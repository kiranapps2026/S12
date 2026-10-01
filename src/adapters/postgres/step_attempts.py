"""PostgreSQL-backed step-attempt marker (gate C35, MUTATION_SAFETY §4).

Writes ``execution_steps.dispatched_attempt`` so a restarted runtime can tell which
attempt already reached the provider, even when the idempotency ledger row is missing.
"""
from __future__ import annotations

import asyncpg

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, check_fence
from contracts.idempotency import attempt_id


class PostgresStepAttempts:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def dispatched(self, tenant_id: str, step_id: str) -> int | None:
        """The highest dispatched attempt for this step, or None."""
        sql = """
            SELECT dispatched_attempt FROM execution_steps
             WHERE tenant_id = $1 AND step_id = $2 AND dispatched_attempt IS NOT NULL"""
        async with self._db.tenant_transaction(tenant_id) as connection:
            return await connection.fetchval(sql, tenant_id, step_id)

    async def mark_dispatched(self, holder: FenceHolder, step_id: str, attempt: int) -> None:
        """Set ``dispatched_attempt = attempt`` inside a fenced write (no state transition)."""
        async with self._db.tenant_transaction(holder.tenant_id) as connection:
            await check_fence(connection, holder)
            await connection.execute(
                "UPDATE execution_steps SET dispatched_attempt = $1, attempt = $1 WHERE tenant_id = $2 AND step_id = $3",
                attempt, holder.tenant_id, step_id)
