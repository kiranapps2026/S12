"""Explicit rollback of a terminal run (gate D2, C27). Nothing calls it automatically.

For each COMPLETED W/D step with an ``undo_token``, latest plan position first: never an IRREVERSIBLE step (by plan or
by row); first confirm the original operation executed (``confirm_executed``); then run the inverse operation through
the full reliability guard with key ``f"{request_id}:{plan_step_id}:inverse"`` (no reservation: the guard's budget layer
is ``InverseBudget``, ruling CONF-038). A failed inverse becomes a dead letter with ``origin = rollback`` and
``retry_mode = NONE``. Rollback never changes a run, step or reservation state; every decision is a ledger event
(``rollback_step``), and a step already compensated is not compensated again.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from adapters.postgres.execution_events import insert_event
from contracts import codec
from contracts.adapter_interface import CallMeta, GuardedCall
from contracts.execution_context import ExecutionContext
from contracts.execution_states import DeadLetterErrorType as ErrorType
from contracts.execution_states import StepState as S
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.stage_outputs import Plan
from engine.stages.s12_execute import transitions

EVENT = "rollback_step"
COMPENSATED, SKIPPED, FAILED = "compensated", "not_confirmed", "inverse_failed"
_COMPENSABLE = frozenset({"W", "D"})


@dataclass(frozen=True)
class RollbackStep:
    plan_step_id: str
    step_id: str
    position: int
    kernel_op_id: str
    inverse_kernel_op_id: str
    mutation: str
    params: dict
    timeout_s: float
    binding: FrozenBindingIdentity


@dataclass(frozen=True)
class RollbackReport:
    compensated: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]


async def _load(database, tenant_id: str, execution_id: str):
    async with database.tenant_transaction(tenant_id) as c:
        run = await c.fetchrow("SELECT * FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2",
                               tenant_id, execution_id)
        if run is None:
            raise LookupError(f"no execution {execution_id}")
        plan_row = await c.fetchrow("SELECT canonical_plan, frozen_bindings, step_binding_index FROM execution_plans"
                                    " WHERE tenant_id = $1 AND execution_id = $2", tenant_id, execution_id)
        rows = await c.fetch("SELECT step_id, plan_step_id, status, effective_mutation, undo_token FROM"
                             " execution_steps WHERE tenant_id = $1 AND execution_id = $2", tenant_id, execution_id)
        done = {r["step_id"] for r in await c.fetch(
            "SELECT step_id FROM execution_events WHERE tenant_id = $1 AND execution_id = $2 AND event_type = $3"
            " AND payload->>'result' = $4", tenant_id, execution_id, EVENT, COMPENSATED)}
    plan = codec.decode(Plan, json.loads(plan_row["canonical_plan"]))
    bindings = codec.decode(tuple[FrozenBindingIdentity, ...], json.loads(plan_row["frozen_bindings"]))
    index = json.loads(plan_row["step_binding_index"])
    return run, plan, bindings, index, {r["plan_step_id"]: r for r in rows}, done


def _candidates(plan, bindings, index, rows) -> list[RollbackStep]:
    out = []
    for position, step in enumerate(plan.steps):
        row = rows.get(step.id)
        if row is None or row["status"] != S.COMPLETED or not row["undo_token"]:
            continue
        if step.mutation not in _COMPENSABLE or row["effective_mutation"] not in _COMPENSABLE:
            continue                                   # never compensate IRREVERSIBLE (D2)
        token = json.loads(row["undo_token"])
        out.append(RollbackStep(step.id, row["step_id"], position, step.kernel_op_id, token["inverse_kernel_op_id"],
                                step.mutation, dict(step.params), float(step.timeout), bindings[index[step.id]]))
    return sorted(out, key=lambda s: s.position, reverse=True)


async def rollback_execution(tenant_id: str, execution_id: str, *, database, guard, dead_letters,
                             confirm_executed: Callable[[RollbackStep], Awaitable[bool]]) -> RollbackReport:
    run, plan, bindings, index, rows, done = await _load(database, tenant_id, execution_id)
    if run["status"] in transitions.RUN:
        raise ValueError(f"execution {execution_id} is not terminal: rollback applies only to a finished run")
    context = ExecutionContext(trace_id=run["trace_id"], request_id=run["request_id"], tenant_id=tenant_id,
                               workspace_id=run["workspace_id"], user_id=run["user_id"],
                               connection_id=run["connection_id"])
    compensated, skipped, failed = [], [], []

    async def record(step: RollbackStep, result: str, **extra) -> None:
        async with database.tenant_transaction(tenant_id) as c:
            await insert_event(c, tenant_id=tenant_id, execution_id=execution_id, trace_id=run["trace_id"],
                               kind=EVENT, payload={"step_id": step.step_id, "result": result, **extra})

    for step in _candidates(plan, bindings, index, rows):
        if step.step_id in done:
            continue                                   # compensated by an earlier rollback
        if not await confirm_executed(step):
            skipped.append(step.plan_step_id)
            await record(step, SKIPPED)
            continue
        key = f"{run['request_id']}:{step.plan_step_id}:inverse"
        meta = CallMeta(key, f"inv-{step.position}-1", str(uuid.uuid4()), tenant_id)
        result = await guard.call(GuardedCall(step.inverse_kernel_op_id, step.params, step.binding, context, meta,
                                              step.step_id, None, 1, step.timeout_s))
        if result.status == "ok":
            compensated.append(step.plan_step_id)
            await record(step, COMPENSATED, inverse_kernel_op_id=step.inverse_kernel_op_id)
            continue
        failed.append(step.plan_step_id)
        await dead_letters.create_rollback(
            tenant_id, execution_id=execution_id, step_id=step.step_id, kernel_op_id=step.inverse_kernel_op_id,
            error_type=ErrorType.TRANSIENT if result.retryable else ErrorType.PERMANENT, error="inverse_failed",
            evidence={"inverse_kernel_op_id": step.inverse_kernel_op_id, "status": result.status,
                      "error_class": str(result.error_class) if result.error_class else None, "attempts": 1},
            mutation=step.mutation)
        await record(step, FAILED, error_class=str(result.error_class) if result.error_class else None)
    return RollbackReport(tuple(compensated), tuple(skipped), tuple(failed))
