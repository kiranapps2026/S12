"""M11 sabotage: a ledger write that is fenced out is ignored and the result used anyway (gate §8 step 8: a
fenced-out Worker Runtime's result is discarded; FencedOut stops all work)."""
def apply():
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import FencedOut
    original = PostgresIdempotencyLedger.store

    async def store(self, holder, **kw):
        try:
            return await original(self, holder, **kw)
        except FencedOut:
            return None
    PostgresIdempotencyLedger.store = store
