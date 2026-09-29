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
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping

from contracts.capability import CapabilityRegistry
from contracts.kernel_policy import KernelPolicy
from contracts.pipeline_state import PRE_EXECUTION_SEQUENCE, PipelineState
from contracts.safety import PathDecision
from contracts.stage_registry import StageStatus
from engine.stages.s0_entry.handler import EntryRequest, handle as s0
from engine.stages.s1_normalize.handler import handle as s1
from engine.stages.s2_intent_analysis.handler import LLMProvider, handle as s2
from engine.stages.s3_capability_discovery.handler import handle as s3
from engine.stages.s4_graph_classification.handler import handle as s4
from engine.stages.s5_provider_resolution.handler import handle as s5
from engine.stages.s6_task_profile_assembly.handler import handle as s6
from engine.stages.s7_path_decision.handler import handle as s7
from engine.stages.s8_safety_gate.dependencies import S8Dependencies
from engine.stages.s8_safety_gate.handler import handle as s8
from engine.stages.s9_plan_creation.handler import handle as s9
from engine.stages.s10_confirmation.handler import handle as s10, resume_confirmation
from engine.stages.s10_confirmation.store import ConfirmationStore
from engine.stages.s11_plan_validation.handler import handle as s11

logger = logging.getLogger(__name__)

StageHandler = Callable[[PipelineState], Awaitable[PipelineState]]


@dataclass(frozen=True)
class PipelineDependencies:
    """Everything S0–S11 need from outside. Built once, passed to build_pipeline()."""
    llm: LLMProvider
    registry: CapabilityRegistry
    policy: KernelPolicy
    s8: S8Dependencies
    confirmation_store: ConfirmationStore


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

    def __init__(self, handlers: Mapping[str, StageHandler], deps: PipelineDependencies) -> None:
        missing = [s for s in PRE_EXECUTION_SEQUENCE[1:] if s not in handlers]
        if missing:
            raise ValueError(f"PipelineRunner missing handlers for {missing}")
        self._handlers = dict(handlers)
        self._deps = deps

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

        return await self._run_from(state, PRE_EXECUTION_SEQUENCE[1:], stages, start, stop_after)

    async def resume(self, suspended: PipelineState) -> PipelineRunResult:
        """Confirmed re-entry after S10: consume the confirmation, then run S11."""
        start = time.monotonic()
        stages = list(PRE_EXECUTION_SEQUENCE[:11])
        try:
            state = resume_confirmation(suspended, self._deps.confirmation_store)
        except Exception as exc:  # noqa: BLE001
            logger.exception("S10 resume failed")
            return self._result(suspended, "S10", StageStatus.ERROR, type(exc).__name__, stages, start)
        if state.stage_status is not StageStatus.NORMAL:
            return self._result(state, "S10", state.stage_status or StageStatus.ERROR,
                                state.deny_reason, stages, start)
        stop = self._stop_check("S10", state)
        if stop is not None:
            return self._result(state, "S10", *stop, stages, start)
        return await self._run_from(state, ("S11",), stages, start, None)

    async def _run_from(self, state: PipelineState, sequence: tuple[str, ...],
                        stages: list[str], start: float, stop_after: str | None) -> PipelineRunResult:
        final_stage = stages[-1] if stages else "S0"
        for stage_id in sequence:
            final_stage = stage_id
            try:
                state = await self._handlers[stage_id](state)
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
    handlers: dict[str, StageHandler] = {
        "S1": s1,
        "S2": lambda st: s2(st, deps.llm),
        "S3": lambda st: s3(st, deps.registry),
        "S4": s4,
        "S5": lambda st: s5(st, deps.registry),
        "S6": s6,
        "S7": lambda st: s7(st, deps.policy),
        "S8": lambda st: s8(st, deps.s8),
        "S9": s9,
        "S10": lambda st: s10(st, deps.confirmation_store),
        "S11": s11,
    }
    return PipelineRunner(handlers, deps)
