"""M12 sabotage: the loop writes a log line without the correlation ids (§21 S5)."""
def apply():
    import logging
    import engine.stages.s12_execute.loop as loop
    original = loop.run_execution

    async def run_execution(deps, tenant_id, execution_id):
        logging.getLogger("engine.stages.s12_execute.loop").info("loop started")
        return await original(deps, tenant_id, execution_id)
    loop.run_execution = run_execution
