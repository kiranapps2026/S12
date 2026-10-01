"""Read a terminal run for its S15 response (gate §12): states, codes and plan positions only."""
from __future__ import annotations

import json

from adapters.postgres.database import Database
from contracts import codec
from contracts.stage_outputs import Plan
from engine.stages.s15_final_state.response import RunSummary, StepSummary


class PostgresRunSummaries:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self, tenant_id: str, execution_id: str) -> RunSummary | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            run = await c.fetchrow("SELECT status, terminal_reason, trace_id FROM execution_runs WHERE tenant_id = $1"
                                   " AND execution_id = $2", tenant_id, execution_id)
            if run is None:
                return None
            raw = await c.fetchval("SELECT canonical_plan FROM execution_plans WHERE tenant_id = $1"
                                   " AND execution_id = $2", tenant_id, execution_id)
            rows = {r["plan_step_id"]: r for r in await c.fetch(
                "SELECT plan_step_id, kernel_op_id, status, terminal_reason FROM execution_steps WHERE tenant_id = $1"
                " AND execution_id = $2", tenant_id, execution_id)}
        order = [s.id for s in codec.decode(Plan, json.loads(raw)).steps]
        steps = tuple(StepSummary(i + 1, rows[sid]["kernel_op_id"], rows[sid]["status"], rows[sid]["terminal_reason"])
                      for i, sid in enumerate(order) if sid in rows)
        return RunSummary(run["status"], run["terminal_reason"], run["trace_id"], steps)
