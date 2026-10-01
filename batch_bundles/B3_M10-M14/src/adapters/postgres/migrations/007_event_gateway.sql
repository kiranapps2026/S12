-- Event Gateway (S0 event-driven mode): signing secrets and the durable event log.
-- Follows DATABASE.md "Event Gateway Tables" with the deviations listed in
-- docs/proposals/S0_EVENT_DRIVEN_MODE.md (needs an owner ruling):
--   * webhook_credentials also carries the identity events run as (like api_keys) and a stable
--     `endpoint_id` (the public part of the webhook URL; it survives secret rotation);
--   * event_log stores the raw payload itself (`payload`) and uses TIMESTAMPTZ.

CREATE TABLE webhook_credentials (
    credential_id     TEXT PRIMARY KEY,
    endpoint_id       TEXT NOT NULL,
    tenant_id         TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    user_id           TEXT NOT NULL REFERENCES users(user_id),
    membership_id     TEXT NOT NULL REFERENCES memberships(membership_id),
    connection_id     TEXT NOT NULL REFERENCES connections(connection_id),
    resource_scope    TEXT NOT NULL DEFAULT '',
    source_system     TEXT NOT NULL CHECK (source_system IN ('ghl','stripe','custom','mcp')),
    secret_ciphertext BYTEA NOT NULL,       -- AES-256-GCM(secret) under the per-record DEK
    secret_nonce      BYTEA NOT NULL,       -- 96-bit GCM nonce
    wrapped_dek       BYTEA NOT NULL,       -- nonce || AES-256-GCM(DEK) under the KEK (never stored here)
    kek_version       INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retiring','retired')),
    retiring_until    TIMESTAMPTZ,
    algorithm         TEXT NOT NULL DEFAULT 'hmac-sha256' CHECK (algorithm IN ('hmac-sha256')),
    last_verified_at  TIMESTAMPTZ,
    expires_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status <> 'retiring' OR retiring_until IS NOT NULL)
);
CREATE UNIQUE INDEX uq_webhook_credentials_active
    ON webhook_credentials (endpoint_id, source_system) WHERE status = 'active';
CREATE UNIQUE INDEX uq_webhook_credentials_retiring
    ON webhook_credentials (endpoint_id, source_system) WHERE status = 'retiring';
CREATE INDEX idx_webhook_credentials_endpoint ON webhook_credentials (endpoint_id);

CREATE TABLE event_log (
    event_id           TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id       TEXT NOT NULL REFERENCES workspaces(workspace_id),
    event_type         TEXT NOT NULL,
    source             TEXT NOT NULL CHECK (source IN ('webhook','schedule','mcp','api','internal')),
    source_system      TEXT NOT NULL,
    payload            BYTEA NOT NULL,
    payload_ref        TEXT NOT NULL,
    payload_checksum   TEXT NOT NULL,
    correlation_id     TEXT NOT NULL,
    idempotency_key    TEXT NOT NULL,
    auth_method        TEXT NOT NULL,
    auth_principal     TEXT NOT NULL,
    processing_status  TEXT NOT NULL DEFAULT 'received'
                       CHECK (processing_status IN ('received','validated','deduplicated','routed',
                                                    'processed','dropped','failed','closed')),
    received_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_event_log_tenant_idempotency ON event_log (tenant_id, idempotency_key);

ALTER TABLE event_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_log FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON event_log
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
