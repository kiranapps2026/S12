"""Activation state (S0.1) and live authorization state (S8) from tenant tables."""
from __future__ import annotations

from supragents.adapters.postgres.database import Database
from supragents.contracts.errors import DependencyUnavailable
from supragents.contracts.vocabulary import RecordStatus
from supragents.ports.activation import ActivationState
from supragents.ports.authorization import ConnectionState

_ACTIVATION_SQL = """
SELECT EXTRACT(EPOCH FROM now())::float8 AS database_now,
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
            row = await connection.fetchrow(_ACTIVATION_SQL, tenant_id, workspace_id)
        if row is None:
            raise DependencyUnavailable("tenant or workspace not found")
        return ActivationState(**dict(row))


class PostgresAuthorizationState:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def _value(self, tenant_id: str, sql: str, *args: object) -> object:
        async with self._db.tenant_transaction(tenant_id) as connection:
            return await connection.fetchval(sql, *args)

    async def _status(self, tenant_id: str, sql: str, key: str) -> RecordStatus:
        status = await self._value(tenant_id, sql, key)
        if status is None:
            raise DependencyUnavailable("record not found")
        return RecordStatus(status)

    async def user_status(self, tenant_id: str, user_id: str) -> RecordStatus:
        return await self._status(tenant_id, "SELECT status FROM users WHERE user_id = $1", user_id)

    async def tenant_status(self, tenant_id: str) -> RecordStatus:
        return await self._status(tenant_id, "SELECT status FROM tenants WHERE tenant_id = $1", tenant_id)

    async def connection_state(self, tenant_id: str, connection_id: str) -> ConnectionState:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT status, EXTRACT(EPOCH FROM expires_at)::float8 AS expires_at"
                "  FROM connections WHERE connection_id = $1", connection_id)
        if row is None:
            raise DependencyUnavailable("connection not found")
        return ConnectionState(status=RecordStatus(row["status"]), expires_at=row["expires_at"])

    async def has_grant(self, tenant_id: str, user_id: str, capability_id: str) -> bool:
        return bool(await self._value(tenant_id, """
            SELECT EXISTS (SELECT 1 FROM capability_grants
             WHERE user_id = $1 AND capability_id = $2 AND is_active
               AND (expires_at IS NULL OR expires_at > now()))""", user_id, capability_id))

    async def workspace_in_scope(
        self, tenant_id: str, user_id: str, workspace_id: str, membership_id: str
    ) -> bool:
        return bool(await self._value(tenant_id, """
            SELECT EXISTS (SELECT 1 FROM memberships
             WHERE membership_id = $1 AND user_id = $2 AND workspace_id = $3
               AND is_active AND revoked_at IS NULL)""", membership_id, user_id, workspace_id))

    async def budget_available(self, tenant_id: str, amount: int) -> bool:
        """Precheck against the tenant pool; S12 adds reservations to this sum (gate C33)."""
        pool = await self._value(tenant_id, "SELECT budget_pool FROM tenants WHERE tenant_id = $1", tenant_id)
        if pool is None:
            raise DependencyUnavailable("tenant not found")
        return pool >= amount
