-- Internal LLM consumption (PIPELINE_STAGES §4 [BILLING]): one row per S2 model call.
CREATE TABLE llm_usage (
    usage_id       BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id        TEXT NOT NULL,
    trace_id       TEXT NOT NULL,
    resource_type  TEXT NOT NULL,
    quantity       INTEGER NOT NULL CHECK (quantity >= 0),
    unit           TEXT NOT NULL,
    kernel_op_ref  TEXT NOT NULL,
    model          TEXT NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_usage_tenant ON llm_usage (tenant_id, recorded_at);

ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_usage FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON llm_usage
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
