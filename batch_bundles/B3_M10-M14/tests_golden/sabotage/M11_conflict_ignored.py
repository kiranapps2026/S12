"""M11 sabotage: a conflicting ledger row is silently accepted (gate §8 step 8: IdempotencyConflict)."""
def apply():
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.idempotency import IdempotencyConflict
    original = PostgresIdempotencyLedger.store

    async def store(self, holder, **kw):
        try:
            await original(self, holder, **kw)
        except IdempotencyConflict:
            return None
    PostgresIdempotencyLedger.store = store
