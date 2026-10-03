"""S12 step loop (gate §8), reference for golden M12."""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from adapters.postgres.fencing import FenceHolder
from contracts import metrics as m
from contracts.execution_states import DeadLetterErrorType as ErrorType
from contracts.execution_states import ExecutionStatus as R
from contracts.execution_states import ReconciliationKind as K
from contracts.execution_states import ReconciliationOutcome as O
from contracts.execution_states import ReconciliationStatus as E
from contracts.execution_states import RetryMode
from contracts.execution_states import StepState as S
from contracts.execution_states import StepTerminalReason as T
from contracts.idempotency import IdempotencyConflict, attempt_id, step_idempotency_key
from contracts.metrics import NoMetrics
from contracts.step_admission import AdmissionStatus
from contracts.step_execution import FencedOut
from contracts.verification import LayerResult, Verdict, VerificationLayer, VerificationOutcome
from engine.stages.s12_execute.admission_control import admit_step, reject_outcome
from engine.stages.s12_execute.attempts import AttemptDeps, StepAttempt, run_attempts
from engine.stages.s12_execute.eligibility import (
    binding_requirements,
    filter_workers,
    record_filtering,
    step_context,
)
from engine.stages.s12_execute.fault_injection import NoFaults
from engine.stages.s12_execute.retry_policy import max_attempts
from engine.stages.s12_execute.selection import lease_for_step
from engine.stages.s13_reconciliation import probe

logger = logging.getLogger(__name__)

LAYER_EVENT = "verification_layer"
REVOKED_EVENT = "authorization_revoked"
REVOCATION, BUDGET = "revocation", "budget"
_TERMINAL_STEP = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED, S.SKIPPED, S.DEAD_LETTER})
FENCED_OUT, PLAN_INTEGRITY = "fenced_out", "plan_integrity"


def topological_order(steps) -> list:
    by_id = {s.id: s for s in steps}
    if len(by_id) != len(steps) or any(d not in by_id for s in steps for d in s.depends_on):
        raise ValueError("unknown or duplicate step id")
    remaining = {s.id: set(s.depends_on) for s in steps}
    out = []
    while remaining:
        ready = [s for s in steps if s.id in remaining and not remaining[s.id]]
        if not ready:
            raise ValueError("dependency cycle")
        step = ready[0]
        out.append(step)
        del remaining[step.id]
        for deps in remaining.values():
            deps.discard(step.id)
    return out


@dataclass(frozen=True)
class LoopSettings:
    admission_max_attempts: int
    lease_max_attempts: int
    lease_ttl_s: float
    backoff_base_s: float
    ledger_ttl_s: float
    step_timeout_s: float | None = None
    probe_max_attempts: int = 3
    probe_backoff_s: float = 1.0
    verification_max_attempts: int = 3
    verification_backoff_s: float = 1.0
    queue_retry_after_ms: int = 1000   # admission QUEUE retry (IMP-M08-1)
    delay_retry_after_ms: int = 500    # admission DELAY retry (IMP-M08-1)


@dataclass(frozen=True)
class LoopDeps:
    runtime_instance_id: str
    store: Any
    events: Any
    admission: Callable[[str, str, str], Awaitable[Any]]
    selection: Any
    leases: Any
    budget: Any
    kernel_policy: Any
    preflight: Callable
    guard: Any
    idempotency: Any
    attempts: Any
    live: Any
    verify: Callable
    consolidate: Callable
    sleep: Callable
    settings: LoopSettings
    episodes: Any = None
    verification: Any = None          # M15 StepVerifier; None: the injected ``verify`` decides
    dead_letters: Any = None          # M17 PostgresDeadLetters; None: no records
    cancel_run: Any = None            # M16 PostgresConsolidator.cancel; None: the store moves the run
    faults: Any = NoFaults()          # M19 fault injection (§15.2): inert unless a test injects one
    metrics: Any = NoMetrics()        # M21 metrics hook (§21 S5): a no-op unless one is injected


@dataclass(frozen=True)
class LoopResult:
    run_status: str
    steps: dict
    reason: str | None = None


class _Run:
    """Mutable per-run state of one loop invocation (never module level)."""
    def __init__(self, deps: LoopDeps, loaded) -> None:
        self.deps, self.loaded = deps, loaded
        self.statuses = {sid: (row.status, None) for sid, row in loaded.steps.items()}
        self.holder = FenceHolder(tenant_id=loaded.tenant_id, execution_id=loaded.execution_id,
                                  runtime_instance_id=deps.runtime_instance_id, fence_token=loaded.owner_token)
        self.owner_worker: str | None = None
        self.requirements: dict = {}
        self.lease = None                       # the lease this loop holds right now, if any

    def log(self, message: str, step_id: str | None = None, *, level: int = logging.INFO, **extra) -> None:
        fields = {"trace_id": self.loaded.trace_id, "execution_id": self.loaded.execution_id,
                  "tenant_id": self.loaded.tenant_id, "runtime_instance_id": self.deps.runtime_instance_id,
                  "step_id": step_id, **extra}
        logger.log(level, json.dumps({"event": message, **fields}, sort_keys=True), extra=fields)

    async def release(self, reason: str = "work_complete") -> None:
        """Release the held lease once (Appendix A.4); nothing when none is held."""
        lease, self.lease = self.lease, None
        if lease is not None:
            await self.deps.leases.release(lease, reason=reason)

    def recorder(self, step_id: str | None = None):
        return self.deps.events.recorder(self.holder, trace_id=self.loaded.trace_id, step_id=step_id)

    async def set_step(self, sid: str, to: str, *, reason: str, terminal_reason=None, **kw) -> None:
        await self.deps.store.transition_step(self.holder, self.loaded.steps[sid].step_id, to, reason=reason,
                                              terminal_reason=terminal_reason, **kw)
        self.statuses[sid] = (to, terminal_reason)
        if to in _TERMINAL_STEP:
            self.deps.metrics.increment(m.STEP_OUTCOME, status=str(to))

    async def cancel_remaining(self, reason: str) -> None:
        for sid, (status, _) in list(self.statuses.items()):
            if status == S.PENDING:
                await self.set_step(sid, S.CANCELLED, reason=reason, terminal_reason=reason)

    async def skip_dependents(self, failed: str) -> None:
        blocked = {failed}
        for step in topological_order(self.loaded.plan.steps):
            if blocked & set(step.depends_on):
                blocked.add(step.id)
                if self.statuses[step.id][0] == S.PENDING:
                    await self.set_step(step.id, S.SKIPPED, reason=T.DEPENDENCY_FAILED,
                                        terminal_reason=T.DEPENDENCY_FAILED)


async def run_execution(deps: LoopDeps, tenant_id: str, execution_id: str) -> LoopResult:
    loaded = await deps.store.load(tenant_id, execution_id)
    if loaded is None:
        raise LookupError(f"no such execution {execution_id}")
    state = _Run(deps, loaded)
    if loaded.run_status != R.RUNNING:
        return LoopResult(loaded.run_status, dict(state.statuses))
    if loaded.owner_runtime != deps.runtime_instance_id:       # never a takeover: only recovery takes ownership
        state.log("not_owner", level=logging.WARNING, reason=FENCED_OUT)
        return LoopResult(loaded.run_status, dict(state.statuses), FENCED_OUT)
    try:
        return await _drive(state)
    except FencedOut:                                          # §8 step 8, C25: stop all work at once
        deps.metrics.increment(m.FENCED_OUT)
        state.log("fenced_out", level=logging.WARNING, reason=FENCED_OUT)
        await state.release(FENCED_OUT)
        return LoopResult(loaded.run_status, dict(state.statuses), FENCED_OUT)


async def _drive(state: _Run) -> LoopResult:
    deps, loaded = state.deps, state.loaded
    tenant_id, execution_id = loaded.tenant_id, loaded.execution_id
    if not loaded.plan_intact:                                 # gate §7.3: never execute a plan that changed
        state.log("plan_integrity_violation", level=logging.ERROR, reason=PLAN_INTEGRITY)
        await state.cancel_remaining(T.RUN_DEAD_LETTERED)
        await deps.consolidate(state.holder, tenant_id, execution_id)
        return LoopResult(R.RUNNING, dict(state.statuses), PLAN_INTEGRITY)
    state.requirements = await binding_requirements(deps.selection, sorted({b.binding_id for b in
                                                                             loaded.bindings.values()}))
    for step in topological_order(loaded.plan.steps):
        if state.statuses[step.id][0] != S.PENDING:
            continue
        if await deps.store.cancel_requested(tenant_id, execution_id):          # C16: before each step
            return await _end_run(state, step.id, T.USER_CANCELLED, REVOCATION)
        ended = await _run_step(state, step)
        if ended is not None:
            return ended
    await deps.consolidate(state.holder, tenant_id, execution_id)
    return LoopResult(R.RUNNING, dict(state.statuses))


async def _end_run(state: _Run, sid: str, reason: str, path: str) -> LoopResult | None:
    """A run-ending trigger: this step and every remaining PENDING step get its reason (C22)."""
    await state.set_step(sid, S.CANCELLED, reason=reason, terminal_reason=reason)
    await state.cancel_remaining(reason)
    state.log("run_ended", step_id=state.loaded.steps[sid].step_id, reason=str(reason))
    if path in (REVOCATION, BUDGET):
        if state.deps.cancel_run is not None:
            await state.deps.cancel_run(state.holder, state.loaded.tenant_id, state.loaded.execution_id,
                                        reason=reason)
        else:
            await state.deps.store.transition_run(state.holder, R.CANCELLED, reason=reason, terminal_reason=reason)
        return LoopResult(R.CANCELLED, dict(state.statuses), reason)
    await state.deps.consolidate(state.holder, state.loaded.tenant_id, state.loaded.execution_id)
    return LoopResult(R.RUNNING, dict(state.statuses), reason)


async def _run_step(state: _Run, step) -> LoopResult | None:
    started = time.monotonic()
    try:
        return await _run_step_timed(state, step)
    finally:
        state.deps.metrics.timing(m.STEP_DURATION_MS, (time.monotonic() - started) * 1000)


async def _run_step_timed(state: _Run, step) -> LoopResult | None:
    deps, loaded = state.deps, state.loaded
    row, binding = loaded.steps[step.id], loaded.bindings[step.id]
    state.log("step_considered", step_id=row.step_id)

    # 0. live authorization at the start of every step (C23, C30)
    revoked = await _live(state, binding)
    if revoked is not None:
        await state.recorder(row.step_id).record(REVOKED_EVENT, {"reason": revoked.reason})
        return await _end_run(state, step.id, revoked.reason, REVOCATION)

    # 1. admission
    async def snapshot():
        return await deps.admission(loaded.tenant_id, loaded.execution_id, step.id)
    decision = await admit_step(snapshot, ledger=state.recorder(row.step_id),
                                max_attempts=deps.settings.admission_max_attempts, sleep=deps.sleep,
                                queue_retry_ms=deps.settings.queue_retry_after_ms,
                                delay_retry_ms=deps.settings.delay_retry_after_ms)
    if decision.status == AdmissionStatus.REJECT:
        reason, path = reject_outcome(decision)
        return await _end_run(state, step.id, reason, path)

    # 2–3. eligibility, selection, lease
    admin = await deps.selection.is_workspace_admin(loaded.tenant_id, loaded.workspace_id, loaded.user_id)
    ctx = step_context(workspace_id=loaded.workspace_id, binding=binding, requirements=state.requirements,
                       principal_id=loaded.user_id, principal_is_human=loaded.actor_type == "user",
                       event_driven=False, admin=admin, now=await deps.selection.database_now())

    async def candidates():
        result = filter_workers(await deps.selection.candidates(loaded.tenant_id), ctx)
        await record_filtering(state.recorder(row.step_id), result)
        return result.eligible

    async def acquire(worker_id):
        return await deps.leases.acquire(tenant_id=loaded.tenant_id, worker_id=worker_id,
                                         execution_id=loaded.execution_id,
                                         runtime_instance_id=deps.runtime_instance_id,
                                         ttl_s=deps.settings.lease_ttl_s, holder=state.holder)
    lease = await lease_for_step(candidates=candidates, acquire=acquire, current_owner=state.owner_worker,
                                 max_attempts=deps.settings.lease_max_attempts)
    if isinstance(lease, str):
        return await _end_run(state, step.id, lease, "consolidate")
    state.owner_worker, state.lease = lease.worker_id, lease
    state.holder = FenceHolder(tenant_id=loaded.tenant_id, execution_id=loaded.execution_id,
                               runtime_instance_id=deps.runtime_instance_id, fence_token=lease.fence_token)
    deps.faults.hit("after_lease_acquire")

    first_attempt = (row.dispatched_attempt or 0) + 1       # after a recovered NOT_EXECUTED: the next attempt
    while True:
        verdict = await _execute(state, step, row, binding, first_attempt)
        if not isinstance(verdict, int):
            return verdict
        first_attempt = verdict                         # NOT_EXECUTED / read re-execution: retry as this attempt
        stop = T.USER_CANCELLED if await deps.store.cancel_requested(loaded.tenant_id, loaded.execution_id) else None
        if stop is None:
            revoked = await _live(state, binding)
            if revoked is not None:
                await state.recorder(row.step_id).record(REVOKED_EVENT, {"reason": revoked.reason})
                stop = revoked.reason
        if stop is not None:                            # a retry would be a new side effect (C16, C23)
            await state.release()
            return await _end_run(state, step.id, stop, REVOCATION)


async def _execute(state: _Run, step, row, binding, first_attempt: int):
    """Steps 5–12 for one reservation. Returns None (step settled), a LoopResult (the run ended) or the next attempt
    number (the step is PENDING again and may be retried)."""
    deps, loaded = state.deps, state.loaded

    # 5. budget
    reservation = await deps.budget.reserve(state.holder, user_id=loaded.user_id, step_id=row.step_id,
                                            cost=step.cost)
    if reservation.reservation_id is None:
        await state.release()
        return await _end_run(state, step.id, T.BUDGET_EXHAUSTED, BUDGET)
    rid = reservation.reservation_id
    deps.faults.hit("after_budget_reserve")

    # 6. pre-flight
    problem = await deps.preflight(step, binding)
    if problem is not None:
        await state.set_step(step.id, S.CANCELLED, reason=T.PREFLIGHT_FAILED, terminal_reason=T.PREFLIGHT_FAILED,
                             error=problem, budget=deps.budget, reservation_id=rid, budget_move="release",
                             budget_reason=T.PREFLIGHT_FAILED)
        await state.release()
        await state.skip_dependents(step.id)
        return None

    # 7. start (I-3)
    await state.set_step(step.id, S.RUNNING, reason="started", budget=deps.budget, reservation_id=rid,
                         budget_move="lock", budget_reason="step_started")
    state.log("step_started", step_id=row.step_id)
    deps.faults.hit("after_budget_lock")

    # 8. attempts
    timeout = float(step.timeout)
    if deps.settings.step_timeout_s is not None:
        timeout = min(timeout, deps.settings.step_timeout_s)
    retry_safety = await deps.kernel_policy.retry_safety(step.kernel_op_id)
    attempt = StepAttempt(request_id=loaded.request_id, plan_step_id=step.id, step_index=row.index,
                          step_id=row.step_id, kernel_op_id=step.kernel_op_id, params=dict(step.params),
                          mutation=step.mutation, retry_safety=retry_safety,
                          step_max_attempts=step.retry_policy.get("max_attempts"), reservation_id=rid,
                          timeout_s=timeout, binding=binding, context=_context(loaded))
    recorder = state.recorder(row.step_id)
    outcome = await run_attempts(attempt, state.holder, AttemptDeps(
        guard=deps.guard, ledger=deps.idempotency, attempts=deps.attempts, live=deps.live, events=recorder,
        sleep=deps.sleep, backoff_base_s=deps.settings.backoff_base_s, ledger_ttl_s=deps.settings.ledger_ttl_s,
        faults=deps.faults),
        first_attempt=first_attempt)

    if outcome.kind == "success":
        return await _settle_success(state, step, row, binding, rid, outcome.result,
                                     "ledger_hit_verified" if outcome.cached else "verified")
    if outcome.kind == "failure":
        reason = "ledger_hit_failure" if outcome.cached else (
            "retries_exhausted" if outcome.result is not None and outcome.result.retryable else "non_retryable_error")
        await _settle_failure(state, step, row, rid, reason)
        if reason == "retries_exhausted":             # §11; a client error (401/403/404/422) gets none
            await _dead_letter_record(state, step, row, rid, error_type=ErrorType.TRANSIENT, retry_mode=RetryMode.NONE,
                                      error=reason, attempt=attempt_id(row.index, outcome.attempts),
                                      evidence={"attempts": outcome.attempts,
                                                "error_class": str(outcome.result.error_class)})
        return None
    if outcome.kind == "revoked":
        # C23/C35: the current attempt was never dispatched: NOT_EXECUTED with evidence no_dispatch_marker
        await state.set_step(step.id, S.PENDING_PROBE, reason="execution_uncertain")
        await deps.episodes.open_and_close(state.holder, step_id=row.step_id, kind=K.EXECUTION,
                                           status=E.CONFIRMED_FAILURE, outcome=O.NOT_EXECUTED, reason="not_executed",
                                           evidence={"reason": "no_dispatch_marker"})
        await state.set_step(step.id, S.PENDING, reason="no_dispatch_marker", budget=deps.budget,
                             reservation_id=rid, budget_move="release", budget_reason="no_dispatch_marker")
        await recorder.record(REVOKED_EVENT, {"reason": outcome.reason})
        await state.release()
        return await _end_run(state, step.id, outcome.reason, REVOCATION)

    # §9: every uncertainty passes through PENDING_PROBE
    if outcome.reason == "timeout":
        await state.set_step(step.id, S.TIMEOUT, reason="step_timeout")
        await state.set_step(step.id, S.PENDING_PROBE, reason="step_timeout_probe")
    else:
        await state.set_step(step.id, S.PENDING_PROBE, reason="execution_uncertain")
    episodes = deps.episodes
    if step.mutation == "R":
        await episodes.open_and_close(state.holder, step_id=row.step_id, kind=K.EXECUTION,
                                      status=E.CONFIRMED_FAILURE, outcome=O.NOT_EXECUTED, reason="not_executed",
                                      evidence={"reason": "read_reexecution_safe"})
        return await _not_executed(state, step, row, rid, attempt, outcome.attempts, "read_reexecution_safe")
    episode_id = await episodes.open(state.holder, step_id=row.step_id, kind=K.EXECUTION)
    return await _probe_and_settle(state, step, row, binding, rid, attempt, outcome.attempts, episode_id,
                                   deps.settings.probe_max_attempts)


async def _probe_and_settle(state, step, row, binding, rid, attempt, attempts_used, episode_id, probes_left):
    """§9 on an open EXECUTION episode: probe (ledger first), then settle the step by the answer."""
    deps = state.deps
    episodes = deps.episodes
    found = await probe.resolve_execution(step=attempt, holder=state.holder, episode_id=episode_id,
                                          attempt=attempts_used, guard=deps.guard, ledger=deps.idempotency,
                                          episodes=episodes, events=state.recorder(row.step_id), sleep=deps.sleep,
                                          max_attempts=probes_left, backoff_s=deps.settings.probe_backoff_s,
                                          faults=deps.faults, metrics=deps.metrics)
    if found.kind in (probe.EXECUTED_SUCCESS, probe.LEDGER_SUCCESS):
        ledger = found.kind == probe.LEDGER_SUCCESS
        checked = await _verify(state, step, row, binding, found.result)
        if checked.verdict == Verdict.FAIL:
            await episodes.close(state.holder, episode_id, status=E.CONFIRMED_FAILURE, outcome=O.VERIFIED_FAIL,
                                 reason="verified_fail")
            return await _verification_failed(state, step, row, rid, checked, episode_id)
        await episodes.close(state.holder, episode_id, status=E.CONFIRMED_SUCCESS,
                             outcome=O.LEDGER_HIT if ledger else O.EXECUTED_SUCCESS,
                             reason="ledger_hit" if ledger else "executed_success")
        if checked.verdict == Verdict.UNKNOWN:            # executed, but its effect is unconfirmed: C19
            return await _verification_episode(state, step, row, binding, rid, found.result, checked,
                                               "ledger_hit_success" if ledger else "probe_executed_success")
        return await _commit(state, step, row, binding, rid, "ledger_hit_success" if ledger else "probe_executed_success")
    if found.kind in (probe.EXECUTED_FAILURE, probe.LEDGER_FAILURE):
        ledger = found.kind == probe.LEDGER_FAILURE
        await episodes.close(state.holder, episode_id, status=E.CONFIRMED_FAILURE,
                             outcome=O.LEDGER_HIT if ledger else O.EXECUTED_FAILURE,
                             reason="ledger_hit_failure" if ledger else "executed_failure")
        return await _settle_failure(state, step, row, rid,
                                     "ledger_hit_failure" if ledger else "probe_executed_failure")
    if found.kind == probe.NOT_EXECUTED:
        await episodes.close(state.holder, episode_id, status=E.CONFIRMED_FAILURE, outcome=O.NOT_EXECUTED,
                             reason="not_executed")
        return await _not_executed(state, step, row, rid, attempt, attempts_used, "probe_not_executed")
    # exhausted: D4 — the budget stays LOCKED; no further mutation runs on uncertain state (§8 step 12)
    return await _dead_letter_step(state, step, row, rid, "probe_exhausted", episode_id=episode_id,
                                   retry_mode=RetryMode.PROBE,
                                   evidence={"probe_attempts": deps.settings.probe_max_attempts,
                                             "outcome": str(O.EXHAUSTED),
                                             "attempt_id": attempt_id(row.index, attempts_used)})


# --- verification (§8 step 9, C12, C19, D4) -------------------------------------------------------------------------

def _outcome(found) -> VerificationOutcome:
    """An injected verdict (M12) or a StepVerifier outcome (M15)."""
    if isinstance(found, VerificationOutcome):
        return found
    verdict = Verdict(found) if found in {v.value for v in Verdict} else Verdict.FAIL    # anything else fails closed
    return VerificationOutcome(verdict, ())


def _still_open(checked: VerificationOutcome) -> tuple[tuple[str, ...] | None, bool]:
    """(layers to re-run — None: all, no layer detail —, whether the human layer is pending)."""
    human = VerificationLayer.HUMAN in checked.pending()
    if checked.verdict == Verdict.PASS:
        return (), human
    if not checked.layers:
        return None, False
    return tuple(x for x in checked.pending() if x != VerificationLayer.HUMAN), human


async def _verify(state, step, row, binding, result, layers=None) -> VerificationOutcome:
    deps, loaded = state.deps, state.loaded
    if deps.verification is not None:
        found = await deps.verification.verify(
            step, binding, result, verifier=loaded.verifiers.get(step.id), context=_context(loaded),
            idempotency_key=step_idempotency_key(loaded.request_id, step.id), layers=layers)
    else:
        found = await deps.verify(step, binding, result)
    checked = _outcome(found)
    recorder = state.recorder(row.step_id)
    for n, layer in enumerate(checked.layers):        # persisted before the step commit (§8 step 8)
        await recorder.record(LAYER_EVENT, {"layer": str(layer.layer), "verdict": str(layer.verdict),
                                            "evidence": dict(layer.evidence)})
        if n == 0:
            deps.faults.hit("during_verification")
    if not checked.layers:
        deps.faults.hit("during_verification")
    deps.faults.hit("after_verification_before_step_commit")
    return checked


async def _settle_success(state, step, row, binding, rid, result, reason):
    state.deps.faults.hit("after_ledger_before_verification")
    try:
        checked = await _verify(state, step, row, binding, result)
    except FencedOut:
        raise
    if checked.verdict == Verdict.FAIL:
        return await _verification_failed(state, step, row, rid, checked, None)
    if checked.verdict == Verdict.UNKNOWN:
        await state.set_step(step.id, S.PENDING_PROBE, reason="verification_uncertain")
        return await _verification_episode(state, step, row, binding, rid, result, checked, "verification_passed")
    return await _commit(state, step, row, binding, rid, reason)


async def _verification_episode(state, step, row, binding, rid, result, checked, pass_reason, *,
                                episode_id=None, tries=0):
    """C19: a VERIFICATION episode re-runs only the layers not yet PASS; never the probe, never the adapter.
    Recovery continues an open episode (``episode_id``, ``tries`` attempts already spent)."""
    deps = state.deps
    episodes, settings = deps.episodes, deps.settings
    if episode_id is None:
        episode_id = await episodes.open(state.holder, step_id=row.step_id, kind=K.VERIFICATION)
    rerun, human = _still_open(checked)
    reconciling = False
    while rerun != () and tries < settings.verification_max_attempts:
        if tries:
            await deps.sleep(settings.verification_backoff_s)
        tries += 1
        await episodes.start_attempt(state.holder, episode_id)
        reconciling = True
        again = await _verify(state, step, row, binding, result, layers=rerun)
        if again.verdict == Verdict.FAIL:
            await episodes.close(state.holder, episode_id, status=E.CONFIRMED_FAILURE, outcome=O.VERIFIED_FAIL,
                                 reason="verified_fail")
            return await _verification_failed(state, step, row, rid, again, episode_id)
        rerun, more_human = _still_open(again)
        human = human or more_human
        if rerun == () and not human:
            await episodes.close(state.holder, episode_id, status=E.CONFIRMED_SUCCESS, outcome=O.VERIFIED_PASS,
                                 reason="verified_pass")
            return await _commit(state, step, row, binding, rid, pass_reason)
        await episodes.inconclusive(state.holder, episode_id)
        reconciling = False
    if reconciling:
        await episodes.inconclusive(state.holder, episode_id)
    await episodes.exhaust(state.holder, episode_id)
    await state.recorder(row.step_id).record(probe.CLOSED_EVENT, {"episode_id": episode_id,
                                                                   "outcome": str(O.EXHAUSTED)})
    human_only = rerun == () and human
    return await _dead_letter_step(
        state, step, row, rid, "human_verification_pending" if human_only else "verification_exhausted",
        episode_id=episode_id, retry_mode=RetryMode.NONE if human_only else RetryMode.VERIFY,
        evidence={"verification_attempts": tries, "outcome": str(O.EXHAUSTED),
                  "pending_layers": ["human"] if human_only else list(rerun or ["all"])})


async def _commit(state, step, row, binding, rid, reason):
    deps = state.deps
    undo = None
    if step.mutation in ("W", "D") and binding.inverse_kernel_op_id:
        undo = json.dumps({"inverse_kernel_op_id": binding.inverse_kernel_op_id, "step_id": row.step_id},
                          sort_keys=True)
    await state.set_step(step.id, S.COMPLETED, reason=reason, undo_token=undo, budget=deps.budget,
                         reservation_id=rid, budget_move="commit", budget_reason="step_completed")
    deps.faults.hit("after_commit_before_checkpoint")
    await state.release()
    state.log("step_completed", step_id=row.step_id)
    return None


async def _verification_failed(state, step, row, rid, checked, episode_id):
    """§8 step 9: FAILED, budget released, a dead letter ``data`` / NONE (not retryable, C29)."""
    await _settle_failure(state, step, row, rid, "verification_failed")
    await _dead_letter_record(state, step, row, rid, error_type=ErrorType.DATA, retry_mode=RetryMode.NONE,
                              error="verification_failed", episode_id=episode_id,
                              evidence={"layers": [{"layer": str(x.layer), "verdict": str(x.verdict)}
                                                   for x in checked.layers] or [{"verdict": str(checked.verdict)}]})
    return None


# --- dead letters (§11, D4, D5) --------------------------------------------------------------------------------------

async def _dead_letter_record(state, step, row, rid, *, error_type, retry_mode, error, evidence, episode_id=None,
                              attempt=None):
    if state.deps.dead_letters is None:
        return None
    state.deps.metrics.increment(m.DEAD_LETTER, error_type=str(error_type))
    return await state.deps.dead_letters.create(
        state.holder, step_id=row.step_id, kernel_op_id=step.kernel_op_id, error_type=error_type,
        retry_mode=retry_mode, error=error, evidence=evidence, reservation_id=rid, attempt_id=attempt,
        episode_id=episode_id, mutation=step.mutation)


async def _dead_letter_step(state, step, row, rid, reason, *, episode_id, retry_mode, evidence):
    """Unresolved uncertainty (an EXHAUSTED episode or the human layer): the step DEAD_LETTER with its budget LOCKED
    (D4), a dead letter ``unknown_unresolved``, every remaining PENDING step cancelled ``run_dead_lettered``."""
    deps, loaded = state.deps, state.loaded
    await state.set_step(step.id, S.DEAD_LETTER, reason=reason)
    await _dead_letter_record(state, step, row, rid, error_type=ErrorType.UNKNOWN_UNRESOLVED, retry_mode=retry_mode,
                              error=reason, evidence=evidence, episode_id=episode_id,
                              attempt=evidence.get("attempt_id"))
    await state.release()
    await state.cancel_remaining(T.RUN_DEAD_LETTERED)
    await deps.consolidate(state.holder, loaded.tenant_id, loaded.execution_id)
    return LoopResult(R.RUNNING, dict(state.statuses), T.RUN_DEAD_LETTERED)


async def _settle_failure(state, step, row, rid, reason):
    deps = state.deps
    await state.set_step(step.id, S.FAILED, reason=reason, budget=deps.budget, reservation_id=rid,
                         budget_move="release", budget_reason="step_failed")
    await state.release()
    state.log("step_failed", step_id=row.step_id, reason=reason)
    await state.skip_dependents(step.id)
    return None


async def _not_executed(state, step, row, rid, attempt, attempts_used, reason):
    """The step goes back to PENDING with its budget released; retried within its ceiling, else CANCELLED."""
    deps = state.deps
    budget_reason = "no_dispatch_marker" if reason == "no_dispatch_marker" else "probe_not_executed"
    await state.set_step(step.id, S.PENDING, reason=reason, budget=deps.budget, reservation_id=rid,
                         budget_move="release", budget_reason=budget_reason)
    if attempts_used < max_attempts(attempt.mutation, attempt.retry_safety, attempt.step_max_attempts):
        return attempts_used + 1
    await state.set_step(step.id, S.CANCELLED, reason=T.NOT_EXECUTED_NO_RETRY,
                         terminal_reason=T.NOT_EXECUTED_NO_RETRY)
    await state.release()
    await state.skip_dependents(step.id)
    return None


async def _live(state: _Run, binding):
    loaded = state.loaded
    return await state.deps.live.check(tenant_id=loaded.tenant_id, workspace_id=loaded.workspace_id,
                                       user_id=loaded.user_id, connection_id=loaded.connection_id, binding=binding)


def _context(loaded):
    from contracts.execution_context import ExecutionContext
    return ExecutionContext(trace_id=loaded.trace_id, request_id=loaded.request_id, tenant_id=loaded.tenant_id,
                            workspace_id=loaded.workspace_id, user_id=loaded.user_id,
                            connection_id=loaded.connection_id)



# --- crash recovery (gate §13, C14, C35; rulings CONF-033, CONF-042, CONF-043) ----------------------------------------

from engine.stages.s12_execute.transitions import IN_FLIGHT_STEP_STATES
NOT_ORPHANED = "not_orphaned"


async def recover_execution(deps: LoopDeps, tenant_id: str, execution_id: str) -> LoopResult:
    """Take over an orphaned run (no usable lease), resolve its in-flight step by the single recovery rule of §13 step
    3 — never re-executing it blindly —, then continue the loop from the first PENDING step. Nothing is written when
    the run is not orphaned (its owner is alive or another sweeper holds it)."""
    loaded = await deps.store.load(tenant_id, execution_id)
    if loaded is None:
        raise LookupError(f"no such execution {execution_id}")
    state = _Run(deps, loaded)
    if loaded.run_status not in (R.RUNNING, R.RECONCILING):
        return LoopResult(loaded.run_status, dict(state.statuses))
    order = topological_order(loaded.plan.steps) if loaded.plan is not None else []
    by_id = {s.id: s for s in order}
    flying = [by_id[sid] for sid, (status, _) in state.statuses.items() if status in IN_FLIGHT_STEP_STATES and sid in by_id]
    pending = [s for s in order if state.statuses[s.id][0] == S.PENDING]
    target = (flying or pending or order or [None])[0]
    await deps.leases.expire_lapsed(tenant_id, execution_id)                      # C26: the sweeper observes it
    try:
        lease = await _take_over(state, target)
        if lease is None:
            return LoopResult(loaded.run_status, dict(state.statuses), NOT_ORPHANED)
        ended = await _recover_owned(state, flying, target)
    except FencedOut:
        await state.release(FENCED_OUT)
        return LoopResult(loaded.run_status, dict(state.statuses), FENCED_OUT)
    if ended is None and loaded.run_status == R.RECONCILING:      # C13: from RECONCILING only to a terminal state;
        await state.cancel_remaining(T.NOT_EXECUTED_NO_RETRY)      # a step found not executed cannot run again
        await deps.consolidate(state.holder, tenant_id, execution_id)
        ended = LoopResult(loaded.run_status, dict(state.statuses))
    await state.release()
    if ended is not None:
        return ended
    return await run_execution(deps, tenant_id, execution_id)


async def _take_over(state: _Run, target):
    """Step 1: a new lease (a new, larger token) on an eligible worker, with the ownership compare-and-set; ownership
    rows another sweeper holds are skipped (§21 S4)."""
    deps, loaded = state.deps, state.loaded
    candidates = await deps.selection.candidates(loaded.tenant_id)
    if target is not None:
        state.requirements = await binding_requirements(deps.selection, sorted({b.binding_id for b in
                                                                                 loaded.bindings.values()}))
        admin = await deps.selection.is_workspace_admin(loaded.tenant_id, loaded.workspace_id, loaded.user_id)
        ctx = step_context(workspace_id=loaded.workspace_id, binding=loaded.bindings[target.id],
                           requirements=state.requirements, principal_id=loaded.user_id,
                           principal_is_human=loaded.actor_type == "user", event_driven=False, admin=admin,
                           now=await deps.selection.database_now())
        candidates = filter_workers(candidates, ctx).eligible
    for worker in candidates:
        worker_id = getattr(worker, "worker_id", worker)
        lease = await deps.leases.acquire(tenant_id=loaded.tenant_id, worker_id=worker_id,
                                          execution_id=loaded.execution_id,
                                          runtime_instance_id=deps.runtime_instance_id,
                                          ttl_s=deps.settings.lease_ttl_s, skip_locked=True)
        if lease is not None:
            state.owner_worker, state.lease = lease.worker_id, lease
            state.holder = FenceHolder(tenant_id=loaded.tenant_id, execution_id=loaded.execution_id,
                                       runtime_instance_id=deps.runtime_instance_id, fence_token=lease.fence_token)
            state.log("recovery_takeover", reason="recovery")
            return lease
    return None


async def _recover_owned(state: _Run, flying, target):
    deps, loaded = state.deps, state.loaded
    if not loaded.plan_intact:                                     # step 2: never execute a plan that changed
        state.log("plan_integrity_violation", level=logging.ERROR, reason=PLAN_INTEGRITY)
        for step_id in [sid for sid, (status, _) in state.statuses.items() if status in IN_FLIGHT_STEP_STATES]:
            await _dead_letter_untrusted(state, step_id)
        await state.cancel_remaining(T.RUN_DEAD_LETTERED)
        await deps.consolidate(state.holder, loaded.tenant_id, loaded.execution_id)
        return LoopResult(R.RUNNING, dict(state.statuses), PLAN_INTEGRITY)
    revoked = await _live(state, loaded.bindings[target.id]) if target is not None else None     # step 1a
    for step in flying:                                            # step 3: the in-flight step first
        ended = await _resolve_in_flight(state, step)
        if isinstance(ended, LoopResult):
            return ended
    if revoked is not None:                                        # resolved, then cancelled; never resumed
        await state.recorder().record(REVOKED_EVENT, {"reason": revoked.reason})
        remaining = [s for s in topological_order(loaded.plan.steps) if state.statuses[s.id][0] == S.PENDING]
        if remaining:
            return await _end_run(state, remaining[0].id, revoked.reason, REVOCATION)
        await deps.consolidate(state.holder, loaded.tenant_id, loaded.execution_id)
        return LoopResult(R.RUNNING, dict(state.statuses), revoked.reason)
    return None


async def _dead_letter_untrusted(state: _Run, step_id: str) -> None:
    """CONF-043 (D-3): an in-flight step of a plan that failed its integrity check is never probed or re-run (its call
    cannot be rebuilt from an untrusted plan): DEAD_LETTER with its budget LOCKED, for an operator to resolve (D4);
    an EXECUTION episode is opened and closed (outcome EXHAUSTED, evidence plan_integrity)."""
    deps, row = state.deps, state.loaded.steps[step_id]
    episode_id = await deps.episodes.open(state.holder, step_id=row.step_id, kind=K.EXECUTION)
    await deps.episodes.exhaust(state.holder, episode_id, evidence={"reason": PLAN_INTEGRITY})
    await state.recorder(row.step_id).record(probe.CLOSED_EVENT,
        {"step_id": row.step_id, "episode_id": episode_id, "outcome": str(O.EXHAUSTED)})
    await _to_pending_probe(state, step_id)
    await state.set_step(step_id, S.DEAD_LETTER, reason="probe_exhausted")
    if state.deps.dead_letters is not None:
        state.deps.metrics.increment(m.DEAD_LETTER, error_type=str(ErrorType.UNKNOWN_UNRESOLVED))
        await state.deps.dead_letters.create(
            state.holder, step_id=row.step_id, kernel_op_id=row.kernel_op_id,        # the admitted row, not the plan
            error_type=ErrorType.UNKNOWN_UNRESOLVED, retry_mode=RetryMode.NONE, error=PLAN_INTEGRITY,
            evidence={"reason": PLAN_INTEGRITY}, reservation_id=row.reservation_id, episode_id=episode_id)


async def _to_pending_probe(state: _Run, step_id: str) -> None:
    """RUNNING / UNKNOWN → PENDING_PROBE (recovery), TIMEOUT → PENDING_PROBE (step_timeout_probe); already there: no move."""
    status = state.statuses[step_id][0]
    if status in (S.RUNNING, S.UNKNOWN):
        await state.set_step(step_id, S.PENDING_PROBE, reason="recovery")
    elif status == S.TIMEOUT:
        await state.set_step(step_id, S.PENDING_PROBE, reason="step_timeout_probe")


def _attempt_for(state: _Run, step, row) -> StepAttempt:
    deps, loaded = state.deps, state.loaded
    timeout = float(step.timeout)
    if deps.settings.step_timeout_s is not None:
        timeout = min(timeout, deps.settings.step_timeout_s)
    return StepAttempt(request_id=loaded.request_id, plan_step_id=step.id, step_index=row.index, step_id=row.step_id,
                       kernel_op_id=step.kernel_op_id, params=dict(step.params), mutation=step.mutation,
                       retry_safety="never", step_max_attempts=step.retry_policy.get("max_attempts"),
                       reservation_id=row.reservation_id, timeout_s=timeout, binding=loaded.bindings[step.id],
                       context=_context(loaded))


async def _layers_passed(state: _Run, step, row, binding) -> bool:
    """Every required layer's latest persisted verdict is PASS (§13 step 3)."""
    from engine.stages.s13_reconciliation.verification import required_verification_layers
    latest = await state.deps.events.layer_verdicts(state.loaded.tenant_id, row.step_id)
    required = required_verification_layers(step.mutation, binding.effective_risk)
    return bool(latest) and all(latest.get(layer) == Verdict.PASS for layer in required)


async def _resolve_in_flight(state: _Run, step):
    """§13 step 3, the single recovery decision rule. The existing reservation is reused (C35); a new one is created
    only for a retry after NOT_EXECUTED. CONF-050 (D-10): recorded layer verdicts are checked before re-running a
    VERIFICATION episode, so a FAIL is never overturned by re-verification."""
    deps, loaded = state.deps, state.loaded
    row, binding = loaded.steps[step.id], loaded.bindings[step.id]
    rid = row.reservation_id
    retry_safety = await deps.kernel_policy.retry_safety(step.kernel_op_id)
    attempt = dataclasses.replace(_attempt_for(state, step, row), retry_safety=retry_safety)
    await _to_pending_probe(state, step.id)
    used = row.dispatched_attempt or 0
    # CONF-050 (D-10): before any re-run, check recorded layer verdicts — a FAIL is never overturned
    verdicts = await deps.events.layer_verdicts(loaded.tenant_id, row.step_id)
    if verdicts and any(v == Verdict.FAIL for v in verdicts.values()):
        episode_id = None
        open_episode = await deps.episodes.find_open(loaded.tenant_id, row.step_id)
        if open_episode is not None and open_episode["kind"] == K.VERIFICATION:
            episode_id = open_episode["episode_id"]
            if open_episode["status"] == E.RECONCILING:
                await deps.episodes.inconclusive(state.holder, episode_id)
            await deps.episodes.start_attempt(state.holder, episode_id)
            await deps.episodes.close(state.holder, episode_id, status=E.CONFIRMED_FAILURE,
                                       outcome=O.VERIFIED_FAIL, reason="verified_fail",
                                       evidence={"recovered": True, "layers": dict(verdicts)})
        checked = VerificationOutcome(Verdict.FAIL,
            tuple(LayerResult(k, v, {}) for k, v in verdicts.items()))
        return await _verification_failed(state, step, row, rid, checked, episode_id)
    episodes = deps.episodes
    open_episode = await episodes.find_open(loaded.tenant_id, row.step_id)
    if open_episode is not None:                                   # continue that episode (same kind)
        if open_episode["status"] == E.RECONCILING:                # its attempt was lost with the process
            await episodes.inconclusive(state.holder, open_episode["episode_id"])
        spent = int(open_episode["attempts"])
        if open_episode["kind"] == K.VERIFICATION:
            # CONF-050 (D-10): check persisted layer verdicts before re-running
            verdicts = await deps.events.layer_verdicts(loaded.tenant_id, row.step_id)
            if verdicts and any(v == Verdict.FAIL for v in verdicts.values()):
                await episodes.start_attempt(state.holder, open_episode["episode_id"])
                await episodes.close(state.holder, open_episode["episode_id"], status=E.CONFIRMED_FAILURE,
                                     outcome=O.VERIFIED_FAIL, reason="verified_fail",
                                     evidence={"recovered": True, "layers": dict(verdicts)})
                checked = VerificationOutcome(Verdict.FAIL,
                    tuple(LayerResult(k, v, {}) for k, v in verdicts.items()))
                return await _verification_failed(state, step, row, rid, checked, open_episode["episode_id"])
            return await _verification_episode(
                state, step, row, binding, rid, None,
                VerificationOutcome(Verdict.UNKNOWN, ()), "verification_passed",
                episode_id=open_episode["episode_id"], tries=spent)
        return await _probe_and_settle(state, step, row, binding, rid, attempt, used, open_episode["episode_id"],
                                       max(deps.settings.probe_max_attempts - spent, 0))
    record = await deps.idempotency.lookup(loaded.tenant_id, step_idempotency_key(loaded.request_id, step.id))
    if record is not None and record.kernel_op_id != step.kernel_op_id:
        raise IdempotencyConflict(step_idempotency_key(loaded.request_id, step.id))
    if record is not None and record.kind == "success":
        if await _layers_passed(state, step, row, binding):
            await episodes.open_and_close(state.holder, step_id=row.step_id, kind=K.VERIFICATION,
                                          status=E.CONFIRMED_SUCCESS, outcome=O.LEDGER_HIT, reason="ledger_hit")
            return await _commit(state, step, row, binding, rid, "ledger_hit_success")
        return await _verification_episode(state, step, row, binding, rid, record.result,
                                           VerificationOutcome(Verdict.UNKNOWN, ()), "verification_passed")
    if record is not None:                                         # a definitive failure
        await episodes.open_and_close(state.holder, step_id=row.step_id, kind=K.EXECUTION,
                                      status=E.CONFIRMED_FAILURE, outcome=O.LEDGER_HIT, reason="ledger_hit_failure")
        return await _settle_failure(state, step, row, rid, "ledger_hit_failure")
    if row.dispatched_attempt is None or row.dispatched_attempt < row.attempt:     # C35: provably never dispatched
        await episodes.open_and_close(state.holder, step_id=row.step_id, kind=K.EXECUTION,
                                      status=E.CONFIRMED_FAILURE, outcome=O.NOT_EXECUTED, reason="not_executed",
                                      evidence={"reason": "no_dispatch_marker"})
        return await _not_executed(state, step, row, rid, attempt, used, "no_dispatch_marker")
    episode_id = await episodes.open(state.holder, step_id=row.step_id, kind=K.EXECUTION)
    return await _probe_and_settle(state, step, row, binding, rid, attempt, used, episode_id,
                                   deps.settings.probe_max_attempts)
