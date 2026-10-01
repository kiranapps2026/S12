"""Attempt counter and dispatch marker of a step (gate C35): no state transition, one fenced write."""
from __future__ import annotations

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, fenced_write

_DISPATCHED = "SELECT dispatched_attempt FROM execution_steps WHERE tenant_id = $1 AND step_id = $2"
_MARK = ("UPDATE execution_steps SET attempt = $4, dispatched_attempt = $4 WHERE tenant_id = $1 AND step_id = $2"
         " AND execution_id = $3")


class PostgresStepAttempts:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def dispatched(self, tenant_id: str, step_id: str) -> int | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            return await c.fetchval(_DISPATCHED, tenant_id, step_id)

    async def mark_dispatched(self, holder: FenceHolder, step_id: str, attempt: int) -> None:
        async def write(c):
            if await c.execute(_MARK, holder.tenant_id, step_id, holder.execution_id, attempt) != "UPDATE 1":
                raise LookupError(f"step {step_id} is not a step of execution {holder.execution_id}")
        await fenced_write(self._db, holder, write)
