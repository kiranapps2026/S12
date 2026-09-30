"""M15 sabotage: mutations are never observed at the provider, so the adapter's self-report decides (WORKER_LIFECYCLE
§6: a worker's claim is not evidence; FINAL_ARCHITECTURE §43: provider_state for W, D, IRREVERSIBLE)."""
def apply():
    from engine.stages.s13_reconciliation import verification
    original = verification.required_verification_layers

    def required_verification_layers(mutation, risk):
        return tuple(x for x in original(mutation, risk) if x != "provider_state")
    verification.required_verification_layers = required_verification_layers
