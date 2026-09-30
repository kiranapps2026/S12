"""M11 sabotage: a missing record is trusted although the attempt was already dispatched (§8: probe, never a blind
call)."""
def apply():
    from adapters.postgres.step_attempts import PostgresStepAttempts

    async def dispatched(self, tenant_id, step_id):
        return None
    PostgresStepAttempts.dispatched = dispatched
