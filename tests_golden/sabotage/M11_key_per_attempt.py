"""M11 sabotage: each attempt carries its own idempotency key (C9: one key per step, stable across attempts)."""
def apply():
    from dataclasses import replace
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    original = ReliabilityGuard.call

    async def call(self, c):
        meta = replace(c.call_meta, idempotency_key=f"{c.call_meta.idempotency_key}:{c.attempt}")
        return await original(self, replace(c, call_meta=meta))
    ReliabilityGuard.call = call
