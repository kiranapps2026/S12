-- S0–S11 schema (DATABASE.md names; valid PostgreSQL 16 types).
-- Tenant tables use row-level security keyed on app.current_tenant, which every
-- adapter sets per transaction. The application role must not be a superuser and
-- must not own these tables, or RLS is bypassed.

CREATE TABLE system_settings (
    singleton            BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    kill_switch_engaged  BOOLEAN NOT NULL DEFAULT FALSE,
    risk_deny_threshold  DOUBLE PRECISION NOT NULL DEFAULT 0.95
                         CHECK (risk_deny_threshold > 0 AND risk_deny_threshold <= 1)
);
INSERT INTO system_settings DEFAULT VALUES;

CREATE TABLE tenants (
    tenant_id                TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active','inactive','suspended','deactivated','revoked','deleted')),
    budget_pool              INTEGER NOT NULL DEFAULT 10000 CHECK (budget_pool >= 0),
    kill_switch_engaged      BOOLEAN NOT NULL DEFAULT FALSE,
    max_mutation             TEXT NOT NULL DEFAULT 'W' CHECK (max_mutation IN ('R','W','D','IRREVERSIBLE')),
    policy_version_id        TEXT NOT NULL,
    paused_until             TIMESTAMPTZ,
    scheduled_activation_at  TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
    workspace_id             TEXT PRIMARY KEY,
    tenant_id                TEXT NOT NULL REFERENCES tenants(tenant_id),
    name                     TEXT NOT NULL,
    policy_version_id        TEXT,            -- NULL: the tenant's version applies
    paused_until             TIMESTAMPTZ,
    scheduled_activation_at  TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    user_id     TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','inactive','suspended','deactivated','revoked','deleted')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    membership_id  TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    workspace_id   TEXT NOT NULL REFERENCES workspaces(workspace_id),
    role           TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner','admin','member','viewer')),
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    revoked_at     TIMESTAMPTZ,
    UNIQUE (tenant_id, user_id, workspace_id)
);

CREATE TABLE connections (
    connection_id  TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    workspace_id   TEXT NOT NULL REFERENCES workspaces(workspace_id),
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active','inactive','suspended','deactivated','revoked','deleted')),
    expires_at     TIMESTAMPTZ
);

-- Global registry (provider-neutral; no tenant data).
CREATE TABLE capabilities (
    capability_id  TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    intent         TEXT NOT NULL,
    mutation       TEXT NOT NULL CHECK (mutation IN ('R','W','D','IRREVERSIBLE')),
    risk_floor     DOUBLE PRECISION NOT NULL CHECK (risk_floor BETWEEN 0 AND 1),
    risk_rule      DOUBLE PRECISION NOT NULL CHECK (risk_rule BETWEEN 0 AND 1),
    risk_implied   DOUBLE PRECISION NOT NULL CHECK (risk_implied BETWEEN 0 AND 1),
    truth_state    TEXT NOT NULL CHECK (truth_state IN ('DRAFT','REVIEW','PRODUCTION_ENABLED','DEPRECATED'))
);
CREATE INDEX idx_capabilities_intent ON capabilities (intent);

CREATE TABLE kernel_ops (
    kernel_op_id     TEXT PRIMARY KEY,
    mutation         TEXT NOT NULL CHECK (mutation IN ('R','W','D','IRREVERSIBLE')),
    risk_floor       DOUBLE PRECISION NOT NULL CHECK (risk_floor BETWEEN 0 AND 1),
    cost             INTEGER NOT NULL CHECK (cost > 0),
    timeout_seconds  INTEGER NOT NULL CHECK (timeout_seconds > 0),
    retry_safety     TEXT NOT NULL CHECK (retry_safety IN ('safe','idempotent','never')),
    truth_state      TEXT NOT NULL CHECK (truth_state IN ('DRAFT','REVIEW','PRODUCTION_ENABLED','DEPRECATED')),
    inverse          TEXT REFERENCES kernel_ops(kernel_op_id)
);

CREATE TABLE bindings (
    binding_id     TEXT PRIMARY KEY,
    capability_id  TEXT NOT NULL REFERENCES capabilities(capability_id),
    kernel_op_id   TEXT NOT NULL REFERENCES kernel_ops(kernel_op_id),
    provider       TEXT NOT NULL,
    engine_module  TEXT NOT NULL,
    adapter_class  TEXT NOT NULL,
    priority       INTEGER NOT NULL DEFAULT 1,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bindings_capability ON bindings (capability_id);

CREATE TABLE registry_versions (
    singleton               BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    capability_version      TEXT NOT NULL,
    binding_version         TEXT NOT NULL,
    risk_policy_version     TEXT NOT NULL,
    authorization_version   TEXT NOT NULL,
    worker_runtime_version  TEXT NOT NULL,
    model_version           TEXT NOT NULL
);

CREATE TABLE capability_grants (
    capability_grant_id  TEXT PRIMARY KEY,
    tenant_id            TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id         TEXT NOT NULL REFERENCES workspaces(workspace_id),
    user_id              TEXT NOT NULL REFERENCES users(user_id),
    capability_id        TEXT NOT NULL REFERENCES capabilities(capability_id),
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at           TIMESTAMPTZ
);
CREATE INDEX idx_grants_lookup ON capability_grants (tenant_id, user_id, capability_id);

CREATE TABLE pending_confirmations (
    confirmation_id  TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
    execution_id     TEXT NOT NULL CHECK (execution_id <> ''),
    user_id          TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    plan_id          TEXT NOT NULL,
    plan_hash        TEXT NOT NULL,
    operations       JSONB NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','consumed','rejected','expired')),
    expires_at       TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at      TIMESTAMPTZ
);
CREATE INDEX idx_confirmations_execution ON pending_confirmations (tenant_id, execution_id);

-- Row-level security on every tenant table (I-001).
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['tenants','workspaces','users','memberships','connections',
                             'capability_grants','pending_confirmations'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;
