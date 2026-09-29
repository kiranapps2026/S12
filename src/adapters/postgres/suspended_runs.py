"""Suspended runs (``suspended_runs``): the state as S10 left it, as JSON, tenant-scoped (RLS)."""
from __future__ import annotations

import json

from adapters.postgres.database import Database
from contracts.codec import decode_state, encode_state
from contracts.pipeline_state import PipelineState


class PostgresSuspendedRunStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, state: PipelineState, *, tenant_id: str, execution_id: str,
                   confirmation_id: str) -> None:
        if not tenant_id or not execution_id or not confirmation_id:
            raise ValueError("tenant_id, execution_id and confirmation_id are required")
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "INSERT INTO suspended_runs (confirmation_id, tenant_id, execution_id, state)"
                " VALUES ($1, $2, $3, $4::jsonb)",
                confirmation_id, tenant_id, execution_id, json.dumps(encode_state(state)))

    async def load(self, *, tenant_id: str, confirmation_id: str) -> PipelineState | None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchval(
                "SELECT state::text FROM suspended_runs WHERE confirmation_id = $1", confirmation_id)
        return None if row is None else decode_state(json.loads(row))
