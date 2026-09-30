"""M11 sabotage: IRREVERSIBLE and non-idempotent steps get the read ceiling (MUTATION_SAFETY §3: never retried)."""
def apply():
    import engine.stages.s12_execute.retry_policy as policy

    def ceiling(mutation, retry_safety):
        return 3
    policy.ceiling = ceiling
