"""M21 sabotage: probe attempts are not reported to the metrics hook (§21 S5: counters for probes)."""
def apply():
    from engine.stages.s13_reconciliation import probe
    original = probe.resolve_execution

    async def resolve_execution(**kw):
        kw.pop("metrics", None)
        return await original(**kw)
    probe.resolve_execution = resolve_execution
