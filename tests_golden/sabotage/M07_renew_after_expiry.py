"""M7 sabotage: a lease past expires_at can still be renewed (C26: never)."""
def apply():
    from dataclasses import replace
    from adapters.postgres.leases import LeaseLost, PostgresLeaseManager
    from adapters.postgres.transition_log import log_transition

    async def renew(self, lease, *, runtime_instance_id, ttl_s):
        async with self._db.tenant_transaction(lease.tenant_id) as c:
            ok = await c.fetchval("SELECT 1 FROM worker_leases WHERE tenant_id = $1 AND lease_id = $2"
                                  " AND status = 'active'", lease.tenant_id, lease.lease_id)
            if not ok:
                raise LeaseLost(lease.lease_id)
            token = await c.fetchval("SELECT nextval('fence_token_seq')")
            await c.execute("UPDATE execution_ownership SET fencing_token = $3 WHERE tenant_id = $1 AND execution_id = $2",
                            lease.tenant_id, lease.execution_id, token)
            await c.execute("UPDATE worker_leases SET fence_token = $3, expires_at = now() + make_interval(secs => $4)"
                            " WHERE tenant_id = $1 AND lease_id = $2", lease.tenant_id, lease.lease_id, token, float(ttl_s))
            await log_transition(c, tenant_id=lease.tenant_id, machine="lease", entity_id=lease.lease_id,
                                 from_state="active", to_state="active", reason="renewed",
                                 runtime_instance_id=runtime_instance_id, fence_token=token, execution_id=lease.execution_id)
            return replace(lease, fence_token=token)
    PostgresLeaseManager.renew = renew
