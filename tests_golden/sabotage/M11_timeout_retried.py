"""M11 sabotage: a timeout is retried like a server error (§9: a timeout is probed, never retried blindly)."""
def apply():
    from contracts.step_execution import AdapterResult
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    original = ReliabilityGuard.call

    async def call(self, c):
        result = await original(self, c)
        return AdapterResult("error", True, "server_error") if result.status == "timeout" else result
    ReliabilityGuard.call = call
