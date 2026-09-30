"""M6 sabotage: the run is written before the entry checks decide (a denied run leaves rows behind)."""
def apply():
    import engine.stages.s12_entry.admission as a
    from contracts.admission import DENIED, AdmissionOutcome

    async def admit_run(state, *, bindings, activation, metadata, admitter, runtime_instance_id, confirmations=None):
        try:
            outcome = await admitter.admit(state, (), runtime_instance_id)
        except Exception:
            return AdmissionOutcome(DENIED, reason="admission_unavailable")
        decision = await a.check_entry(state, bindings=bindings, activation=activation, metadata=metadata,
                                       **({"confirmations": confirmations} if confirmations is not None else {}))
        return outcome if decision.allowed else AdmissionOutcome(DENIED, reason=decision.reason)
    a.admit_run = admit_run
