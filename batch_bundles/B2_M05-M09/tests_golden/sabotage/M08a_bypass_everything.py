"""M8a sabotage: the admin bypass also lets through workspace, capability and mutation-ceiling failures."""
def apply():
    import dataclasses
    import engine.stages.s12_execute.eligibility as e
    original = e.filter_workers

    def filter_workers(candidates, ctx):
        result = original(candidates, ctx)
        if not ctx.admin:
            return result
        back = tuple(w for w in candidates if w.worker_id in result.removed)
        return dataclasses.replace(result, eligible=tuple(result.eligible) + back, removed={},
                                   bypassed=tuple(result.bypassed) + tuple((w.worker_id, r) for w in back
                                                                           for r in [result.removed[w.worker_id]]))
    e.filter_workers = filter_workers
