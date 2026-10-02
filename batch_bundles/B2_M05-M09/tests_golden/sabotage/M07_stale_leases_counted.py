"""M7 sabotage: an acquisition counts leases whose expires_at has passed as still active (C26: expire them first)."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("lease_base", pathlib.Path(__file__).with_name("_lease_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    from adapters.postgres.leases import PostgresLeaseManager

    async def acquire(self, **kw):
        return await base.acquire(self, **kw, expire_stale=False)
    PostgresLeaseManager.acquire = acquire
