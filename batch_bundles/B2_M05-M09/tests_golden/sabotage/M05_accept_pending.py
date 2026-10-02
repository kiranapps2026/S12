"""M5 sabotage: a confirmation that was never consumed is accepted (status not checked)."""
def apply():
    import dataclasses
    import engine.stages.s12_entry.confirmation as c
    original = c.confirmation_denial

    async def confirmation_denial(state, reader):
        if reader is None:
            return await original(state, reader)

        class AlwaysConsumed:
            async def read(self, confirmation_id, *, tenant_id):
                row = await reader.read(confirmation_id, tenant_id=tenant_id)
                return None if row is None else dataclasses.replace(row, status="consumed")
        return await original(state, AlwaysConsumed())
    c.confirmation_denial = confirmation_denial
