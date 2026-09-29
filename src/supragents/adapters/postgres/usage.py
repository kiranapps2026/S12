"""LLM usage records (``llm_usage``), tenant-scoped under row-level security."""
from __future__ import annotations

from supragents.adapters.postgres.database import Database
from supragents.ports.usage import UsageRecord


class PostgresUsageRecorder:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def record(self, usage: UsageRecord) -> None:
        async with self._db.tenant_transaction(usage.tenant_id) as connection:
            await connection.execute("""
                INSERT INTO llm_usage (tenant_id, user_id, trace_id, resource_type, quantity, unit,
                                       kernel_op_ref, model)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                usage.tenant_id, usage.user_id, usage.trace_id, usage.resource_type,
                usage.quantity, usage.unit, usage.kernel_op_ref, usage.model)
