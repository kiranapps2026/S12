"""The attempts of one RUNNING step (gate §8 step 8, C9, C17, C35): live check, ledger, marker, guarded call."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from contracts.adapter_interface import CallMeta, ErrorClass, GuardedCall
from contracts.execution_context import ExecutionContext
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.idempotency import IdempotencyConflict, attempt_id, step_idempotency_key
from contracts.step_execution import AdapterResult
from engine.stages.s12_execute.fault_injection import NoFaults
from engine.stages.s12_execute.retry_policy import backoff_s, max_attempts

SUCCESS, FAILURE, UNCERTAIN, REVOKED = "success", "failure", "uncertain", "revoked"
HIT_EVENT = "idempotency_hit"
ATTEMPT_EVENT, CALLED_EVENT, RETURNED_EVENT = "step_attempt", "ProviderCalled", "ProviderReturned"
_NOT_INVOKED = frozenset({ErrorClass.CIRCUIT_OPEN, ErrorClass.RETRY_STORM})


@dataclass(frozen=True)
class StepAttempt:
    request_id: str
    plan_step_id: str
    step_index: int
    step_id: str
    kernel_op_id: str
    params: dict
    mutation: str
    retry_safety: str
    step_max_attempts: int | None
    reservation_id: str
    timeout_s: float
    binding: FrozenBindingIdentity
    context: ExecutionContext


@dataclass(frozen=True)
class AttemptDeps:
    guard: Any
    ledger: Any
    attempts: Any
    live: Any
    events: Any
    sleep: Callable[[float], Awaitable[object]]
    backoff_base_s: float
    ledger_ttl_s: float
    faults: Any = NoFaults()


@dataclass(frozen=True)
class AttemptOutcome:
    kind: str
    result: AdapterResult | None
    attempts: int
    cached: bool = False
    reason: str | None = None


async def run_attempts(step: StepAttempt, holder, deps: AttemptDeps, *, first_attempt: int = 1) -> AttemptOutcome:
    ctx, key = step.context, step_idempotency_key(step.request_id, step.plan_step_id)
    limit = max_attempts(step.mutation, step.retry_safety, step.step_max_attempts)
    n = first_attempt
    while True:
        revoked = await deps.live.check(tenant_id=ctx.tenant_id, workspace_id=ctx.workspace_id, user_id=ctx.user_id,
                                        connection_id=ctx.connection_id, binding=step.binding)
        if revoked is not None:
            return AttemptOutcome(REVOKED, None, n, reason=revoked.reason)
        record = await deps.ledger.lookup(ctx.tenant_id, key)
        if record is not None and record.kernel_op_id != step.kernel_op_id:
            raise IdempotencyConflict(key)              # the key's row is another operation's: never a hit
        if record is not None:
            await deps.events.record(HIT_EVENT, {"step_id": step.step_id, "attempt_id": attempt_id(step.step_index, n),
                                                 "kind": record.kind})
            return AttemptOutcome(record.kind, record.result, n, cached=True)
        dispatched = await deps.attempts.dispatched(ctx.tenant_id, step.step_id)
        if dispatched is not None and dispatched >= n:
            return AttemptOutcome(UNCERTAIN, None, n, reason="dispatched_without_record")
        await deps.attempts.mark_dispatched(holder, step.step_id, n)
        deps.faults.hit("after_dispatch_marker_before_call")
        meta = CallMeta(key, attempt_id(step.step_index, n), str(uuid.uuid4()), ctx.tenant_id)
        await deps.events.record(ATTEMPT_EVENT, {"step_id": step.step_id, "attempt_id": meta.attempt_id,
                                                 "attempt": n})
        result = await deps.guard.call(GuardedCall(step.kernel_op_id, step.params, step.binding, ctx, meta,
                                                   step.step_id, step.reservation_id, n, step.timeout_s))
        deps.faults.hit("after_adapter_call_before_ledger")
        if result.error_class not in _NOT_INVOKED:
            ids = {"step_id": step.step_id, "attempt_id": meta.attempt_id, "provider_call_id": meta.provider_call_id}
            await deps.events.record(CALLED_EVENT, {**ids, "kernel_op_id": step.kernel_op_id})
            await deps.events.record(RETURNED_EVENT, {**ids, "status": result.status})
        if result.status == "ok":
            await deps.ledger.store(holder, idempotency_key=key, kernel_op_id=step.kernel_op_id, result=result,
                                    ttl_s=deps.ledger_ttl_s)
            return AttemptOutcome(SUCCESS, result, n)
        if result.status == "timeout":
            return AttemptOutcome(UNCERTAIN, result, n, reason="timeout")
        if result.error_class in _NOT_INVOKED:
            return AttemptOutcome(FAILURE, result, n)
        if not result.retryable:
            await deps.ledger.store(holder, idempotency_key=key, kernel_op_id=step.kernel_op_id, result=result,
                                    ttl_s=deps.ledger_ttl_s)
            return AttemptOutcome(FAILURE, result, n)
        if n >= limit:
            return AttemptOutcome(FAILURE, result, n)
        await deps.sleep(backoff_s(step.mutation, n, deps.backoff_base_s))
        n += 1
