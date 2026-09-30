"""The probe path of an EXECUTION episode (gate §9, C12, C18): called from the S12 loop."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from contracts.adapter_interface import CallMeta, GuardedCall, ProbeOutcome
from contracts.idempotency import IdempotencyConflict, attempt_id, step_idempotency_key
from contracts.metrics import PROBE
from contracts.step_execution import AdapterResult
from engine.stages.s12_execute.fault_injection import NoFaults

LEDGER_SUCCESS, LEDGER_FAILURE = "ledger_success", "ledger_failure"
EXECUTED_SUCCESS, EXECUTED_FAILURE = "executed_success", "executed_failure"
NOT_EXECUTED, EXHAUSTED = "not_executed", "exhausted"
CLOSED_EVENT = "episode_closed"


@dataclass(frozen=True)
class Determination:
    kind: str
    result: AdapterResult | None = None


async def resolve_execution(*, step, holder, episode_id: str, attempt: int, guard, ledger, episodes, events, sleep,
                            max_attempts: int, backoff_s: float, faults=None, metrics=None) -> Determination:
    """Probe attempts until a determination; the episode is left RECONCILING for the caller to close, or EXHAUSTED."""
    key = step_idempotency_key(step.request_id, step.plan_step_id)
    for n in range(1, max_attempts + 1):
        await episodes.start_attempt(holder, episode_id)
        (faults or NoFaults()).hit("during_probe")
        record = await ledger.lookup(step.context.tenant_id, key)
        if record is not None and record.kernel_op_id != step.kernel_op_id:
            raise IdempotencyConflict(key)              # another operation's row: an invariant violation, no guess
        if record is not None:
            return Determination(LEDGER_SUCCESS if record.kind == "success" else LEDGER_FAILURE, record.result)
        meta = CallMeta(key, attempt_id(step.step_index, attempt), str(uuid.uuid4()), step.context.tenant_id)
        call = GuardedCall(step.kernel_op_id, step.params, step.binding, step.context, meta, step.step_id,
                           step.reservation_id, attempt, step.timeout_s)
        if metrics is not None:
            metrics.increment(PROBE)
        outcome = await guard.probe(call)
        if outcome == ProbeOutcome.EXECUTED_SUCCESS:
            return Determination(EXECUTED_SUCCESS)
        if outcome == ProbeOutcome.EXECUTED_FAILURE:
            return Determination(EXECUTED_FAILURE)
        if outcome == ProbeOutcome.NOT_EXECUTED:
            return Determination(NOT_EXECUTED)
        await episodes.inconclusive(holder, episode_id)
        if n < max_attempts:
            await sleep(backoff_s * n)
    await episodes.exhaust(holder, episode_id)
    await events.record(CLOSED_EVENT, {"step_id": step.step_id, "episode_id": episode_id, "outcome": "EXHAUSTED"})
    return Determination(EXHAUSTED)
