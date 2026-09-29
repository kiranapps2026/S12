-- Durable admission for S12 (gate §7.2/§7.3, DATABASE.md "S12–S15 Additive Tables").
-- Every table is tenant-scoped with forced row-level security. Deviations from DATABASE.md, listed in
-- docs/proposals/S12_MULTI_STEP.md (they need the gate owner's ruling):
--   * times are TIMESTAMPTZ, not REAL (as in every other table of this schema);
--   * execution_plans stores the array of frozen bindings and the step->binding index (G4);
--   * no foreign keys to workers / worker_leases / worker_versions (those tables do not exist yet) and
--     no budget_reservations -> execution_runs/steps foreign keys (S12's reserve step adds them);
--   * operation_quotas has no worker_id column (worker-level quotas are out of phase, the CHECK made it NULL).

CREATE TABLE execution_runs (
    execution_id          TEXT PRIMARY KEY,
    request_id            TEXT NOT NULL,
    trace_id              TEXT NOT NULL,
    task_id               TEXT NOT NULL,
    user_id               TEXT NOT NULL REFERENCES users(user_id),
    tenant_id             TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id          TEXT NOT NULL REFERENCES workspaces(workspace_id),
    conversation_id       TEXT NOT NULL,
    plan_id               TEXT,
    status                TEXT NOT NULL CHECK (status IN ('pending','running','reconciling','completed',
                                                          'partial','failed','cancelled','dead_letter')),
    actor_type            TEXT NOT NULL DEFAULT 'user' CHECK (actor_type IN ('user','worker','system')),
    actor_id              TEXT NOT NULL,
    consolidation         TEXT,
    budget_spent          INTEGER NOT NULL DEFAULT 0,
    duration_ms           INTEGER,
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancel_requested_at   TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_execution_runs_request ON execution_runs (tenant_id, request_id);
CREATE INDEX idx_execution_runs_trace ON execution_runs (trace_id);
CREATE INDEX idx_execution_runs_status ON execution_runs (tenant_id, status);

CREATE TABLE execution_steps (
    step_id              TEXT PRIMARY KEY,                 -- "{execution_id}:{plan_step_id}"
    plan_step_id         TEXT NOT NULL,
    execution_id         TEXT NOT NULL REFERENCES execution_runs(execution_id),
    tenant_id            TEXT NOT NULL REFERENCES tenants(tenant_id),
    plan_id              TEXT,
    kernel_op_id         TEXT NOT NULL,
    resolved_binding_id  TEXT NOT NULL,
    effective_risk       DOUBLE PRECISION NOT NULL CHECK (effective_risk BETWEEN 0 AND 1),
    effective_mutation   TEXT NOT NULL CHECK (effective_mutation IN ('R','W','D','IRREVERSIBLE')),
    request_fingerprint  TEXT NOT NULL,
    reservation_id       TEXT REFERENCES budget_reservations(reservation_id),
    status               TEXT NOT NULL CHECK (status IN ('pending','running','completed','partial','failed',
                                              'cancelled','skipped','timeout','unknown','pending_probe',
                                              'dead_letter')),
    data                 TEXT,
    error                TEXT,
    attempt              INTEGER NOT NULL DEFAULT 1,
    undo_token           TEXT,
    duration_ms          INTEGER,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (execution_id, plan_step_id)
);
CREATE INDEX idx_execution_steps_execution ON execution_steps (execution_id);

CREATE TABLE execution_manifests (
    execution_id           TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    tenant_id              TEXT NOT NULL REFERENCES tenants(tenant_id),
    trace_id               TEXT NOT NULL,
    plan_hash              TEXT NOT NULL,
    capability_version     TEXT NOT NULL,
    binding_version        TEXT NOT NULL,
    policy_version         TEXT NOT NULL,
    risk_policy_version    TEXT NOT NULL,
    authorization_version  TEXT NOT NULL,
    auth_result_id         TEXT,
    worker_runtime_version TEXT NOT NULL,
    model_version          TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL
);

CREATE TABLE execution_plans (
    execution_id           TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    tenant_id              TEXT NOT NULL REFERENCES tenants(tenant_id),
    plan_hash              TEXT NOT NULL,
    canonical_plan         JSONB NOT NULL,
    frozen_bindings        JSONB NOT NULL,                 -- array, one entry per distinct binding
    step_binding_index     JSONB NOT NULL,                 -- plan step id -> index into frozen_bindings
    verifiers              JSONB NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE execution_ownership (
    execution_id           TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    tenant_id              TEXT NOT NULL REFERENCES tenants(tenant_id),
    worker_id              TEXT,
    runtime_instance_id    TEXT NOT NULL,
    lease_id               TEXT,
    fencing_token          BIGINT NOT NULL DEFAULT 0,
    checkpoint_sequence    INTEGER NOT NULL DEFAULT 0,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE state_transitions (
    transition_id          BIGSERIAL PRIMARY KEY,
    tenant_id              TEXT NOT NULL REFERENCES tenants(tenant_id),
    entity_type            TEXT NOT NULL CHECK (entity_type IN ('run','step')),
    entity_id              TEXT NOT NULL,
    from_state             TEXT,
    to_state               TEXT NOT NULL,
    reason                 TEXT,
    runtime_instance_id    TEXT,
    fence_token            BIGINT,
    occurred_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_state_transitions_entity ON state_transitions (entity_type, entity_id);

CREATE TABLE operation_quotas (
    quota_id       TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id   TEXT REFERENCES workspaces(workspace_id),          -- NULL = tenant level
    resource_type  TEXT NOT NULL DEFAULT 'executions' CHECK (resource_type IN ('executions')),
    period_start   TIMESTAMPTZ NOT NULL,
    period_end     TIMESTAMPTZ NOT NULL,
    limit_value    INTEGER NOT NULL,
    used_count     INTEGER NOT NULL DEFAULT 0,
    is_hard        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (used_count >= 0 AND limit_value >= 0),
    CHECK (used_count <= limit_value),
    CHECK (period_end > period_start),
    UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, resource_type, period_start)
);
CREATE INDEX idx_quotas_lookup ON operation_quotas (tenant_id, resource_type, period_start, period_end);

-- The manifest and the plan are frozen at admission: never updated.
CREATE FUNCTION reject_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% is immutable', TG_TABLE_NAME; END $$;
CREATE TRIGGER execution_manifests_immutable BEFORE UPDATE ON execution_manifests
    FOR EACH ROW EXECUTE FUNCTION reject_update();
CREATE TRIGGER execution_plans_immutable BEFORE UPDATE ON execution_plans
    FOR EACH ROW EXECUTE FUNCTION reject_update();

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['execution_runs','execution_steps','execution_manifests','execution_plans',
                             'execution_ownership','state_transitions','operation_quotas'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;
