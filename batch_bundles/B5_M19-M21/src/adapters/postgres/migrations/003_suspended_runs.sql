-- Runs suspended at S10, stored as JSON (never pickle) so a reply can resume them after a restart.
CREATE TABLE suspended_runs (
    confirmation_id  TEXT PRIMARY KEY REFERENCES pending_confirmations(confirmation_id),
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
    execution_id     TEXT NOT NULL,
    state            JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_suspended_runs_execution ON suspended_runs (tenant_id, execution_id);

ALTER TABLE suspended_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE suspended_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON suspended_runs
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
