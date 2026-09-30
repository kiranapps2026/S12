"""M19 sabotage: the idempotency ledger never answers, so a recovered step with a recorded result is probed at the
provider (§13 step 3: the ledger first; a record means no probe, suite 6 Crash B)."""
def apply():
    from adapters.postgres.idempotency import PostgresIdempotencyLedger

    async def lookup(self, tenant_id, idempotency_key):
        return None
    PostgresIdempotencyLedger.lookup = lookup
