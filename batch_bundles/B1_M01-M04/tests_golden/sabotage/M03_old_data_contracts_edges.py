"""M3 sabotage: the pre-v9 DATA_CONTRACTS edges (TIMEOUT -> DEAD_LETTER, UNKNOWN -> FAILED)."""
def apply():
    import engine.stages.s12_execute.transitions as t
    original = t.validate

    def validate(machine, from_state, to_state, *, reason, closed=False):
        if machine == "step" and (from_state, to_state) in {("timeout", "dead_letter"), ("unknown", "failed")}:
            return None
        return original(machine, from_state, to_state, reason=reason, closed=closed)
    t.validate = validate
