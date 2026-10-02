"""M8a sabotage: a legacy worker with NULL workspace_id (or another workspace) counts as a match (filter 4b)."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.eligibility as e
    original = e.filter_workers

    def filter_workers(candidates, ctx):
        return original([dataclasses.replace(w, workspace_id=ctx.workspace_id) for w in candidates], ctx)
    e.filter_workers = filter_workers
