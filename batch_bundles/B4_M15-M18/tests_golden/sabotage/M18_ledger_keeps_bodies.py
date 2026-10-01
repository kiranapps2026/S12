"""M18 sabotage: a failure's provider body is stored in the idempotency ledger (§12, §21 S6: provider bodies and
secrets never reach a persisted row)."""
def apply():
    import json
    from adapters.postgres.fencing import fenced_write
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    original_init = PostgresIdempotencyLedger.__init__

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def store(self, holder, *, idempotency_key, kernel_op_id, result, ttl_s):
        body = json.dumps({"status": result.status, "error_class": result.error_class, "data": result.data or {}})

        async def write(c):
            await c.execute("INSERT INTO idempotency_ledger (idempotency_key, tenant_id, kernel_op_id, result,"
                            " expires_at) VALUES ($1, $2, $3, $4::jsonb, now() + make_interval(secs => $5))"
                            " ON CONFLICT (idempotency_key) DO NOTHING", idempotency_key, holder.tenant_id,
                            kernel_op_id, body, float(ttl_s))
        await fenced_write(self._sabotage_db, holder, write)
    PostgresIdempotencyLedger.__init__, PostgresIdempotencyLedger.store = __init__, store
