"""User cancellation request (gate C16): recorded on the run; only the run's own user and tenant; no lease needed."""
from __future__ import annotations

from adapters.postgres.database import Database
from contracts.execution_states import ExecutionStatus as R

_OPEN = (R.PENDING, R.RUNNING, R.RECONCILING)
_REQUEST = ("UPDATE execution_runs SET cancel_requested_at = COALESCE(cancel_requested_at, now())"
            " WHERE tenant_id = $1 AND execution_id = $2 AND user_id = $3 AND status = ANY($4::text[])"
            " RETURNING execution_id")


class PostgresCancellation:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def request(self, tenant_id: str, execution_id: str, user_id: str) -> bool:
        async with self._db.tenant_transaction(tenant_id) as c:
            return await c.fetchval(_REQUEST, tenant_id, execution_id, user_id, [str(s) for s in _OPEN]) is not None
