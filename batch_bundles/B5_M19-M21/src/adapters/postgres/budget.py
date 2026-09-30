"""Budget arithmetic shared by S8's precheck and S12's reserve (gate C3, C33).

available = tenants.budget_pool - sum(cost of the tenant's reserved/locked/committed reservations
created in the current period); the period start is computed from database time, UTC.
"""
from __future__ import annotations

PERIOD_START_SQL = (
    "date_trunc(CASE t.budget_period WHEN 'daily' THEN 'day' WHEN 'weekly' THEN 'week' ELSE 'month' END,"
    " now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'")

AVAILABLE_SQL = f"""
    SELECT t.budget_pool - COALESCE((
        SELECT SUM(r.cost) FROM budget_reservations r
         WHERE r.tenant_id = t.tenant_id
           AND r.status IN ('reserved', 'locked', 'committed')
           AND r.created_at >= {PERIOD_START_SQL}), 0) AS available
      FROM tenants t WHERE t.tenant_id = $1"""
