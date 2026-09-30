"""M19 sabotage: the dispatch marker is never written, so recovery cannot tell a dispatched attempt from one that
never left (C35: the marker is written before every call; with it, recovery probes instead of re-executing)."""
def apply():
    from adapters.postgres.step_attempts import PostgresStepAttempts

    async def mark_dispatched(self, holder, step_id, attempt):
        return None
    PostgresStepAttempts.mark_dispatched = mark_dispatched
