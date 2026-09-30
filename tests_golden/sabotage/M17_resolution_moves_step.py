"""M17 sabotage: resolving a dead letter also "re-opens" the step (D4: a resolution never changes the run or the
step)."""
def apply():
    from adapters.postgres.dead_letters import PostgresDeadLetters
    original_init, original = PostgresDeadLetters.__init__, PostgresDeadLetters.resolve

    def __init__(self, database):
        original_init(self, database)
        self._sabotage_db = database

    async def resolve(self, tenant_id, dead_letter_id, outcome):
        await original(self, tenant_id, dead_letter_id, outcome)
        async with self._sabotage_db.tenant_transaction(tenant_id) as c:
            await c.execute("UPDATE execution_steps SET status = 'failed' WHERE tenant_id = $1 AND step_id ="
                            " (SELECT step_id FROM dead_letters WHERE dead_letter_id = $2)", tenant_id,
                            dead_letter_id)
    PostgresDeadLetters.__init__, PostgresDeadLetters.resolve = __init__, resolve
