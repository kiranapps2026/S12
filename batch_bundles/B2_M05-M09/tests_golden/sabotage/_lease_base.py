"""Shared by the M7 sabotage patches: a plain lease acquisition, parameterised by the flaw each patch injects.
Not a sabotage patch itself (the certifier only runs files named Mxx_*)."""
import uuid


async def acquire(self, *, tenant_id, worker_id, execution_id, runtime_instance_id, ttl_s,
                  token_sql="SELECT nextval('fence_token_seq')", expire_stale=True):
    from adapters.postgres.leases import Lease
    from adapters.postgres.transition_log import log_transition
    async with self._db.tenant_transaction(tenant_id) as c:
        w = await c.fetchrow("SELECT state, capacity FROM workers WHERE tenant_id = $1 AND worker_id = $2 FOR UPDATE",
                             tenant_id, worker_id)
        if w is None or w["state"] != "ACTIVE":
            return None
        if expire_stale:
            for r in await c.fetch("UPDATE worker_leases SET status = 'expired' WHERE tenant_id = $1 AND worker_id = $2"
                                   " AND status = 'active' AND expires_at <= now() RETURNING lease_id", tenant_id, worker_id):
                await log_transition(c, tenant_id=tenant_id, machine="lease", entity_id=r["lease_id"],
                                     from_state="active", to_state="expired", reason="ttl_elapsed",
                                     runtime_instance_id=None, fence_token=None, execution_id=None)
        n = await c.fetchval("SELECT count(*) FROM worker_leases WHERE tenant_id = $1 AND worker_id = $2"
                             " AND status = 'active'", tenant_id, worker_id)
        if n >= w["capacity"]:
            return None
        token = await c.fetchval(token_sql, *([worker_id] if "$1" in token_sql else []))
        lease_id = str(uuid.uuid4())
        await c.execute("INSERT INTO worker_leases (lease_id, tenant_id, worker_id, execution_id, fence_token, status,"
                        " expires_at) VALUES ($1, $2, $3, $4, $5, 'active', now() + make_interval(secs => $6))",
                        lease_id, tenant_id, worker_id, execution_id, token, float(ttl_s))
        await log_transition(c, tenant_id=tenant_id, machine="lease", entity_id=lease_id, from_state=None,
                             to_state="active", reason="acquired", runtime_instance_id=runtime_instance_id,
                             fence_token=token, execution_id=execution_id)
        await c.execute("UPDATE workers SET current_load = $3, lease_epoch = $4 WHERE tenant_id = $1 AND worker_id = $2",
                        tenant_id, worker_id, n + 1, token)
        await c.execute("UPDATE execution_ownership SET worker_id = $3, lease_id = $4, runtime_instance_id = $5,"
                        " fencing_token = $6 WHERE tenant_id = $1 AND execution_id = $2", tenant_id, execution_id,
                        worker_id, lease_id, runtime_instance_id, token)
        return Lease(lease_id, tenant_id, worker_id, execution_id, token)
