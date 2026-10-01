"""M14 sabotage: the live check writes (C23: LiveAuthorizationCheck is read-only)."""
def apply():
    from adapters.postgres.live_authorization import PostgresLiveAuthorization
    original_init, original = PostgresLiveAuthorization.__init__, PostgresLiveAuthorization.check

    def __init__(self, scopes, **kw):
        original_init(self, scopes, **kw)
        self._sabotage_db = kw.get("database")

    async def check(self, **kw):
        async with self._sabotage_db.tenant_transaction(kw["tenant_id"]) as c:
            await c.execute("INSERT INTO pipeline_events (tenant_id, stage, status, duration_ms) VALUES ($1, 'S12',"
                            " 'normal', 0)", kw["tenant_id"])
        return await original(self, **kw)
    PostgresLiveAuthorization.__init__, PostgresLiveAuthorization.check = __init__, check
