"""M15 sabotage: a verification uncertainty is recorded as an EXECUTION episode (C19: two different questions; a
VERIFICATION episode never probes and never ends NOT_EXECUTED)."""
def apply():
    from adapters.postgres.reconciliation import PostgresEpisodes
    original = PostgresEpisodes.open

    async def open(self, holder, *, step_id, kind):
        return await original(self, holder, step_id=step_id, kind="EXECUTION")
    PostgresEpisodes.open = open
