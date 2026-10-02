"""M5 sabotage: consumption as read-then-update instead of one conditional UPDATE (several winners under concurrency)."""
def apply():
    import asyncio
    from adapters.postgres.confirmations import PostgresConfirmationStore
    from engine.stages.s10_confirmation.store import CONSUMED, MISMATCH

    async def consume(self, confirmation_id, *, tenant_id, user_id, plan_hash, now=None):
        async with self._db.tenant_transaction(tenant_id) as c:
            status = await c.fetchval("SELECT status FROM pending_confirmations WHERE confirmation_id = $1"
                                      " AND user_id = $2 AND plan_hash = $3", confirmation_id, user_id, plan_hash)
        if status != "pending":
            return MISMATCH
        await asyncio.sleep(0.05)
        async with self._db.tenant_transaction(tenant_id) as c:
            await c.execute("UPDATE pending_confirmations SET status = 'consumed', consumed_at = now()"
                            " WHERE confirmation_id = $1", confirmation_id)
        return CONSUMED
    PostgresConfirmationStore.consume = consume
