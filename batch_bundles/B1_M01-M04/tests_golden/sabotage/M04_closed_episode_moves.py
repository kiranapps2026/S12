"""M4 sabotage: a closed episode can still transition (closed_at ignored)."""
def apply():
    import engine.stages.s12_execute.transitions as t
    original = t.validate

    def validate(machine, from_state, to_state, *, reason, closed=False):
        return original(machine, from_state, to_state, reason=reason, closed=False)
    t.validate = validate
