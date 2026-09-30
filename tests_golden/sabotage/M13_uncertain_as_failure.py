"""M13 sabotage: an uncertain attempt is treated as a failure (§9: every UNKNOWN passes through PENDING_PROBE)."""
def apply():
    import engine.stages.s12_execute.attempts as attempts
    from contracts.step_execution import AdapterResult
    original = attempts.run_attempts

    async def run_attempts(step, holder, deps, *, first_attempt=1):
        outcome = await original(step, holder, deps, first_attempt=first_attempt)
        if outcome.kind == "uncertain":
            return attempts.AttemptOutcome("failure", AdapterResult("error", False, "server_error"), outcome.attempts)
        return outcome
    attempts.run_attempts = run_attempts
