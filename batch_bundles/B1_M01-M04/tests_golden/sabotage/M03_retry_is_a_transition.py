"""M3 sabotage: a retry is logged as RUNNING -> RUNNING (C24 forbids)."""
def apply():
    import engine.stages.s12_execute.transitions as t
    original = t.validate

    def validate(machine, from_state, to_state, *, reason, closed=False):
        if machine == "step" and from_state == to_state == "running":
            return None
        return original(machine, from_state, to_state, reason=reason, closed=closed)
    t.validate = validate
