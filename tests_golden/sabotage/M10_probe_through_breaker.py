"""M10 sabotage: probes are refused while the breaker is open (C23/§9: probes always run to settle uncertainty)."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("guard_base", pathlib.Path(__file__).with_name("_guard_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    from contracts.adapter_interface import ProbeOutcome
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    base.capture()
    original = ReliabilityGuard.probe

    async def probe(self, c):
        breaker = self._sabotage["breaker"]
        if breaker.state(c.binding.provider) == "OPEN":
            return ProbeOutcome.INCONCLUSIVE
        return await original(self, c)
    ReliabilityGuard.probe = probe
