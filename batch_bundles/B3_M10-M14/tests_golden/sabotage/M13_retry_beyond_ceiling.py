"""M13 sabotage: a NOT_EXECUTED step is retried whatever its ceiling (§9: IRREVERSIBLE and non-idempotent D never)."""
def apply():
    import engine.stages.s12_execute.retry_policy as policy

    def max_attempts(mutation, retry_safety, step_max=None):
        return 5
    policy.max_attempts = max_attempts
