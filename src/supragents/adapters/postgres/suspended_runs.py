"""Suspended runs (``suspended_runs``): the pre-S10 PipelineState as JSON, tenant-scoped."""
from __future__ import annotations

import json

from supragents.adapters.postgres.database import Database
from supragents.contracts.codec import decode, encode
from supragents.contracts.state import PipelineState


class PostgresSuspendedRunStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, state: PipelineState, *, tenant_id: str, execution_id: str,
                   confirmation_id: str) -> None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "INSERT INTO suspended_runs (confirmation_id, tenant_id, execution_id, state)"
                " VALUES ($1, $2, $3, $4::jsonb)",
                confirmation_id, tenant_id, execution_id, json.dumps(encode(state)))

    async def load(self, *, tenant_id: str, confirmation_id: str) -> PipelineState | None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchval(
                "SELECT state::text FROM suspended_runs WHERE confirmation_id = $1", confirmation_id)
        return None if row is None else decode(PipelineState, json.loads(row))
