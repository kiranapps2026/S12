-- Onboarding, usage metering and rate limiting.
--   invitations         one-time invitation tokens (only the SHA-256 is stored). Looked up BEFORE the tenant is known, like
--                       api_keys: no row-level security; every administrative query filters by tenant explicitly.
--   llm_usage           one row per language-model call (tokens), tenant table with forced RLS.
--   rate_limit_counters one row per bucket, fixed window; counters only, no tenant data, no row-level security. The
--                       application role may not DELETE, so a window is reset in place instead of rows being purged.

CREATE TABLE invitations (
    invitation_id     TEXT PRIMARY KEY,
    token_hash        TEXT NOT NULL UNIQUE,
    tenant_id         TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    role              TEXT NOT NULL CHECK (role IN ('owner','admin','member','viewer')),
    label             TEXT,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL,
    revoked_at        TIMESTAMPTZ,
    accepted_at       TIMESTAMPTZ,
    accepted_user_id  TEXT REFERENCES users(user_id)
);
CREATE INDEX idx_invitations_tenant ON invitations (tenant_id, created_at DESC);

CREATE TABLE llm_usage (
    usage_id      BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id       TEXT NOT NULL,
    request_id    TEXT NOT NULL,
    model         TEXT NOT NULL,
    total_tokens  INTEGER NOT NULL CHECK (total_tokens >= 0),
    called_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_usage_tenant_time ON llm_usage (tenant_id, called_at DESC);
ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_usage FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON llm_usage
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE TABLE rate_limit_counters (
    bucket        TEXT PRIMARY KEY,
    window_start  TIMESTAMPTZ NOT NULL,
    hits          INTEGER NOT NULL
);
