"""M8a sabotage: the assignment filter (14) is applied to event-driven and system runs too."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.eligibility as e
    original = e.filter_workers

    def filter_workers(candidates, ctx):
        return original(candidates, dataclasses.replace(ctx, event_driven=False, principal_is_human=True))
    e.filter_workers = filter_workers
