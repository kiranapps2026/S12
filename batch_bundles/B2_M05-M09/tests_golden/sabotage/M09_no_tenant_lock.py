"""M9 sabotage: availability is read without locking the tenant row (C3): concurrent reservations over-reserve."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("budget_base", pathlib.Path(__file__).with_name("_budget_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    from adapters.postgres.budget_reserver import PostgresBudgetReserver

    async def reserve(self, holder, **kw):
        return await base.reserve(self, holder, **kw, lock_tenant=False, pause=0.05)
    PostgresBudgetReserver.reserve = reserve
