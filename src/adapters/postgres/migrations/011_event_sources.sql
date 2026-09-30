-- Event sources beyond signed webhooks (Phase C): registered payload schemas and schedules.
-- Decisions: docs/proposals/EVENT_SOURCES.md (rulings R-BB..R-BG).

-- Payload schemas per (tenant, source system, event type): an event type must be REGISTERED, and its
-- payload must satisfy the newest active schema (a small JSON-Schema subset, engine/gateway/schema.py).
CREATE TABLE event_schemas (
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    source_system   TEXT NOT NULL,
    event_type      TEXT NOT NULL CHECK (event_type ~ '^[A-Za-z0-9_.:-]{1,64}$'),
    schema_version  INTEGER NOT NULL CHECK (schema_version >= 1),
    schema          JSONB NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source_system, event_type, schema_version)
);
ALTER TABLE event_schemas ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_schemas FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON event_schemas
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

ALTER TABLE event_log ADD COLUMN schema_version TEXT NOT NULL DEFAULT '1';

-- Schedules. A SYSTEM table (no row-level security): the scheduler lists every tenant's active
-- schedules, exactly like webhook_credentials it is read before any tenant is known. It holds the
-- fixed identity a scheduled event runs as (a service user) and nothing secret.
CREATE TABLE event_schedules (
    schedule_id       TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    user_id           TEXT NOT NULL REFERENCES users(user_id),
    membership_id     TEXT NOT NULL REFERENCES memberships(membership_id),
    connection_id     TEXT NOT NULL REFERENCES connections(connection_id),
    resource_scope    TEXT NOT NULL DEFAULT '',
    event_type        TEXT NOT NULL CHECK (event_type ~ '^[A-Za-z0-9_.:-]{1,64}$'),
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    kind              TEXT NOT NULL CHECK (kind IN ('interval','daily','weekly')),
    anchor            TIMESTAMPTZ,
    interval_seconds  INTEGER CHECK (interval_seconds IS NULL OR interval_seconds >= 60),
    at_seconds        INTEGER CHECK (at_seconds IS NULL OR (at_seconds >= 0 AND at_seconds < 86400)),
    weekday           INTEGER CHECK (weekday IS NULL OR (weekday BETWEEN 1 AND 7)),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    last_planned      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((kind = 'interval' AND anchor IS NOT NULL AND interval_seconds IS NOT NULL)
        OR (kind = 'daily' AND at_seconds IS NOT NULL)
        OR (kind = 'weekly' AND at_seconds IS NOT NULL AND weekday IS NOT NULL))
);
CREATE INDEX idx_event_schedules_active ON event_schedules (is_active) WHERE is_active;
