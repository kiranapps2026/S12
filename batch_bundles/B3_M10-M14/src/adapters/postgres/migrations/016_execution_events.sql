-- The execution ledger (FINAL_ARCHITECTURE §40 LedgerEvent; gate C17, C24, C30, C35/I16, §21 S5; ruling CONF-026).
-- Append-only: no UPDATE and no DELETE, for any role. Ordered by seq.
CREATE TABLE execution_events (
    seq                  BIGSERIAL PRIMARY KEY,
    event_id             TEXT NOT NULL UNIQUE,
    tenant_id            TEXT NOT NULL REFERENCES tenants(tenant_id),
    execution_id         TEXT REFERENCES execution_runs(execution_id),
    trace_id             TEXT NOT NULL,
    event_type           TEXT NOT NULL,
    step_id              TEXT,
    attempt_id           TEXT,
    provider_call_id     TEXT,
    runtime_instance_id  TEXT,
    fence_token          BIGINT,
    payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_execution_events_execution ON execution_events (tenant_id, execution_id, seq);

CREATE TRIGGER execution_events_no_update BEFORE UPDATE ON execution_events
    FOR EACH ROW EXECUTE FUNCTION reject_update();
CREATE TRIGGER execution_events_no_delete BEFORE DELETE ON execution_events
    FOR EACH ROW EXECUTE FUNCTION reject_update();

ALTER TABLE execution_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON execution_events
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
