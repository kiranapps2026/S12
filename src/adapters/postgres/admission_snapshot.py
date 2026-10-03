"""Database-backed admission snapshot (CONF-027 as amended, M21; DEF-006).

``PostgresAdmissionSnapshot`` is an awaitable callable::

    snap = await PostgresAdmissionSnapshot(database)(tenant_id, execution_id, plan_step_id)

Every field on the returned ``AdmissionSnapshot`` is read from the database under the
tenant's RLS.  Fields with no database source default to their passing value.

Gate 10 (budget_available) says whether the reserve step would succeed: cost comes from
the frozen plan's canonical_plan, available = ``adapters.postgres.budget.AVAILABLE_SQL``
(pool minus reserved/locked/committed reservations in the current period), and a step
that already holds a live reservation passes regardless of pool state.  Unknown execution
or step fails closed (DEF-006).
"""
from __future__ import annotations

from adapters.postgres.budget import AVAILABLE_SQL
from adapters.postgres.budget_reserver import LIVE
from engine.stages.s12_execute.admission_control import AdmissionSnapshot

_STEP_COST = ("SELECT (s->>'cost')::int FROM execution_plans p"
              " CROSS JOIN LATERAL jsonb_array_elements(p.canonical_plan->'steps') s"
              " WHERE p.tenant_id = $1 AND p.execution_id = $2 AND s->>'id' = $3")
_HOLDS_LIVE = ("SELECT EXISTS (SELECT 1 FROM budget_reservations WHERE tenant_id = $1 AND step_id = $2"
               " AND status = ANY($3::text[]))")


class PostgresAdmissionSnapshot:
    """Reads the four database-backed admission gates from Postgres."""

    def __init__(self, database) -> None:
        self._db = database

    async def __call__(self, tenant_id: str, execution_id: str, plan_step_id: str) -> AdmissionSnapshot:
        async with self._db.tenant_transaction(tenant_id) as c:
            tenant = await c.fetchrow(
                "SELECT kill_switch_engaged, (status = 'active') AS is_active"
                " FROM tenants WHERE tenant_id = $1", tenant_id)
            if tenant is None:
                return AdmissionSnapshot(
                    kill_switch_engaged=True, tenant_quota_exceeded=True, tenant_active=False,
                    workspace_active=True, mode_allowed=True, provider_allowed=True,
                    worker_capacity_available=False, circuit_open=False, db_pool_pressure=False,
                    budget_available=False, system_overloaded=False)

            kill_switch = tenant["kill_switch_engaged"]
            tenant_active = tenant["is_active"]

            cost = await c.fetchval(_STEP_COST, tenant_id, execution_id, plan_step_id)
            if cost is None:
                budget_available = False
            elif await c.fetchval(_HOLDS_LIVE, tenant_id, f"{execution_id}:{plan_step_id}",
                                  [str(s) for s in LIVE]):
                budget_available = True
            else:
                available = await c.fetchval(AVAILABLE_SQL, tenant_id)
                budget_available = available is not None and available >= cost

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
