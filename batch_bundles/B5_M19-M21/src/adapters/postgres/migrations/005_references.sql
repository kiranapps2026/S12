-- Sources for S1 reference resolution ($ref, $file, {{template}}). Read by the application role;
-- written by the stages/APIs that produce results and files. Tenant tables: forced RLS.

CREATE TABLE conversation_results (
    result_id        BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id          TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    summary          TEXT NOT NULL CHECK (length(summary) <= 4000),   -- text form of a result
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_results_lookup ON conversation_results (tenant_id, user_id, conversation_id, result_id DESC);

CREATE TABLE files (
    file_id       TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id  TEXT NOT NULL REFERENCES workspaces(workspace_id),
    name          TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    mime          TEXT NOT NULL,
    size_bytes    BIGINT NOT NULL CHECK (size_bytes >= 0),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, workspace_id, name)
);

CREATE TABLE template_variables (
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id  TEXT REFERENCES workspaces(workspace_id),          -- NULL: tenant-wide
    name          TEXT NOT NULL CHECK (name ~ '^[A-Za-z_][A-Za-z0-9_.]{0,63}$'),
    value         TEXT NOT NULL CHECK (length(value) <= 500)
);
CREATE UNIQUE INDEX idx_template_variables ON template_variables (tenant_id, COALESCE(workspace_id, ''), name);

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['conversation_results','files','template_variables'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;
