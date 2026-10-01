"""Kernel operation policy read by the S12 loop: retry safety (MUTATION_SAFETY §3). Unknown operations never retry."""
from __future__ import annotations

from adapters.postgres.database import Database

NEVER = "never"


class PostgresKernelPolicy:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def retry_safety(self, kernel_op_id: str) -> str:
        async with self._db.transaction() as c:
            value = await c.fetchval("SELECT retry_safety FROM kernel_ops WHERE kernel_op_id = $1", kernel_op_id)
        return value or NEVER
