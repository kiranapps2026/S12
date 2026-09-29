"""
The S0–S11 pipeline runner — the one execution path before S12.

Source: DATA_CONTRACTS.md §2, PIPELINE_STAGES.md §11, RUNBOOK R-C/R-I/R-N

- Stages run in PRE_EXECUTION_SEQUENCE order, S0 first; every handler is awaited.
- A stage continues the run only with StageStatus.NORMAL. DENY / CLARIFY / ERROR (or a
  missing status) stop it; no later stage runs and none writes output.
- An uncaught exception in a stage becomes ERROR and stops the run; it is never re-raised
  into the caller and never leaves a half-run state that looks successful.
- Enforcement does not trust a handler's status alone: after S7, S8, S10 and S11 the
  runner checks the stage's own output and stops the run if it says "no".
- Dependencies arrive from one composition root, build_pipeline(); there are no globals.
- S0.1 (activation check) runs right after S0, before anything else, and on every reply.
- Tenant-specific dependencies (live kill switch, RLS-bound authorization state, policy
  versions) are resolved once per run, right after S0 identified the tenant, through the
  RunScopeFactory. If they cannot be read the run ends in ERROR before S1.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from contracts.activation import ActivationStateReader
from contracts.capability import CapabilityRegistry
from contracts.intent_model import IntentModel
from contracts.errors import UnknownConfirmation
from contracts.pipeline_state import PRE_EXECUTION_SEQUENCE, PipelineState
from contracts.suspended_runs import SuspendedRunStore
from contracts.safety import PathDecision
from contracts.stage_registry import StageStatus
from engine.stages.s0_entry.activation import activation_denial
from engine.stages.s0_entry.handler import EntryRequest, handle as s0
from engine.stages.s1_normalize.handler import handle as s1
from engine.stages.s2_intent_analysis.handler import handle as s2
from engine.stages.s3_capability_discovery.handler import handle as s3
from engine.stages.s4_graph_classification.handler import handle as s4
from engine.stages.s5_provider_resolution.handler import handle as s5
from engine.stages.s6_task_profile_assembly.handler import handle as s6
from engine.stages.s7_path_decision.handler import handle as s7
from engine.control_plane.scope import RunScope, RunScopeFactory
from engine.stages.s8_safety_gate.handler import handle as s8, recheck_safety
from engine.stages.s9_plan_creation.handler import handle as s9
from engine.stages.s10_confirmation.handler import handle as s10, resume_confirmation
from engine.stages.s10_confirmation.store import ConfirmationStore
from engine.stages.s11_plan_validation.handler import handle as s11

logger = logging.getLogger(__name__)

StageHandler = Callable[[PipelineState], Awaitable[PipelineState]]


@dataclass(frozen=True)
class PipelineDependencies:
    """Everything S0–S11 need from outside. Built once, passed to build_pipeline()."""
    intent_model: IntentModel
    registry: CapabilityRegistry
    scopes: RunScopeFactory
    confirmation_store: ConfirmationStore
    suspended: SuspendedRunStore
    activation: ActivationStateReader


@dataclass(frozen=True)
class PipelineRunResult:
    """Result of an S0–S11 run."""
    final_state: PipelineState
    final_stage: str                       # the stage that ended the run
    status: StageStatus                    # NORMAL only if the run completed
    reason: str | None = None
    stages_run: tuple[str, ...] = ()
    duration_ms: float = 0.0


def _enforce(stage_id: str, state: PipelineState) -> tuple[StageStatus, str] | None:
    """Independent check of a stage's own output; returns a stop (status, reason) or None."""
    if stage_id == "S7" and state.path_decision is not None:
        d = state.path_decision
        if d.decision is PathDecision.DENY:
            return StageStatus.DENY, d.reason or "path_denied"
        if d.decision is PathDecision.CLARIFY:
            return StageStatus.CLARIFY, d.reason or "path_clarify"
    elif stage_id == "S8":
        sr = state.safety_result
        if sr is None or sr.allowed is not True:
            return StageStatus.DENY, (sr.reason if sr else None) or "safety_not_passed"
    elif stage_id == "S10":
        outcome = state.confirmation
        if outcome is None:
            return StageStatus.ERROR, "confirmation_missing"
        if outcome.required and (outcome.confirmation is None
                                 or outcome.confirmation.consumed_at is None):
            return StageStatus.CLARIFY, "confirmation_required"
    elif stage_id == "S11":
        vr = state.validation_result
        if vr is None or vr.is_valid is not True or state.execution_manifest is None:
            return StageStatus.DENY, (vr.errors[0] if vr and vr.errors else "plan_invalid")
    return None


class PipelineRunner:
    """Runs S0–S11. Construct with build_pipeline()."""

    def __init__(self, deps: PipelineDependencies) -> None:
        self._deps = deps
        self._wrappers: dict[str, Callable[[StageHandler], StageHandler]] = {}

    def wrap(self, stage_id: str, wrapper: Callable[[StageHandler], StageHandler]) -> None:
        """Replace stage_id's handler with wrapper(real_handler). For tests and instrumentation."""
        if stage_id not in PRE_EXECUTION_SEQUENCE[1:]:
            raise ValueError(f"Unknown stage {stage_id}")
        self._wrappers[stage_id] = wrapper

    def handlers(self, scope: RunScope) -> dict[str, StageHandler]:
        """The S1..S11 handlers bound to this run's dependencies."""
        d = self._deps
        table: dict[str, StageHandler] = {
            "S1": s1,
            "S2": lambda st: s2(st, d.intent_model, d.registry),
            "S3": lambda st: s3(st, d.registry),
            "S4": s4,
            "S5": lambda st: s5(st, d.registry, scope.policy_versions),
            "S6": s6,
            "S7": lambda st: s7(st, scope.policy),
            "S8": lambda st: s8(st, scope.s8),
            "S9": s9,
            "S10": lambda st: s10(st, d.confirmation_store),
            "S11": s11,
        }
        return {k: self._wrappers[k](v) if k in self._wrappers else v for k, v in table.items()}

    async def _scope_for(self, state: PipelineState) -> RunScope:
        ctx = state.execution_context
        return await self._deps.scopes.for_run(ctx.tenant_id, ctx.workspace_id)

    async def run(self, entry: EntryRequest, *, stop_after: str | None = None) -> PipelineRunResult:
        """Run S0 then S1..S11 (or up to and including `stop_after`)."""
        start = time.monotonic()
        stages: list[str] = []

        try:
            state = await s0(entry)
        except Exception as exc:  # noqa: BLE001 — becomes ERROR, never escapes
            logger.exception("S0 failed")
            return self._result(PipelineState(), "S0", StageStatus.ERROR,
                                type(exc).__name__, stages, start)
        stages.append("S0")
        stop = self._stop_check("S0", state)
        if stop is not None or stop_after == "S0":
            return self._result(state, "S0", *(stop or (StageStatus.NORMAL, None)), stages, start)

        # S0.1: a paused / not-yet-active tenant or workspace runs no S1–S11 work
        denied = await activation_denial(state, self._deps.activation)
        if denied is not None:
            return self._result(state.with_status(StageStatus.DENY, denied), "S0",
                                StageStatus.DENY, denied, stages, start)

        try:
            scope = await self._scope_for(state)
        except Exception as exc:  # noqa: BLE001 — fail closed: no scope, no run
            logger.exception("Run scope unavailable")
            return self._result(state, "S0", StageStatus.ERROR, "scope_unavailable", stages, start)
        result = await self._run_from(state, self.handlers(scope), PRE_EXECUTION_SEQUENCE[1:],
                                      stages, start, stop_after)
        if (result.final_stage == "S10" and result.status is StageStatus.CLARIFY
                and result.reason == "confirmation_required"):
            return await self._suspend(result)
        return result

    async def reply(self, tenant_id: str, confirmation_id: str, user_id: str,
                    approved: bool) -> PipelineRunResult:
        """The authenticated user's answer to a confirmation, for the run waiting on it.

        Raises UnknownConfirmation if this tenant has no such waiting run. The reply is
        checked against the authenticated `user_id` (never the stored one); a rejection
        ends the run; an approval re-checks authorization (the kill switch or the user's
        status may have changed since S8), consumes the confirmation exactly once, then
        runs S11.
        """
        start = time.monotonic()
        stages = list(PRE_EXECUTION_SEQUENCE[:11])
        suspended = await self._deps.suspended.load(tenant_id=tenant_id, confirmation_id=confirmation_id)
        if suspended is None:
            raise UnknownConfirmation(confirmation_id)
        denied = await activation_denial(suspended, self._deps.activation)   # S0.1 applies to replies
        if denied is not None:
            return self._result(suspended, "S0", StageStatus.DENY, denied, stages, start)
        try:
            if not approved:
                rejected = await self._deps.confirmation_store.reject(
                    confirmation_id, tenant_id=tenant_id, user_id=user_id)
                reason = "confirmation_rejected" if rejected else "confirmation_mismatch"
                return self._result(suspended, "S10", StageStatus.DENY, reason, stages, start)
            scope = await self._scope_for(suspended)
            stale = await recheck_safety(suspended, scope.s8)
            if stale is not None:
                return self._result(suspended, "S8", StageStatus.DENY, stale[0], stages, start)
            state = await resume_confirmation(suspended, self._deps.confirmation_store, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 — becomes ERROR, never escapes
            logger.exception("Confirmation reply failed")
            return self._result(suspended, "S10", StageStatus.ERROR, type(exc).__name__, stages, start)
        if state.stage_status is not StageStatus.NORMAL:
            return self._result(state, "S10", state.stage_status or StageStatus.ERROR,
                                state.deny_reason, stages, start)
        stop = self._stop_check("S10", state)
        if stop is not None:
            return self._result(state, "S10", *stop, stages, start)
        return await self._run_from(state, self.handlers(scope), ("S11",), stages, start, None)

    async def _suspend(self, result: PipelineRunResult) -> PipelineRunResult:
        """Store the state S10 left so a reply can resume it, even after a restart. If it
        cannot be stored the run ends in ERROR: nobody could ever answer the confirmation."""
        state = result.final_state
        try:
            await self._deps.suspended.save(
                state, tenant_id=state.execution_context.tenant_id,
                execution_id=state.plan.execution_id,
                confirmation_id=state.confirmation.confirmation.confirmation_id)
        except Exception:  # noqa: BLE001
            logger.exception("Suspended run could not be stored")
            return dataclasses.replace(result, status=StageStatus.ERROR,
                                       reason="suspended_run_unrecorded")
        return result

    async def _run_from(self, state: PipelineState, handlers: dict[str, StageHandler],
                        sequence: tuple[str, ...], stages: list[str], start: float,
                        stop_after: str | None) -> PipelineRunResult:
        final_stage = stages[-1] if stages else "S0"
        for stage_id in sequence:
            final_stage = stage_id
            try:
                state = await handlers[stage_id](state)
            except Exception as exc:  # noqa: BLE001 — becomes ERROR, never escapes
                logger.exception("Stage %s raised", stage_id)
                return self._result(state, stage_id, StageStatus.ERROR,
                                    type(exc).__name__, stages, start)
            stages.append(stage_id)
            stop = self._stop_check(stage_id, state)
            if stop is not None:
                logger.info("Run stopped at %s: %s (%s)", stage_id, stop[0], stop[1])
                return self._result(state, stage_id, *stop, stages, start)
            if stop_after == stage_id:
                break
        return self._result(state, final_stage, StageStatus.NORMAL, None, stages, start)

    @staticmethod
    def _stop_check(stage_id: str, state) -> tuple[StageStatus, str | None] | None:
        if not isinstance(state, PipelineState):
            return StageStatus.ERROR, "handler_returned_non_state"
        status = state.stage_status
        if status is None:
            return StageStatus.ERROR, "stage_status_missing"
        if status is not StageStatus.NORMAL:
            return status, state.deny_reason
        return _enforce(stage_id, state)

    @staticmethod
    def _result(state: PipelineState, stage_id: str, status: StageStatus, reason: str | None,
                stages: list[str], start: float) -> PipelineRunResult:
        return PipelineRunResult(
            final_state=state, final_stage=stage_id, status=status, reason=reason,
            stages_run=tuple(stages), duration_ms=(time.monotonic() - start) * 1000,
        )


def build_pipeline(deps: PipelineDependencies) -> PipelineRunner:
    """The composition root for S0–S11: the only place handlers meet dependencies."""
    return PipelineRunner(deps)
