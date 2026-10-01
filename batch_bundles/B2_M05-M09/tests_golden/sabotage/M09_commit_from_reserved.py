"""M9 sabotage: commit writes 'committed' from any state (the RESERVED -> COMMITTED shortcut C3 forbids)."""
def apply():
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    from adapters.postgres.fencing import fenced_write

    async def commit(self, holder, reservation_id, *, reason):
        async def write(c):
            await c.execute("UPDATE budget_reservations SET status = 'committed', committed_at = now()"
                            " WHERE tenant_id = $1 AND reservation_id = $2", holder.tenant_id, reservation_id)
        await fenced_write(self._db, holder, write)
    PostgresBudgetReserver.commit = commit
