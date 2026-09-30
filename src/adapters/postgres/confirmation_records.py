"""Read the stored confirmation row for S12 entry (gate C20). Read-only and tenant-scoped: a row of another tenant
is invisible (None), both through the query's tenant_id filter and through row-level security."""
from __future__ import annotations

from adapters.postgres.database import Database
from contracts.confirmation_record import ConsumedConfirmation


class PostgresConsumedConfirmationReader:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def read(self, confirmation_id: str, *, tenant_id: str) -> ConsumedConfirmation | None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT status, execution_id, plan_hash, user_id FROM pending_confirmations"
                " WHERE tenant_id = $1 AND confirmation_id = $2", tenant_id, confirmation_id)
        if row is None:
            return None
        return ConsumedConfirmation(row["status"], row["execution_id"], row["plan_hash"], row["user_id"])
