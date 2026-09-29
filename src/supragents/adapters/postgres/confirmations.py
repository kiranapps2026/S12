"""Durable pending confirmations (PIPELINE_STAGES §12, ruling R-Z).

Expiry is decided by the database clock; consume and reject are single atomic UPDATEs
that succeed only from ``pending``, so a confirmation can be used exactly once.
"""
from __future__ import annotations

import json

from supragents.adapters.postgres.database import Database
from supragents.contracts.frozen_json import freeze, thaw
from supragents.contracts.outputs import Confirmation
from supragents.contracts.vocabulary import ConfirmationStatus
from supragents.ports.confirmations import StoredConfirmation

_SELECT = """
SELECT confirmation_id, tenant_id, execution_id, user_id, conversation_id, plan_id, plan_hash,
       operations::text AS operations, status,
       EXTRACT(EPOCH FROM expires_at)::float8 AS expires_at,
       EXTRACT(EPOCH FROM consumed_at)::float8 AS consumed_at
  FROM pending_confirmations
"""


class PostgresConfirmationStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(self, confirmation: Confirmation, *, tenant_id: str, execution_id: str) -> None:
        if not tenant_id or not execution_id:
            raise ValueError("tenant_id and execution_id are required")
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute("""
                INSERT INTO pending_confirmations (confirmation_id, tenant_id, execution_id, user_id,
                    conversation_id, plan_id, plan_hash, operations, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, to_timestamp($9))""",
                confirmation.confirmation_id, tenant_id, execution_id, confirmation.user_id,
                confirmation.conversation_id, confirmation.plan_id, confirmation.plan_hash,
                json.dumps(thaw(confirmation.operations)), confirmation.expires_at)

    async def find(self, *, tenant_id: str, execution_id: str) -> StoredConfirmation | None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(_SELECT + " WHERE execution_id = $1", execution_id)
        return None if row is None else _stored(row)

    async def consume(self, confirmation_id: str, *, tenant_id: str, user_id: str, plan_hash: str) -> bool:
        async with self._db.tenant_transaction(tenant_id) as connection:
            await _expire(connection, confirmation_id)
            status = await connection.execute("""
                UPDATE pending_confirmations SET status = 'consumed', consumed_at = now()
                 WHERE confirmation_id = $1 AND user_id = $2 AND plan_hash = $3
                   AND status = 'pending' AND expires_at > now()""", confirmation_id, user_id, plan_hash)
        return status == "UPDATE 1"

    async def reject(self, confirmation_id: str, *, tenant_id: str, user_id: str) -> bool:
        async with self._db.tenant_transaction(tenant_id) as connection:
            status = await connection.execute("""
                UPDATE pending_confirmations SET status = 'rejected'
                 WHERE confirmation_id = $1 AND user_id = $2 AND status = 'pending'""",
                confirmation_id, user_id)
        return status == "UPDATE 1"


async def _expire(connection, confirmation_id: str) -> None:
    await connection.execute("""
        UPDATE pending_confirmations SET status = 'expired'
         WHERE confirmation_id = $1 AND status = 'pending' AND expires_at <= now()""", confirmation_id)


def _stored(row) -> StoredConfirmation:
    confirmation = Confirmation(
        confirmation_id=row["confirmation_id"], user_id=row["user_id"],
        conversation_id=row["conversation_id"], plan_id=row["plan_id"], plan_hash=row["plan_hash"],
        operations=freeze(json.loads(row["operations"])), expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
    )
    return StoredConfirmation(confirmation=confirmation, tenant_id=row["tenant_id"],
                              execution_id=row["execution_id"], status=ConfirmationStatus(row["status"]))
