"""M10 sabotage: the circuit breaker is consulted before the Bulkhead slot is acquired (RELIABILITY §8: Bulkhead first)."""
def apply():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("guard_base", pathlib.Path(__file__).with_name("_guard_base.py"))
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    from contracts.step_execution import AdapterResult
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    base.capture()
    original = ReliabilityGuard.call

    async def call(self, c):
        breaker = self._sabotage["breaker"]
        if not breaker.allow(c.binding.provider):
            return AdapterResult("error", False, "circuit_open")
        breaker.record_ignored(c.binding.provider)
        return await original(self, c)
    ReliabilityGuard.call = call
