"""M18 sabotage: a CANCELLED run's envelope does not say which steps already completed (§12: their side effects
happened, so they are listed)."""
def apply():
    import dataclasses
    from engine.stages.s15_final_state import response
    original = response.build_envelope

    def build_envelope(summary):
        env = original(summary)
        if summary.run_status == "cancelled" and env.error is not None:
            env = dataclasses.replace(env, error=dataclasses.replace(env.error, details={}))
        return env
    response.build_envelope = build_envelope
