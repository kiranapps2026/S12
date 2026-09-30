"""M21 sabotage: the S12 loop asks the S5 resolver again before it runs (suite 2: no resolver, risk or mutation
recomputation after S11; the frozen binding is used)."""
def apply():
    from engine.stages.s12_execute import loop
    original = loop.run_execution

    async def run_execution(deps, tenant_id, execution_id):
        from engine.stages.s5_provider_resolution import handler
        try:
            handler.handle(None, None, None)
        except TypeError:
            pass
        return await original(deps, tenant_id, execution_id)
    loop.run_execution = run_execution
