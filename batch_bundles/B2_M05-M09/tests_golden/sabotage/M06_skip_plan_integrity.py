"""M6 sabotage: the plan digest is not recomputed at entry (a plan changed after S11 is admitted)."""
def apply():
    import dataclasses
    import engine.stages.s12_entry.checks as c
    from contracts.plan_hash import canonical_plan_digest
    original = c.check_entry

    async def check_entry(state, **readers):
        if state.plan is not None and state.execution_manifest is not None:
            digest = canonical_plan_digest(state.plan.plan)
            state = dataclasses.replace(state, plan=dataclasses.replace(state.plan, plan_hash=digest),
                                        execution_manifest=dataclasses.replace(state.execution_manifest, plan_hash=digest))
        return await original(state, **readers)
    c.check_entry = check_entry
    import engine.stages.s12_entry.admission as a
    a.check_entry = check_entry
