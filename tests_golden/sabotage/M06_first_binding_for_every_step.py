"""M6 sabotage: every step row copies the first step's binding (G3 violated; I10 must catch it)."""
def apply():
    import adapters.postgres.admission as a
    original = a._step_bindings

    def _step_bindings(state):
        per_step, distinct = original(state)
        return (per_step[0],) * len(per_step), distinct
    a._step_bindings = _step_bindings
