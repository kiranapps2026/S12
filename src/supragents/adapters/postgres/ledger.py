"""Stage events written to ``pipeline_events`` — the S0–S11 execution ledger."""
from __future__ import annotations

from supragents.adapters.postgres.database import Database
from supragents.contracts.events import StageEvent


class PostgresEventSink:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def emit(self, event: StageEvent) -> None:
        async with self._db.tenant_transaction(event.tenant_id) as connection:
            await connection.execute("""
                INSERT INTO pipeline_events
                    (tenant_id, trace_id, request_id, stage, status, reason, duration_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                event.tenant_id, event.trace_id, event.request_id, event.stage,
                event.status.value, event.reason, event.duration_ms)
