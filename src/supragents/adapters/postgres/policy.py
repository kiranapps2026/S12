"""Kernel policy (kill switch, deny threshold), policy versions and the mutation ceiling."""
from __future__ import annotations

from supragents.adapters.postgres.database import Database
from supragents.contracts.errors import DependencyUnavailable
from supragents.contracts.vocabulary import Mutation
from supragents.ports.policy import KernelPolicy, PolicyVersions


class PostgresKernelPolicy:
    """The kill switch is engaged if either the system or the tenant switch is on."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def current(self, tenant_id: str) -> KernelPolicy:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow("""
                SELECT s.kill_switch_engaged OR t.kill_switch_engaged AS kill_switch_engaged,
                       s.risk_deny_threshold
                  FROM system_settings s CROSS JOIN tenants t WHERE t.tenant_id = $1""", tenant_id)
        if row is None:
            raise DependencyUnavailable("tenant not found")
        return KernelPolicy(**dict(row))


class PostgresPolicyVersions:
    """The effective version is the workspace's own, else the tenant's."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def current(self, tenant_id: str, workspace_id: str) -> PolicyVersions:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow("""
                SELECT t.policy_version_id AS tenant_policy_version_id,
                       COALESCE(w.policy_version_id, t.policy_version_id) AS workspace_policy_version_id,
                       COALESCE(w.policy_version_id, t.policy_version_id) AS policy_version_id
                  FROM tenants t JOIN workspaces w ON w.tenant_id = t.tenant_id
                 WHERE t.tenant_id = $1 AND w.workspace_id = $2""", tenant_id, workspace_id)
        if row is None:
            raise DependencyUnavailable("tenant or workspace not found")
        return PolicyVersions(**dict(row))


class PostgresMutationPolicy:
    """A mutation is permitted up to the tenant's ``max_mutation`` ceiling."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def permits(self, tenant_id: str, mutation: Mutation, risk: float) -> bool:
        async with self._db.tenant_transaction(tenant_id) as connection:
            ceiling = await connection.fetchval(
                "SELECT max_mutation FROM tenants WHERE tenant_id = $1", tenant_id)
        if ceiling is None:
            raise DependencyUnavailable("tenant not found")
        return mutation.severity <= Mutation(ceiling).severity
