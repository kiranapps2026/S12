"""Durable pending confirmations (PIPELINE_STAGES §12, ruling R-Z).

Expiry is decided by the database clock; consume is a single atomic UPDATE that succeeds
only from ``pending`` for the same tenant, user and plan hash, so a confirmation can be
used exactly once. ``now`` is accepted for protocol compatibility and ignored.
"""
from __future__ import annotations

import json

from adapters.postgres.database import Database
from contracts.execution_manifest import Confirmation
from engine.stages.s10_confirmation.store import CONSUMED, EXPIRED, MISMATCH


class PostgresConfirmationStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, confirmation: Confirmation, tenant_id: str, execution_id: str) -> None:
        if not tenant_id or not execution_id:
            raise ValueError("tenant_id and execution_id are required")
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute("""
                INSERT INTO pending_confirmations (confirmation_id, tenant_id, execution_id, user_id,
                    conversation_id, plan_id, plan_hash, operations, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, to_timestamp($9))""",
                confirmation.confirmation_id, tenant_id, execution_id, confirmation.user_id,
                confirmation.conversation_id, confirmation.plan_id, confirmation.plan_hash,
                json.dumps(list(confirmation.operations)), confirmation.expires_at)

    async def consume(self, confirmation_id: str, *, tenant_id: str, user_id: str,
                      plan_hash: str, now: float | None = None) -> str:
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute("""
                UPDATE pending_confirmations SET status = 'expired'
                 WHERE confirmation_id = $1 AND status = 'pending' AND expires_at <= now()
                   AND user_id = $2 AND plan_hash = $3""", confirmation_id, user_id, plan_hash)
            done = await connection.execute("""
                UPDATE pending_confirmations SET status = 'consumed', consumed_at = now()
                 WHERE confirmation_id = $1 AND user_id = $2 AND plan_hash = $3
                   AND status = 'pending' AND expires_at > now()""",
                confirmation_id, user_id, plan_hash)
            if done == "UPDATE 1":
                return CONSUMED
            expired = await connection.fetchval("""
                SELECT status = 'expired' FROM pending_confirmations
                 WHERE confirmation_id = $1 AND user_id = $2 AND plan_hash = $3""",
                confirmation_id, user_id, plan_hash)
        return EXPIRED if expired else MISMATCH

    async def reject(self, confirmation_id: str, *, tenant_id: str, user_id: str) -> bool:
        async with self._db.tenant_transaction(tenant_id) as connection:
            done = await connection.execute("""
                UPDATE pending_confirmations SET status = 'rejected'
                 WHERE confirmation_id = $1 AND user_id = $2 AND status = 'pending'""",
                confirmation_id, user_id)
        return done == "UPDATE 1"
