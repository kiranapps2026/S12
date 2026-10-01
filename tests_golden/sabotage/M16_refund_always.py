"""M16 sabotage: the quota is refunded whenever a run ends, not only when it ends CANCELLED with no step COMPLETED
(C39)."""
def apply():
    from adapters.postgres.consolidation import PostgresConsolidator
    original_init, original = PostgresConsolidator.__init__, PostgresConsolidator.consolidate

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def consolidate(self, holder, tenant_id, execution_id):
        result = await original(self, holder, tenant_id, execution_id)
        async with self._sabotage_db.tenant_transaction(tenant_id) as c:
            await c.execute("UPDATE operation_quotas SET used_count = used_count - 1 WHERE tenant_id = $1"
                            " AND used_count > 0", tenant_id)
        return result
    PostgresConsolidator.__init__, PostgresConsolidator.consolidate = __init__, consolidate
