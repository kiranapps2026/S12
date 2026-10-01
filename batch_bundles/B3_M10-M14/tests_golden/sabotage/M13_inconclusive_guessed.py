"""M13 sabotage: an inconclusive probe is taken as NOT_EXECUTED (§9: probe again, then DEAD_LETTER; never guess)."""
def apply():
    from contracts.adapter_interface import ProbeOutcome
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    original = ReliabilityGuard.probe

    async def probe(self, call):
        outcome = await original(self, call)
        return ProbeOutcome.NOT_EXECUTED if outcome == ProbeOutcome.INCONCLUSIVE else outcome
    ReliabilityGuard.probe = probe
