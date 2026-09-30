"""M19 sabotage: a takeover first expires every lease of the execution, lapsed or not, so a live owner is robbed
(§13: only runs whose ownership lease is expired or absent are taken over)."""
def apply():
    from adapters.postgres.leases import PostgresLeaseManager
    original_init, original = PostgresLeaseManager.__init__, PostgresLeaseManager.acquire

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def acquire(self, *, tenant_id, worker_id, execution_id, runtime_instance_id, ttl_s, holder=None,
                      skip_locked=False):
        if holder is None and skip_locked:
            async with self._sabotage_db.tenant_transaction(tenant_id) as c:
                await c.execute("UPDATE worker_leases SET expires_at = now() - interval '1 second'"
                                " WHERE tenant_id = $1 AND execution_id = $2 AND status = 'active'",
                                tenant_id, execution_id)
        return await original(self, tenant_id=tenant_id, worker_id=worker_id, execution_id=execution_id,
                              runtime_instance_id=runtime_instance_id, ttl_s=ttl_s, holder=holder,
                              skip_locked=skip_locked)
    PostgresLeaseManager.__init__, PostgresLeaseManager.acquire = __init__, acquire
