"""M12 sabotage: consolidation is called again after the loop, even when the run already ended (C15: a cancelled run
is not consolidated; §10: once per run)."""
def apply():
    import engine.stages.s12_execute.loop as loop
    original = loop.run_execution

    async def run_execution(deps, tenant_id, execution_id):
        result = await original(deps, tenant_id, execution_id)
        await deps.consolidate(None, tenant_id, execution_id)
        return result
    loop.run_execution = run_execution
