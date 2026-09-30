"""M20 sabotage: a sweeper waits for an ownership row another sweeper holds instead of skipping it (§21 S4: FOR UPDATE
SKIP LOCKED, so sweepers never wait on, or double-claim, the same execution)."""
def apply():
    from adapters.postgres.leases import PostgresLeaseManager
    original = PostgresLeaseManager.acquire

    async def acquire(self, *, skip_locked=False, **kw):
        return await original(self, skip_locked=False, **kw)
    PostgresLeaseManager.acquire = acquire
