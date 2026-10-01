"""M11 sabotage: the ledger is never consulted, so a cached result is executed again (C17: no call on a hit)."""
def apply():
    from adapters.postgres.idempotency import PostgresIdempotencyLedger

    async def lookup(self, tenant_id, idempotency_key):
        return None
    PostgresIdempotencyLedger.lookup = lookup
