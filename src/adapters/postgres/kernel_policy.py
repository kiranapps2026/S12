"""PostgreSQL-backed kernel operation policy lookup (M12, gate C9).

Reads ``kernel_ops.retry_safety`` for a given ``kernel_op_id``. Unknown operations
return ``"never"`` so the loop never retries an unregistered operation.
"""
from __future__ import annotations

import asyncpg

from adapters.postgres.database import Database


class PostgresKernelPolicy:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def retry_safety(self, kernel_op_id: str) -> str:
        """The retry safety profile for this operation, or "never" when not registered."""
        sql = "SELECT retry_safety FROM kernel_ops WHERE kernel_op_id = $1"
        async with self._db.transaction() as c:
            row = await c.fetchrow(sql, kernel_op_id)
        if row is None:
            return "never"
        return row["retry_safety"]
