"""M4 sabotage: an expired lease can be renewed (C26: never)."""
def apply():
    import engine.stages.s12_execute.transitions as t
    original = t.validate

    def validate(machine, from_state, to_state, *, reason, closed=False):
        if machine == "lease" and (from_state, to_state) == ("expired", "active"):
            return None
        return original(machine, from_state, to_state, reason=reason, closed=closed)
    t.validate = validate
