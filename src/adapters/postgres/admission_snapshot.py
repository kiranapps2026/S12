"""Database-backed admission snapshot (CONF-027 as amended, M21).

``PostgresAdmissionSnapshot`` is an awaitable callable::

    snap = await PostgresAdmissionSnapshot(database)(tenant_id, execution_id, plan_step_id)

Every field on the returned ``AdmissionSnapshot`` is read from the database under the
tenant's RLS.  Fields with no database source default to their passing value.
"""
from __future__ import annotations

from engine.stages.s12_execute.admission_control import AdmissionSnapshot


class PostgresAdmissionSnapshot:
    """Reads the four database-backed admission gates from Postgres."""

    def __init__(self, database) -> None:
        self._db = database

    async def __call__(self, tenant_id: str, execution_id: str, plan_step_id: str) -> AdmissionSnapshot:
        async with self._db.tenant_transaction(tenant_id) as c:
            tenant = await c.fetchrow(
                "SELECT kill_switch_engaged, status, budget_pool"
                " FROM tenants WHERE tenant_id = $1", tenant_id)
            if tenant is None:
                return AdmissionSnapshot(
                    kill_switch_engaged=True, tenant_quota_exceeded=True, tenant_active=False,
                    workspace_active=True, mode_allowed=True, provider_allowed=True,
                    worker_capacity_available=False, circuit_open=False, db_pool_pressure=False,
                    budget_available=False, system_overloaded=False)

            kill_switch = tenant["kill_switch_engaged"]
            tenant_active = tenant["status"] == "active"

            budget_available = tenant["budget_pool"] > 0

            step_cost = await c.fetchval(
                "SELECT effective_risk FROM execution_steps"
                " WHERE tenant_id = $1 AND execution_id = $2 AND plan_step_id = $3",
                tenant_id, execution_id, plan_step_id)
            if step_cost is not None:
                budget_available = budget_available and step_cost <= tenant["budget_pool"]

            worker_capacity = await c.fetchval(
                "SELECT EXISTS (SELECT 1 FROM workers WHERE tenant_id = $1"
                " AND state = 'ACTIVE' AND current_load < capacity)", tenant_id)

        return AdmissionSnapshot(
            kill_switch_engaged=kill_switch,
            tenant_quota_exceeded=False,
            tenant_active=tenant_active,
            workspace_active=True,
            mode_allowed=True,
            provider_allowed=True,
            worker_capacity_available=worker_capacity,
            circuit_open=False,
            db_pool_pressure=False,
            budget_available=budget_available,
            system_overloaded=False,
        )
