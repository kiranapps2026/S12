"""M18 sabotage: the summary names each step by its internal step id (§12: no internal id other than trace_id)."""
def apply():
    import dataclasses
    from adapters.postgres.run_summary import PostgresRunSummaries
    original = PostgresRunSummaries.load

    async def load(self, tenant_id, execution_id):
        summary = await original(self, tenant_id, execution_id)
        if summary is None:
            return None
        steps = tuple(dataclasses.replace(s, operation=f"{execution_id}:{s.operation}") for s in summary.steps)
        return dataclasses.replace(summary, steps=steps)
    PostgresRunSummaries.load = load
