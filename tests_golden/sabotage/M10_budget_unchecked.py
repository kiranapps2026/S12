"""M10 sabotage: BudgetTracker lets any call through (C31: the step's reservation must exist, be its own and LOCKED)."""
def apply():
    from engine.stages.s12_execute.reliability import BudgetTracker

    async def check(self, call):
        return None
    BudgetTracker.check = check
