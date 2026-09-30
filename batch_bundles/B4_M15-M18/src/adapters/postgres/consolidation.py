"""The S13 consolidation transaction (gate §10, C8, C13, C39 refund; invariants I2, I3, I13; ruling CONF-037).

Every way a run becomes terminal after admission goes through here, in ONE fenced transaction:
``consolidate`` (the §10 table) and ``cancel`` (C15, C16, C23: CANCELLED with the trigger's reason). Both first require
every step terminal (the loop settles steps first; a run never ends with a live step, I3), release any reservation
still RESERVED (no RESERVED reservation survives a terminal run, I2; LOCKED stays only under D4), emit the ledger
events VERIFICATION_STARTED (the layers each step required) and VERIFICATION_COMPLETED (the layer results persisted
for each step), and move the run by the legal matrix. ``cancel`` also refunds the run's quota use when no step
COMPLETED (C39), with a ``quota_refunded`` event. A second call on a terminal run is refused by the matrix and writes
nothing, so a refund can never happen twice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import asyncpg

from adapters.postgres.budget_reserver import MACHINE as BUDGET_MACHINE
from adapters.postgres.database import Database
from adapters.postgres.execution_events import insert_event
from adapters.postgres.fencing import FenceHolder, fenced_write
from adapters.postgres.transition_log import log_transition
from contracts.execution_states import ExecutionStatus as R
from contracts.execution_states import ReservationState as B
from contracts.execution_states import StepState as S
from engine.stages.s12_execute import transitions
from engine.stages.s13_reconciliation.consolidation import Outcome, consolidation_outcome
from engine.stages.s13_reconciliation.verification import required_verification_layers

STARTED, COMPLETED = "VERIFICATION_STARTED", "VERIFICATION_COMPLETED"
LAYER_EVENT = "verification_layer"
REFUND_EVENT = "quota_refunded"
CONSOLIDATED = "consolidated"

_RUN = "SELECT status, trace_id, workspace_id, created_at FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2" \
       " FOR UPDATE"
_STEPS = ("SELECT step_id, plan_step_id, status, terminal_reason, effective_mutation, effective_risk FROM"
          " execution_steps WHERE tenant_id = $1 AND execution_id = $2 ORDER BY plan_step_id FOR UPDATE")
_RESERVED = ("SELECT reservation_id FROM budget_reservations WHERE tenant_id = $1 AND execution_id = $2 AND status = $3"
             " FOR UPDATE")
_LAYERS = ("SELECT step_id, payload FROM execution_events WHERE tenant_id = $1 AND execution_id = $2"
           " AND event_type = $3 ORDER BY seq")
_REFUND = ("UPDATE operation_quotas SET used_count = used_count - 1 WHERE tenant_id = $1 AND resource_type = 'executions'"
           " AND (workspace_id IS NULL OR workspace_id = $2) AND period_start <= $3 AND period_end > $3"
           " AND used_count > 0 RETURNING quota_id")


@dataclass(frozen=True)
class ConsolidationResult:
    run_status: str
    outcome: str | None
    refunded: tuple[str, ...] = ()


class PostgresConsolidator:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def __call__(self, holder: FenceHolder, tenant_id: str, execution_id: str) -> ConsolidationResult:
        return await self.consolidate(holder, tenant_id, execution_id)

    async def consolidate(self, holder: FenceHolder, tenant_id: str, execution_id: str) -> ConsolidationResult:
        async def write(c):
            run, steps = await self._prepare(c, holder)
            status, outcome = consolidation_outcome((s["status"], s["terminal_reason"]) for s in steps)
            await self._finish(c, holder, run, steps, status, CONSOLIDATED, None, outcome)
            return ConsolidationResult(status, outcome)
        self._same(holder, tenant_id, execution_id)
        return await fenced_write(self._db, holder, write)

    async def cancel(self, holder: FenceHolder, tenant_id: str, execution_id: str, *, reason: str) -> ConsolidationResult:
        async def write(c):
            run, steps = await self._prepare(c, holder)
            consolidation_outcome((s["status"], s["terminal_reason"]) for s in steps)     # every step terminal
            await self._finish(c, holder, run, steps, R.CANCELLED, reason, reason, None)
            refunded: tuple[str, ...] = ()
            if not any(s["status"] == S.COMPLETED for s in steps):
                refunded = tuple(r["quota_id"] for r in await c.fetch(_REFUND, holder.tenant_id, run["workspace_id"],
                                                                        run["created_at"]))
                if refunded:
                    await self._event(c, holder, run, REFUND_EVENT, {"quota_ids": list(refunded)})
            return ConsolidationResult(R.CANCELLED, None, refunded)
        self._same(holder, tenant_id, execution_id)
        return await fenced_write(self._db, holder, write)

    @staticmethod
    def _same(holder: FenceHolder, tenant_id: str, execution_id: str) -> None:
        if (holder.tenant_id, holder.execution_id) != (tenant_id, execution_id):
            raise ValueError("the fence holder belongs to another execution")

    async def _prepare(self, c: asyncpg.Connection, holder: FenceHolder):
        run = await c.fetchrow(_RUN, holder.tenant_id, holder.execution_id)
        if run is None:
            raise LookupError(f"no execution {holder.execution_id}")
        if run["status"] not in (R.RUNNING, R.RECONCILING):
            raise ValueError(f"execution {holder.execution_id} is {run['status']}: nothing to consolidate")
        return run, await c.fetch(_STEPS, holder.tenant_id, holder.execution_id)

    async def _event(self, c, holder, run, kind, payload) -> None:
        await insert_event(c, tenant_id=holder.tenant_id, execution_id=holder.execution_id, trace_id=run["trace_id"],
                           kind=kind, payload=payload, runtime_instance_id=holder.runtime_instance_id,
                           fence_token=holder.fence_token)

    async def _finish(self, c, holder, run, steps, to, reason, terminal_reason, outcome) -> None:
        release_reason = "run_cancelled" if to == R.CANCELLED else "budget_released_before_start"
        for r in await c.fetch(_RESERVED, holder.tenant_id, holder.execution_id, B.RESERVED):
            transitions.validate(BUDGET_MACHINE, B.RESERVED, B.RELEASED, reason=release_reason)
            await c.execute("UPDATE budget_reservations SET status = $3, released_at = now() WHERE tenant_id = $1"
                            " AND reservation_id = $2", holder.tenant_id, r["reservation_id"], B.RELEASED)
            await log_transition(c, tenant_id=holder.tenant_id, machine=BUDGET_MACHINE, entity_id=r["reservation_id"],
                                 from_state=B.RESERVED, to_state=B.RELEASED, reason=release_reason,
                                 runtime_instance_id=holder.runtime_instance_id, fence_token=holder.fence_token,
                                 execution_id=holder.execution_id)
        by_id = {s["step_id"]: s["plan_step_id"] for s in steps}
        results: dict[str, dict[str, str]] = {s["plan_step_id"]: {} for s in steps}
        for e in await c.fetch(_LAYERS, holder.tenant_id, holder.execution_id, LAYER_EVENT):
            body = json.loads(e["payload"]) if isinstance(e["payload"], str) else e["payload"]
            if e["step_id"] in by_id:
                results[by_id[e["step_id"]]][body["layer"]] = body["verdict"]      # the latest verdict per layer
        await self._event(c, holder, run, STARTED, {"steps": {
            s["plan_step_id"]: list(required_verification_layers(s["effective_mutation"], s["effective_risk"]))
            for s in steps}})
        await self._event(c, holder, run, COMPLETED, {"steps": {
            sid: [{"layer": k, "verdict": v} for k, v in layers.items()] for sid, layers in results.items()}})
        transitions.validate("run", run["status"], to, reason=reason)
        await c.execute("UPDATE execution_runs SET status = $3, terminal_reason = $4, consolidation = $5,"
                        " completed_at = now() WHERE tenant_id = $1 AND execution_id = $2", holder.tenant_id,
                        holder.execution_id, to, terminal_reason, None if outcome is None else str(outcome))
        await log_transition(c, tenant_id=holder.tenant_id, machine="run", entity_id=holder.execution_id,
                             from_state=run["status"], to_state=to, reason=reason,
                             runtime_instance_id=holder.runtime_instance_id, fence_token=holder.fence_token,
                             execution_id=holder.execution_id)


__all__ = ["ConsolidationResult", "Outcome", "PostgresConsolidator"]
