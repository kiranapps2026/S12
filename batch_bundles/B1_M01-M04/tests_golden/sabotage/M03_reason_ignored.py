"""M3 sabotage: guarded edges accept any reason (only the pair is checked)."""
def apply():
    import engine.stages.s12_execute.transitions as t
    original = t.validate

    def validate(machine, from_state, to_state, *, reason, closed=False):
        try:
            return original(machine, from_state, to_state, reason=reason, closed=closed)
        except t.IllegalStateTransition:
            for probe in ("admitted", "started", "reserved", "created", "step_started", "consolidated", "verified"):
                try:
                    return original(machine, from_state, to_state, reason=probe, closed=closed)
                except t.IllegalStateTransition:
                    pass
            raise
    t.validate = validate
