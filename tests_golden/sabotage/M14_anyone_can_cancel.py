"""M14 sabotage: any user of any tenant can cancel a run (C16: only the run's own user and tenant)."""
def apply():
    from adapters.postgres.cancellation import PostgresCancellation
    original_init = PostgresCancellation.__init__

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def request(self, tenant_id, execution_id, user_id):
        async with self._sabotage_db.transaction() as c:
            await c.execute("SELECT set_config('row_security', 'off', true)")
        return True
    PostgresCancellation.__init__, PostgresCancellation.request = __init__, request
