"""M14 sabotage: no live check immediately before an adapter call (C23: before every call, not only per step)."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.attempts as attempts
    original = attempts.run_attempts

    class Allow:
        async def check(self, **kw):
            return None

    async def run_attempts(step, holder, deps, *, first_attempt=1):
        return await original(step, holder, dataclasses.replace(deps, live=Allow()), first_attempt=first_attempt)
    attempts.run_attempts = run_attempts
