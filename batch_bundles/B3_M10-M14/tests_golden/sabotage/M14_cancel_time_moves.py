"""M14 sabotage: every cancel request overwrites the request time, and a finished run still accepts one (C16: the
first request counts; only an open run can be cancelled)."""
def apply():
    from adapters.postgres.cancellation import PostgresCancellation
    original_init = PostgresCancellation.__init__

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def request(self, tenant_id, execution_id, user_id):
        async with self._sabotage_db.tenant_transaction(tenant_id) as c:
            return await c.fetchval("UPDATE execution_runs SET cancel_requested_at = clock_timestamp()"
                                    " WHERE tenant_id = $1 AND execution_id = $2 AND user_id = $3"
                                    " RETURNING execution_id", tenant_id, execution_id, user_id) is not None
    PostgresCancellation.__init__, PostgresCancellation.request = __init__, request
