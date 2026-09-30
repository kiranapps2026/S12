"""M12 sabotage: the reservation locks in its own transaction, not in the step's start (Appendix A.2, I-3)."""
def apply():
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    original = PostgresBudgetReserver.lock

    async def lock(self, holder, reservation_id, *, reason, connection=None):
        await original(self, holder, reservation_id, reason=reason)
    PostgresBudgetReserver.lock = lock
