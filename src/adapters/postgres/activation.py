"""S0.1 activation state from the tenant and workspace rows, with the database clock."""
from __future__ import annotations

from adapters.postgres.database import Database
from contracts.activation import ActivationState
from contracts.errors import DependencyUnavailable

_SQL = """
SELECT EXTRACT(EPOCH FROM clock_timestamp())::float8 AS database_now,
       EXTRACT(EPOCH FROM t.paused_until)::float8 AS tenant_paused_until,
       EXTRACT(EPOCH FROM t.scheduled_activation_at)::float8 AS tenant_activation_at,
       EXTRACT(EPOCH FROM w.paused_until)::float8 AS workspace_paused_until,
       EXTRACT(EPOCH FROM w.scheduled_activation_at)::float8 AS workspace_activation_at
  FROM tenants t JOIN workspaces w ON w.tenant_id = t.tenant_id
 WHERE t.tenant_id = $1 AND w.workspace_id = $2
"""


class PostgresActivationReader:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def read(self, tenant_id: str, workspace_id: str) -> ActivationState:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(_SQL, tenant_id, workspace_id)
        if row is None:
            raise DependencyUnavailable("tenant or workspace not found")
        return ActivationState(**dict(row))
