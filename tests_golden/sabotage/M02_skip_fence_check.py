"""M2 sabotage: fenced_write writes without checking the fence."""
def apply():
    import adapters.postgres.fencing as f

    async def fenced_write(database, holder, write):
        async with database.tenant_transaction(holder.tenant_id) as connection:
            return await write(connection)
    f.fenced_write = fenced_write
