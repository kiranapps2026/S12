"""M11 sabotage: the dispatch marker is never written (C35: written and committed before every call)."""
def apply():
    from adapters.postgres.step_attempts import PostgresStepAttempts

    async def mark_dispatched(self, holder, step_id, attempt):
        return None
    PostgresStepAttempts.mark_dispatched = mark_dispatched
