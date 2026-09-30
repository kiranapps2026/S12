"""M9 sabotage: availability counts every period, not only the current one (C33)."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("budget_base", pathlib.Path(__file__).with_name("_budget_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    from adapters.postgres.budget_reserver import PostgresBudgetReserver

    async def reserve(self, holder, **kw):
        return await base.reserve(self, holder, **kw, period=False)
    PostgresBudgetReserver.reserve = reserve
