"""M12 sabotage: the loop's lease acquisition ignores its holder, so a step's lease takes the execution back from the
Worker Runtime that took it over (C25; only recovery takes ownership)."""
def apply():
    from adapters.postgres.leases import PostgresLeaseManager
    original = PostgresLeaseManager.acquire

    async def acquire(self, **kw):
        kw.pop("holder", None)
        return await original(self, **kw)
    PostgresLeaseManager.acquire = acquire
