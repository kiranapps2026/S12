-- API keys for the HTTP entry point. Looked up BEFORE the tenant is known (pre-tenant, like
-- webhook_credentials), so this table has no RLS: it holds only SHA-256 hashes of random
-- 256-bit keys and the fixed identity each key maps to. The key itself is never stored.
CREATE TABLE api_keys (
    key_id          TEXT PRIMARY KEY,
    key_hash        TEXT NOT NULL UNIQUE,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id    TEXT NOT NULL REFERENCES workspaces(workspace_id),
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    membership_id   TEXT NOT NULL REFERENCES memberships(membership_id),
    connection_id   TEXT NOT NULL REFERENCES connections(connection_id),
    resource_scope  TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
