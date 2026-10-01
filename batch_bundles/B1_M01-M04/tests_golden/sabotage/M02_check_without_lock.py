"""M2 sabotage: the fence is checked with a plain read, so a takeover can commit between check and write."""
def apply():
    import adapters.postgres.fencing as f
    from contracts.step_execution import FencedOut

    async def fenced_write(database, holder, write):
        async with database.tenant_transaction(holder.tenant_id) as connection:
            ok = await connection.fetchval(
                "SELECT count(*) FROM execution_ownership WHERE execution_id = $1 AND tenant_id = $2"
                " AND fencing_token = $3 AND runtime_instance_id = $4",
                holder.execution_id, holder.tenant_id, holder.fence_token, holder.runtime_instance_id)
            if not ok:
                raise FencedOut(holder.execution_id)
            return await write(connection)
    f.fenced_write = fenced_write
