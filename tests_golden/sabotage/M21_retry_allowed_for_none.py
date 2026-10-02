"""M21 sabotage (CONF-049, D-9): the operator path may retry a dead letter whose ``retry_mode`` is NONE (D5: such a
record leaves ``pending`` only by a human resolution): the store stops refusing it and reports it as PROBE."""
def apply():
    import dataclasses
    from adapters.postgres import dead_letters as module
    from adapters.postgres.dead_letters import PostgresDeadLetters
    get, record = PostgresDeadLetters.get, module._record

    def as_probe(found):
        if found is not None and str(found.retry_mode) == "NONE":
            return dataclasses.replace(found, retry_mode="PROBE")
        return found

    async def get_any(self, tenant_id, dead_letter_id):
        return as_probe(await get(self, tenant_id, dead_letter_id))

    async def start_retry(self, tenant_id, dead_letter_id):
        async with self._db.tenant_transaction(tenant_id) as c:
            row = await self._locked(c, tenant_id, dead_letter_id)
            await self._move(c, row, module.D.RETRYING, "retry_started")
            return as_probe(record(await self._locked(c, tenant_id, dead_letter_id)))
    PostgresDeadLetters.get = get_any
    PostgresDeadLetters.start_retry = start_retry
