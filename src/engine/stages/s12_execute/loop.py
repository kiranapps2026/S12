"""S12 step loop (gate §8), one step at a time in topological order (C11).

Built here: cancellation check (C16), live authorization at step start and before every adapter call
(C23), per-step budget reserve / lock / commit / release (C3, C15), the dispatch marker (C35), the
reliability guard, retries of READ steps only, independent verification, undo tokens, dependents
(SKIPPED) and collateral cancellation, and a minimal run consolidation.

NOT built (later gate milestones; each fails CLOSED here, never silently succeeds):
  worker selection / leases / admission controller (M7, M8) - one Worker Runtime, ownership row only;
  idempotency ledger and retries of W/D steps (M11) - a failed mutation is never retried;
  probe and reconciliation (M13) - a timeout or unverifiable step goes to DEAD_LETTER, budget LOCKED;
  verification layers beyond one injected verifier (M15); dead-letter records and rollback (M17);
  pre-flight schema validation (no kernel input schema exists yet); checkpoints; S13/S15.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from contracts.plan_hash import canonical_plan_digest
from contracts.step_execution import (
    AdapterResult, FencedOut, LiveAuthorization, PASS, FAIL, StepCall, StepVerification,
)
from engine.stages.s12_execute import transitions
from engine.stages.s12_execute.guard import ReliabilityGuard

logger = logging.getLogger(__name__)

MAX_READ_ATTEMPTS = 3
READ_BACKOFF_SECONDS = 0.05


@dataclass(frozen=True)
class StepLoopDeps:
    repo: object                          # PostgresExecutionRepository
    budget: object                        # PostgresBudgetReserver
    guard: ReliabilityGuard
    live: LiveAuthorization
    verification: StepVerification | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


@dataclass(frozen=True)
class LoopResult:
    run_status: str
    terminal_reason: str | None
    steps: dict                           # plan step id -> final status
    budget_spent: int = 0


@dataclass(frozen=True)
class _Halt:
    run_status: str                       # cancelled | dead_letter
    run_reason: str
    step_reason: str                      # terminal_reason for the remaining PENDING steps


def topological_order(steps) -> list:
    """depends_on order, ties broken by plan position. Raises ValueError on a cycle or unknown id."""
    by_id = {s.id: s for s in steps}
    position = {s.id: i for i, s in enumerate(steps)}
    if len(by_id) != len(steps) or any(d not in by_id for s in steps for d in s.depends_on):
        raise ValueError("plan dependencies do not form a graph over known steps")
    remaining = {s.id: set(s.depends_on) for s in steps}
    order = []
    while remaining:
        ready = sorted((sid for sid, deps in remaining.items() if not deps), key=position.__getitem__)
        if not ready:
            raise ValueError("cycle in plan dependencies")
        sid = ready[0]
        order.append(by_id[sid])
        del remaining[sid]
        for deps in remaining.values():
            deps.discard(sid)
    return order


async def run_execution(deps: StepLoopDeps, tenant_id: str, execution_id: str) -> LoopResult:
    started = time.monotonic()
    loaded = await deps.repo.load(tenant_id, execution_id)
    if loaded is None:
        raise LookupError(f"no such execution {execution_id}")
    statuses = {sid: row.status for sid, row in loaded.steps.items()}
    if loaded.run_status != "running":                       # nothing to do (terminal, or not admitted)
        return LoopResult(loaded.run_status, None, statuses)
    try:
        return await _run(deps, loaded, statuses, started)
    except FencedOut:
        logger.warning("S12: fenced out of execution %s; stopping", execution_id)
        return LoopResult("fenced_out", None, statuses)


async def _run(deps, loaded, statuses: dict, started: float) -> LoopResult:
    tenant, execution = loaded.tenant_id, loaded.execution_id
    repo = deps.repo
    plan = loaded.plan
    try:
        order = topological_order(plan.steps)
        intact = canonical_plan_digest(plan) == loaded.plan_hash
    except (ValueError, TypeError):
        order, intact = [], False
    if not intact:                                          # gate §7.3: never execute a plan that changed
        halt = _Halt("dead_letter", "plan_integrity", "run_dead_lettered")
        await _cancel_pending(deps, loaded, statuses, halt.step_reason)
        return await _finish(deps, loaded, statuses, halt, started)

    halt: _Halt | None = None
    for step in order:
        if statuses[step.id] != "pending":
            continue
        halt = await _run_step(deps, loaded, statuses, step)
        if halt is not None:
            break
    if halt is not None:
        await _cancel_pending(deps, loaded, statuses, halt.step_reason)
    return await _finish(deps, loaded, statuses, halt, started)


async def _set(deps, loaded, statuses, step, to, *, reason, **fields) -> None:
    transitions.check_step(statuses[step.id], to)
    await deps.repo.transition_step(loaded.tenant_id, loaded.execution_id, loaded.steps[step.id].step_id, to,
                                    reason=reason, **fields)
    statuses[step.id] = to


async def _cancel_pending(deps, loaded, statuses, reason: str) -> None:
    """Remaining PENDING steps become CANCELLED with the trigger's reason (C22)."""
    for sid, status in list(statuses.items()):
        if status == "pending":
            await deps.repo.transition_step(loaded.tenant_id, loaded.execution_id, loaded.steps[sid].step_id,
                                            "cancelled", reason="collateral", terminal_reason=reason)
            statuses[sid] = "cancelled"


async def _skip_dependents(deps, loaded, statuses, failed_id: str) -> None:
    """Transitive dependents of a step that ended FAILED or CANCELLED become SKIPPED (§8 step 12)."""
    blocked = {failed_id}
    for step in topological_order(loaded.plan.steps):
        if blocked & set(step.depends_on):
            blocked.add(step.id)
            if statuses[step.id] == "pending":
                await deps.repo.transition_step(loaded.tenant_id, loaded.execution_id,
                                                loaded.steps[step.id].step_id, "skipped",
                                                reason="dependency_failed", terminal_reason="dependency_failed")
                statuses[step.id] = "skipped"


async def _live(deps, loaded, binding):
    return await deps.live.check(tenant_id=loaded.tenant_id, workspace_id=loaded.workspace_id,
                                 user_id=loaded.user_id, connection_id=loaded.connection_id, binding=binding)


async def _release(deps, loaded, reservation_id: str | None) -> None:
    if reservation_id is not None:
        await deps.budget.release(loaded.tenant_id, reservation_id)


async def _run_step(deps, loaded, statuses, step) -> _Halt | None:
    tenant, execution = loaded.tenant_id, loaded.execution_id
    binding = loaded.bindings[step.id]
    step_id = loaded.steps[step.id].step_id

    # cancellation request (C16): checked before each step; an in-flight call is never interrupted
    if await deps.repo.cancel_requested(tenant, execution):
        await _set(deps, loaded, statuses, step, "cancelled", reason="cancel_requested",
                   terminal_reason="user_cancelled")
        return _Halt("cancelled", "user_cancelled", "user_cancelled")

    # live authorization at the start of every step (C23)
    revoked = await _live(deps, loaded, binding)
    if revoked is not None:
        await _set(deps, loaded, statuses, step, "cancelled", reason=revoked.reason,
                   terminal_reason=revoked.reason)
        return _Halt("cancelled", revoked.reason, revoked.reason)

    # reserve budget (C3): exhausted -> this step and every remaining one is CANCELLED (C15)
    reservation = await deps.budget.reserve(tenant_id=tenant, user_id=loaded.user_id, execution_id=execution,
                                            step_id=step_id, cost=step.cost)
    if reservation.reservation_id is None:
        await _set(deps, loaded, statuses, step, "cancelled", reason="budget_exhausted",
                   terminal_reason="budget_exhausted")
        return _Halt("cancelled", "budget_exhausted", "budget_exhausted")
    rid = reservation.reservation_id

    # PENDING -> RUNNING, budget RESERVED -> LOCKED
    await _set(deps, loaded, statuses, step, "running", reason="step_started")
    await deps.budget.lock(tenant, rid)

    verifier = loaded.verifiers.get(step.id)
    attempt = 1
    while True:
        # immediately before EVERY adapter call (C23)
        revoked = await _live(deps, loaded, binding)
        if revoked is not None:
            await _set(deps, loaded, statuses, step, "cancelled", reason=revoked.reason,
                       terminal_reason=revoked.reason)
            await _release(deps, loaded, rid)
            return _Halt("cancelled", revoked.reason, revoked.reason)
        await deps.repo.mark_dispatched(tenant, execution, step_id, attempt)
        began = time.monotonic()
        result = await deps.guard.execute(
            StepCall(tenant, execution, step, binding, verifier, attempt),
            reservation_status=await deps.budget.status(tenant, rid))
        if (result.status == "error" and result.retryable and step.mutation == "R"
                and attempt < MAX_READ_ATTEMPTS):
            attempt += 1
            await deps.sleep(READ_BACKOFF_SECONDS * attempt)
            continue
        break
    elapsed_ms = int((time.monotonic() - began) * 1000)

    if result.status == "timeout":
        # probe (M13) is not built: never guess. The budget stays LOCKED (D4).
        await _set(deps, loaded, statuses, step, "timeout", reason="timeout")
        await _set(deps, loaded, statuses, step, "pending_probe", reason="timeout_probe_queued")
        await _set(deps, loaded, statuses, step, "dead_letter", reason="probe_unavailable",
                   error="timeout", attempt=attempt)
        return _Halt("dead_letter", "unknown_unresolved", "run_dead_lettered")

    if result.status != "ok":
        # definitive failure (a mutation is never retried without the idempotency ledger)
        await _set(deps, loaded, statuses, step, "failed", reason="adapter_error", error=result.error_class,
                   attempt=attempt, duration_ms=elapsed_ms)
        await _release(deps, loaded, rid)
        await _skip_dependents(deps, loaded, statuses, step.id)
        return None

    # independent verification (never the adapter's own claim); reads are self-verifying
    if step.mutation != "R" or verifier is not None:
        verdict = await _verify(deps, verifier, result)
        if verdict == FAIL:
            await _set(deps, loaded, statuses, step, "failed", reason="verification_failed",
                       error="verification_failed", attempt=attempt, duration_ms=elapsed_ms)
            await _release(deps, loaded, rid)
            await _skip_dependents(deps, loaded, statuses, step.id)
            return None
        if verdict != PASS:
            await _set(deps, loaded, statuses, step, "pending_probe", reason="verification_unknown")
            await _set(deps, loaded, statuses, step, "dead_letter", reason="verification_unresolved",
                       error="verification_unknown", attempt=attempt)
            return _Halt("dead_letter", "unknown_unresolved", "run_dead_lettered")

    undo = None
    if step.inverse and step.mutation in ("W", "D"):
        undo = json.dumps({"inverse_kernel_op_id": step.inverse, "step_id": step_id}, sort_keys=True)
    await _set(deps, loaded, statuses, step, "completed", reason="step_completed", attempt=attempt,
               undo_token=undo, duration_ms=elapsed_ms, data=result.data or None)
    await deps.budget.commit(tenant, rid)
    return None


async def _verify(deps, verifier, result: AdapterResult) -> str:
    if verifier is None or deps.verification is None:
        return "UNKNOWN"                                    # a mutation nobody can verify is not a success
    try:
        verdict = await deps.verification.verify(verifier, result)
    except Exception:  # noqa: BLE001 — fail closed
        logger.exception("verification raised")
        return "UNKNOWN"
    return verdict if verdict in (PASS, FAIL) else "UNKNOWN"


async def _finish(deps, loaded, statuses, halt: _Halt | None, started: float) -> LoopResult:
    """Minimal consolidation (the full S13 rules are a later milestone): the run's terminal state."""
    completed = [s for s in loaded.plan.steps if statuses[s.id] == "completed"]
    spent = sum(s.cost for s in completed)
    if halt is not None:
        status, reason = halt.run_status, halt.run_reason
    elif len(completed) == len(loaded.plan.steps):
        status, reason = "completed", None
    elif completed:
        status, reason = "partial", "step_failed"
    else:
        status, reason = "failed", "step_failed"
    await deps.repo.transition_run(loaded.tenant_id, loaded.execution_id, status, reason=reason or "consolidated",
                                   terminal_reason=reason, budget_spent=spent,
                                   duration_ms=int((time.monotonic() - started) * 1000))
    return LoopResult(status, reason, dict(statuses), spent)
