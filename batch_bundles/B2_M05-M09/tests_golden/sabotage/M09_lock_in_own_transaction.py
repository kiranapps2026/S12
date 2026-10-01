"""M9 sabotage: lock ignores the caller's connection and commits on its own (I-3: step start and lock must be one
transaction)."""
def apply():
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    original = PostgresBudgetReserver.lock

    async def lock(self, holder, reservation_id, *, reason, connection=None):
        await original(self, holder, reservation_id, reason=reason)
    PostgresBudgetReserver.lock = lock
