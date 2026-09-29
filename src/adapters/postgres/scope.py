"""Per-run scope from PostgreSQL: live kernel policy, policy versions, tenant-bound S8 providers."""
from __future__ import annotations

from adapters.postgres.database import Database, LoopBridge
from adapters.postgres.identity import PostgresAuthorizationState, PostgresMutationPolicy
from contracts.errors import DependencyUnavailable
from contracts.kernel_policy import KernelPolicy, PolicyVersions
from engine.control_plane.scope import RunScope
from engine.stages.s8_safety_gate.dependencies import CircuitBreaker, S8Dependencies


class PostgresRunScopes:
    """Reads the kill switch and policy versions fresh on every run (it must take effect
    immediately) and binds every S8 provider to the run's tenant."""

    def __init__(self, database: Database, circuit_breaker: CircuitBreaker) -> None:
        self._db = database
        self._breaker = circuit_breaker

    async def for_run(self, tenant_id: str, workspace_id: str) -> RunScope:
        async with self._db.tenant_transaction(tenant_id) as connection:
            policy_row = await connection.fetchrow("""
                SELECT s.kill_switch_engaged OR t.kill_switch_engaged AS kill_switch_engaged,
                       s.risk_deny_threshold
                  FROM system_settings s CROSS JOIN tenants t WHERE t.tenant_id = $1""", tenant_id)
            versions_row = await connection.fetchrow("""
                SELECT t.policy_version_id AS tenant_policy_version_id,
                       COALESCE(w.policy_version_id, t.policy_version_id) AS workspace_policy_version_id,
                       COALESCE(w.policy_version_id, t.policy_version_id) AS policy_version_id
                  FROM tenants t JOIN workspaces w ON w.tenant_id = t.tenant_id
                 WHERE t.tenant_id = $1 AND w.workspace_id = $2""", tenant_id, workspace_id)
        if policy_row is None or versions_row is None:
            raise DependencyUnavailable("tenant or workspace not found")
        bridge = LoopBridge.current()
        return RunScope(
            policy=KernelPolicy(**dict(policy_row)),
            s8=S8Dependencies(
                policy=KernelPolicy(**dict(policy_row)),
                auth_state=PostgresAuthorizationState(self._db, tenant_id, bridge),
                circuit_breaker=self._breaker,
                mutation_policy=PostgresMutationPolicy(self._db, tenant_id, bridge),
            ),
            policy_versions=PolicyVersions(**dict(versions_row)),
        )
