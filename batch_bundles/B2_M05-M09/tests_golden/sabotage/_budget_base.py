"""Shared by the M9 sabotage patches: a reserve() whose availability query and locking the patch chooses.
Not a sabotage patch itself (the certifier only runs files named Mxx_*)."""
import asyncio
import uuid


async def reserve(self, holder, *, user_id, step_id, cost, lock_tenant=True, period=True, pause=0.0):
    from adapters.postgres.budget import PERIOD_START_SQL
    from adapters.postgres.budget_reserver import Reservation
    from adapters.postgres.fencing import fenced_write
    from adapters.postgres.transition_log import log_transition
    window = f" AND r.created_at >= {PERIOD_START_SQL}" if period else ""
    available_sql = ("SELECT t.budget_pool - COALESCE((SELECT SUM(r.cost) FROM budget_reservations r"
                     " WHERE r.tenant_id = t.tenant_id AND r.status IN ('reserved','locked','committed')" + window +
                     "), 0) FROM tenants t WHERE t.tenant_id = $1")

    async def write(c):
        if lock_tenant:
            await c.fetchval("SELECT 1 FROM tenants WHERE tenant_id = $1 FOR UPDATE", holder.tenant_id)
        live = await c.fetchrow("SELECT reservation_id, status FROM budget_reservations WHERE tenant_id = $1"
                                " AND step_id = $2 AND status <> 'released'", holder.tenant_id, step_id)
        if live is not None:
            return Reservation(live["reservation_id"], live["status"])
        available = await c.fetchval(available_sql, holder.tenant_id)
        await asyncio.sleep(pause)
        if available < cost:
            return Reservation(None, None, "budget_exhausted")
        rid = str(uuid.uuid4())
        await c.execute("INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id,"
                        " cost, status) VALUES ($1,$2,$3,$4,$5,$6,'reserved')", rid, holder.tenant_id, user_id,
                        holder.execution_id, step_id, cost)
        await c.execute("UPDATE execution_steps SET reservation_id = $3 WHERE tenant_id = $1 AND step_id = $2",
                        holder.tenant_id, step_id, rid)
        await log_transition(c, tenant_id=holder.tenant_id, machine="reservation", entity_id=rid, from_state=None,
                             to_state="reserved", reason="reserved", runtime_instance_id=holder.runtime_instance_id,
                             fence_token=holder.fence_token, execution_id=holder.execution_id)
        return Reservation(rid, "reserved")
    return await fenced_write(self._db, holder, write)

