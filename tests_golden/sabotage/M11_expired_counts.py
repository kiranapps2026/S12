"""M11 sabotage: an expired ledger record still counts as a record (gate §8 step 8: expired = no record)."""
def apply():
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    original_init, original_lookup = PostgresIdempotencyLedger.__init__, PostgresIdempotencyLedger.lookup

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def lookup(self, tenant_id, idempotency_key):
        async with self._sabotage_db.tenant_transaction(tenant_id) as c:
            await c.execute("UPDATE idempotency_ledger SET expires_at = now() + interval '1 day'"
                            " WHERE tenant_id = $1 AND idempotency_key = $2", tenant_id, idempotency_key)
        return await original_lookup(self, tenant_id, idempotency_key)
    PostgresIdempotencyLedger.__init__, PostgresIdempotencyLedger.lookup = __init__, lookup
