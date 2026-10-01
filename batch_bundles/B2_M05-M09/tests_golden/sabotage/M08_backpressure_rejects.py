"""M8 sabotage: backpressure (gates 9 and 11) rejects the step instead of delaying it (CONF-017)."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.admission_control as ac
    original = ac.evaluate

    def evaluate(snapshot):
        d = original(snapshot)
        return dataclasses.replace(d, status="REJECT", retry_after_ms=None) if d.status == "DELAY" else d
    ac.evaluate = evaluate
