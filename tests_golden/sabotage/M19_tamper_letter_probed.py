"""M19 sabotage (CONF-043 as amended, D-3): an unresolved-uncertainty dead letter recorded without an automated retry
is written ``retry_mode = PROBE``, so an operator retry would probe a call rebuilt from a plan that failed its digest
check."""
def apply():
    from adapters.postgres.dead_letters import PostgresDeadLetters
    original = PostgresDeadLetters.create

    async def create(self, holder, *, error_type, retry_mode, **kw):
        if str(error_type) == "unknown_unresolved" and str(retry_mode) == "NONE":
            retry_mode = "PROBE"
        return await original(self, holder, error_type=error_type, retry_mode=retry_mode, **kw)
    PostgresDeadLetters.create = create
