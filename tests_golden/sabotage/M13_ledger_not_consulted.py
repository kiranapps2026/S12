"""M13 sabotage: the ledger is never consulted, so the probe path probes although a definitive result exists (§9:
ledger before probe)."""
def apply():
    from adapters.postgres.idempotency import PostgresIdempotencyLedger

    async def lookup(self, tenant_id, idempotency_key):
        return None
    PostgresIdempotencyLedger.lookup = lookup
