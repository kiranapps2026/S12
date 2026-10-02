"""M19 sabotage (CONF-050, D-10): recovery never sees a recorded FAIL, so after a crash it re-runs the failed layer and
a non-retryable FAIL can turn into PASS (§8 step 9)."""
def apply():
    from adapters.postgres.execution_events import PostgresExecutionEvents
    original = PostgresExecutionEvents.layer_verdicts

    async def layer_verdicts(self, tenant_id, step_id):
        return {layer: verdict for layer, verdict in (await original(self, tenant_id, step_id)).items()
                if verdict != "FAIL"}
    PostgresExecutionEvents.layer_verdicts = layer_verdicts
