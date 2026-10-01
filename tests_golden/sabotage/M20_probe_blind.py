"""M20 sabotage: the provider probe always answers NOT_EXECUTED, so a step a killed runtime already executed is run
again (§9, §13: the new owner learns the outcome by probing)."""
def apply():
    from contracts.adapter_interface import ProbeOutcome
    from engine.stages.s12_execute.reliability import ReliabilityGuard

    async def probe(self, call):
        return ProbeOutcome.NOT_EXECUTED
    ReliabilityGuard.probe = probe
