"""M10 sabotage: an error whose text mentions a timeout is treated as a timeout (C32/MC-008: TimeoutManager only)."""
def apply():
    from contracts.step_execution import AdapterResult
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    original = ReliabilityGuard.call

    async def call(self, c):
        result = await original(self, c)
        if result.status == "error" and "timeout" in repr(result.data).lower():
            return AdapterResult("timeout", False, "timeout")
        return result
    ReliabilityGuard.call = call
