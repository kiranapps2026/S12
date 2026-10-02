"""M11 sabotage: a ledger row is taken as a hit whatever operation wrote it (§8 step 8: another kernel_op_id under the
step's key is an IdempotencyConflict, never a cached result)."""
def apply():
    import dataclasses
    from adapters.postgres.idempotency import PostgresIdempotencyLedger

    class AnyOperation(str):
        def __eq__(self, other):
            return True

        def __ne__(self, other):
            return False

        __hash__ = str.__hash__

    original = PostgresIdempotencyLedger.lookup

    async def lookup(self, tenant_id, idempotency_key):
        record = await original(self, tenant_id, idempotency_key)
        return None if record is None else dataclasses.replace(record, kernel_op_id=AnyOperation(record.kernel_op_id))
    PostgresIdempotencyLedger.lookup = lookup
