"""M5 sabotage: the C20 check forgets the execution_id (a confirmation for another run is accepted)."""
def apply():
    import engine.stages.s12_entry.confirmation as c
    original = c.confirmation_denial

    async def confirmation_denial(state, reader):
        if reader is not None and state.confirmation is not None and state.confirmation.required:
            class SameExecution:
                async def read(self, confirmation_id, *, tenant_id):
                    import dataclasses
                    row = await reader.read(confirmation_id, tenant_id=tenant_id)
                    return None if row is None else dataclasses.replace(row, execution_id=state.plan.execution_id)
            return await original(state, SameExecution())
        return await original(state, reader)
    c.confirmation_denial = confirmation_denial
