-- Admin API (Phase B4): labels and authorship on what an administrator creates, revocation time for API keys,
-- and an append-only audit trail of every administrative action (no secrets, ever).

ALTER TABLE api_keys            ADD COLUMN label TEXT, ADD COLUMN created_by TEXT, ADD COLUMN revoked_at TIMESTAMPTZ;
ALTER TABLE webhook_credentials ADD COLUMN label TEXT, ADD COLUMN created_by TEXT;
ALTER TABLE event_schemas       ADD COLUMN created_by TEXT;
ALTER TABLE event_schedules     ADD COLUMN label TEXT, ADD COLUMN created_by TEXT;

CREATE TABLE admin_audit (
    audit_id             BIGSERIAL PRIMARY KEY,
    tenant_id            TEXT NOT NULL REFERENCES tenants(tenant_id),
    actor_user_id        TEXT NOT NULL,
    actor_membership_id  TEXT NOT NULL,
    action               TEXT NOT NULL,          -- e.g. api_key.issue, endpoint.rotate, event_schema.put
    target_type          TEXT NOT NULL,
    target_id            TEXT NOT NULL,
    details              JSONB NOT NULL DEFAULT '{}'::jsonb,   -- ids, versions and labels only; never a secret
    occurred_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_admin_audit_tenant ON admin_audit (tenant_id, audit_id DESC);

CREATE FUNCTION reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END $$;
CREATE TRIGGER admin_audit_append_only BEFORE UPDATE OR DELETE ON admin_audit
    FOR EACH ROW EXECUTE FUNCTION reject_change();

ALTER TABLE admin_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON admin_audit
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
