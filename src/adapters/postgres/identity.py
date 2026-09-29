"""Live authorization state (S8, R-C) read from tenant tables under row-level security.

The S8 provider protocol is synchronous (R-C) and has no tenant parameter, so an instance
is bound to ONE tenant at construction (built per run by PostgresRunScopes). It must be
called from a worker thread (S8 runs its checks with asyncio.to_thread); every method
raises when the database cannot answer or the row is invisible, and S8 turns that into
a `<check>_unavailable` DENY.
"""
from __future__ import annotations

import types

from adapters.postgres.database import Database, LoopBridge
from contracts.errors import DependencyUnavailable


class PostgresAuthorizationState:
    def __init__(self, database: Database, tenant_id: str, bridge: LoopBridge) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self._db = database
        self._tenant = tenant_id
        self._bridge = bridge

    def _fetchrow(self, sql: str, *args):
        async def run():
            async with self._db.tenant_transaction(self._tenant) as connection:
                return await connection.fetchrow(sql, *args)
        return self._bridge.call(run())

    def _one(self, sql: str, *args):
        row = self._fetchrow(sql, *args)
        if row is None:
            raise DependencyUnavailable("record not found")
        return row

    def user_status(self, user_id: str) -> str:
        return self._one("SELECT status FROM users WHERE user_id = $1", user_id)["status"]

    def tenant_status(self, tenant_id: str) -> str:
        self._require_own(tenant_id)
        return self._one("SELECT status FROM tenants WHERE tenant_id = $1", tenant_id)["status"]

    def connection_status(self, connection_id: str) -> tuple[str, float | None]:
        row = self._one(
            "SELECT status, EXTRACT(EPOCH FROM expires_at)::float8 AS expires_at"
            "  FROM connections WHERE connection_id = $1", connection_id)
        return row["status"], row["expires_at"]

    def has_grant(self, tenant_id: str, user_id: str, capability_id: str) -> bool:
        self._require_own(tenant_id)
        return bool(self._one("""
            SELECT EXISTS (SELECT 1 FROM capability_grants
             WHERE user_id = $1 AND capability_id = $2 AND is_active
               AND (expires_at IS NULL OR expires_at > now())) AS ok""",
            user_id, capability_id)["ok"])

    def in_scope(self, tenant_id: str, user_id: str, workspace_id: str) -> bool:
        self._require_own(tenant_id)
        return bool(self._one("""
            SELECT EXISTS (SELECT 1 FROM memberships
             WHERE user_id = $1 AND workspace_id = $2 AND is_active AND revoked_at IS NULL) AS ok""",
            user_id, workspace_id)["ok"])

    def budget_available(self, tenant_id: str, amount: float) -> bool:
        """Pool minus the reservations of the current period (database time, UTC) >= amount.

        Reserved, locked and committed reservations count; released ones do not. A precheck
        only: S12's atomic reserve (row lock on the tenant) is the authority.
        """
        self._require_own(tenant_id)
        available = self._one("""
            SELECT t.budget_pool - COALESCE((
                SELECT SUM(r.cost) FROM budget_reservations r
                 WHERE r.tenant_id = t.tenant_id
                   AND r.status IN ('reserved', 'locked', 'committed')
                   AND r.created_at >= date_trunc(
                        CASE t.budget_period WHEN 'daily' THEN 'day' WHEN 'weekly' THEN 'week' ELSE 'month' END,
                        now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0) AS available
              FROM tenants t WHERE t.tenant_id = $1""", tenant_id)["available"]
        return available >= amount

    def _require_own(self, tenant_id: str) -> None:
        """A provider bound to one tenant refuses to answer for another."""
        if tenant_id != self._tenant:
            raise DependencyUnavailable("tenant mismatch")


_SEVERITY = types.MappingProxyType({"R": 0, "W": 1, "D": 2, "IRREVERSIBLE": 3})


class PostgresMutationPolicy:
    """A mutation is permitted up to the tenant's ``max_mutation`` ceiling. Bound to one tenant."""

    def __init__(self, database: Database, tenant_id: str, bridge: LoopBridge) -> None:
        self._db, self._tenant, self._bridge = database, tenant_id, bridge

    def permits(self, mutation: str, risk: float) -> bool:
        async def run():
            async with self._db.tenant_transaction(self._tenant) as connection:
                return await connection.fetchval(
                    "SELECT max_mutation FROM tenants WHERE tenant_id = $1", self._tenant)
        ceiling = self._bridge.call(run())
        if ceiling is None:
            raise DependencyUnavailable("tenant not found")
        if mutation not in _SEVERITY or ceiling not in _SEVERITY:
            raise DependencyUnavailable("unknown mutation value")
        return _SEVERITY[mutation] <= _SEVERITY[ceiling]
