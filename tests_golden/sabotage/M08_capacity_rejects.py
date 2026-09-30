"""M8 sabotage: worker capacity rejects instead of queueing (C30: gate 7 is a QUEUE, never a REJECT)."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.admission_control as ac
    original = ac.evaluate

    def evaluate(snapshot):
        d = original(snapshot)
        return dataclasses.replace(d, status="REJECT", retry_after_ms=None) if d.gate_failed == "7" else d
    ac.evaluate = evaluate
