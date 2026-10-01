"""M12 sabotage: a fenced-out loop keeps its lease (Appendix A.4: it is released ``fenced_out``; the worker's capacity
is not held by a runtime that must stop)."""
def apply():
    from adapters.postgres.leases import PostgresLeaseManager
    original = PostgresLeaseManager.release

    async def release(self, lease, *, reason):
        if reason == "fenced_out":
            return False
        return await original(self, lease, reason=reason)
    PostgresLeaseManager.release = release
