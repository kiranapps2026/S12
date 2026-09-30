"""M7 sabotage: tokens counted per worker (max + 1) instead of from fence_token_seq (C25 trap): a takeover by another
worker gets a smaller token."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("lease_base", pathlib.Path(__file__).with_name("_lease_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    from adapters.postgres.leases import PostgresLeaseManager

    async def acquire(self, **kw):
        return await base.acquire(self, **kw, token_sql="SELECT COALESCE(max(fence_token), 0) + 1 FROM worker_leases"
                                                        " WHERE worker_id = $1")
    PostgresLeaseManager.acquire = acquire
