-- S12–S15 schema (gate v10 §7.3, C16, C18, C20–C22, C25–C28, C33–C35, C39; ruling CONF-007, CONF-014).
-- Additive only: 001–014 are inside the s0-s11-certified tag and are never edited.
-- Every CHECK value list below is contracts.execution_states (or contracts.worker.WorkerStatus) .value, one source (C28);
-- tests_golden/s12/M01_schema.py compares each list with its enum.
-- Keys are TEXT (RD-1), times TIMESTAMPTZ in database time (C33), every table carries tenant_id under forced RLS (C34),
-- and no foreign key cascades (P1-H: execution history is retained).

-- Fence tokens for every lease acquisition and renewal: strictly increasing per worker and per execution (C25).
CREATE SEQUENCE fence_token_seq;

-- Workers (WORKER_LIFECYCLE §3, DATABASE workers + C39 management columns).
CREATE TABLE workers (
    worker_id                TEXT PRIMARY KEY,
    tenant_id                TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id             TEXT REFERENCES workspaces(workspace_id),   -- filter 4b; NULL only on legacy rows (ineligible)
    worker_class             TEXT NOT NULL,
    runtime_version          TEXT,
    capability_profile       JSONB NOT NULL,
    state                    TEXT NOT NULL DEFAULT 'REGISTERED'          -- WorkerStatus; canonical default (C33)
        CHECK (state IN ('REGISTERED', 'ACTIVE', 'DRAINING', 'DRAINED', 'TERMINATED')),
    capacity                 INTEGER NOT NULL DEFAULT 1 CHECK (capacity >= 1),
    current_load             INTEGER NOT NULL DEFAULT 0 CHECK (current_load >= 0),   -- = usable leases (C26)
    lease_epoch              BIGINT NOT NULL DEFAULT 0,                  -- newest token issued; never rejects a write (C25)
    heartbeat_at             TIMESTAMPTZ,
    last_assignment_at       TIMESTAMPTZ,
    drain_state              TEXT,
    settings                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    assigned_user_id         TEXT REFERENCES users(user_id),             -- filter 14; NULL = any user
    paused_until             TIMESTAMPTZ,                                -- filter 12b (not a state)
    scheduled_activation_at  TIMESTAMPTZ,                                -- filter 13b (not a state)
    runtime_type             TEXT NOT NULL DEFAULT 'llm'                 -- RuntimeType (filter 17)
        CHECK (runtime_type IN ('llm', 'rules', 'vision', 'browser', 'rpa', 'data', 'rag', 'code', 'human')),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (current_load <= capacity)
);
CREATE INDEX idx_workers_workspace ON workers (workspace_id);                -- CONF-014
CREATE INDEX idx_workers_tenant ON workers (tenant_id);

-- Leases of record (C5, C26). Usable only while status = 'active' AND expires_at > now().
CREATE TABLE worker_leases (
    lease_id      TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    worker_id     TEXT NOT NULL REFERENCES workers(worker_id),
    execution_id  TEXT REFERENCES execution_runs(execution_id),           -- diagnostics
    task_id       TEXT,
    fence_token   BIGINT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'                          -- LeaseStatus
        CHECK (status IN ('pending', 'active', 'expired', 'released')),
    expires_at    TIMESTAMPTZ NOT NULL,
    acquired_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at   TIMESTAMPTZ
);
CREATE INDEX idx_worker_leases_active ON worker_leases (worker_id) WHERE status = 'active';
CREATE INDEX idx_worker_leases_execution ON worker_leases (tenant_id, execution_id);

-- One record per uncertainty episode (C18, C19, C35); at most one open episode per step.
CREATE TABLE step_reconciliations (
    episode_id    TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    execution_id  TEXT NOT NULL REFERENCES execution_runs(execution_id),
    step_id       TEXT NOT NULL REFERENCES execution_steps(step_id),
    kind          TEXT NOT NULL CHECK (kind IN ('EXECUTION', 'VERIFICATION')),          -- ReconciliationKind
    status        TEXT NOT NULL                                                         -- ReconciliationStatus minus none
        CHECK (status IN ('pending_probe', 'reconciling', 'confirmed_success', 'confirmed_failure')),
    outcome       TEXT CHECK (outcome IN ('EXECUTED_SUCCESS', 'EXECUTED_FAILURE', 'NOT_EXECUTED', 'LEDGER_HIT',
                                          'VERIFIED_PASS', 'VERIFIED_FAIL', 'EXHAUSTED')),  -- ReconciliationOutcome
    evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempts      INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at     TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_step_reconciliations_open ON step_reconciliations (step_id) WHERE closed_at IS NULL;
CREATE INDEX idx_step_reconciliations_execution ON step_reconciliations (tenant_id, execution_id);

-- Dead letters (C21, C27, C29, D4, D5).
CREATE TABLE dead_letters (
    dead_letter_id      TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(tenant_id),
    execution_id        TEXT NOT NULL REFERENCES execution_runs(execution_id),
    step_id             TEXT NOT NULL REFERENCES execution_steps(step_id),
    kernel_op_id        TEXT NOT NULL,
    reservation_id      TEXT REFERENCES budget_reservations(reservation_id),
    attempt_id          TEXT,
    episode_id          TEXT REFERENCES step_reconciliations(episode_id),
    error               TEXT NOT NULL,
    error_type          TEXT NOT NULL                                           -- DeadLetterErrorType
        CHECK (error_type IN ('transient', 'permanent', 'data', 'unknown_unresolved')),
    mutation_type       TEXT NOT NULL DEFAULT 'R' CHECK (mutation_type IN ('R', 'W', 'D', 'IRREVERSIBLE')),
    is_idempotent       BOOLEAN NOT NULL DEFAULT FALSE,
    retry_count         INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries         INTEGER NOT NULL DEFAULT 3 CHECK (max_retries >= 0),
    next_retry_at       TIMESTAMPTZ,
    context             JSONB NOT NULL DEFAULT '{}'::jsonb,                     -- evidence; never credentials (S6)
    status              TEXT NOT NULL DEFAULT 'pending'                         -- DeadLetterStatus
        CHECK (status IN ('pending', 'retrying', 'resolved', 'abandoned')),
    resolved            BOOLEAN NOT NULL DEFAULT FALSE,
    retry_mode          TEXT NOT NULL CHECK (retry_mode IN ('PROBE', 'VERIFY', 'NONE')),          -- RetryMode
    resolution_outcome  TEXT CHECK (resolution_outcome IN ('EXECUTED', 'NOT_EXECUTED', 'UNDETERMINED')),  -- ResolutionOutcome
    origin              TEXT NOT NULL DEFAULT 'execution' CHECK (origin IN ('execution', 'rollback')),  -- DeadLetterOrigin
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- resolved is true exactly when status is resolved or abandoned; both need an outcome (C21)
    CONSTRAINT chk_dead_letters_resolved CHECK (resolved = (status IN ('resolved', 'abandoned'))),
    CONSTRAINT chk_dead_letters_outcome CHECK (status NOT IN ('resolved', 'abandoned') OR resolution_outcome IS NOT NULL),
    -- a rollback dead letter is never retried (C27)
    CONSTRAINT chk_dead_letters_rollback CHECK (origin <> 'rollback' OR retry_mode = 'NONE')
);
CREATE INDEX idx_dead_letters_execution ON dead_letters (tenant_id, execution_id);

-- Idempotency ledger (C9, C17, C34). Key = "{request_id}:{plan_step_id}". An expired record authorizes nothing.
CREATE TABLE idempotency_ledger (
    idempotency_key  TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
    kernel_op_id     TEXT NOT NULL,
    result           JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_idempotency_ledger_tenant_key ON idempotency_ledger (tenant_id, idempotency_key);

-- Checkpoints are rows, never files (C10). A hint only: database state is the truth on recovery. No context snapshot
-- (C33: recovery never restores ExecutionContext from a checkpoint).
CREATE TABLE checkpoints (
    checkpoint_id    TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
    execution_id     TEXT NOT NULL REFERENCES execution_runs(execution_id),
    sequence         INTEGER NOT NULL CHECK (sequence >= 0),
    completed_steps  JSONB NOT NULL DEFAULT '[]'::jsonb,
    failed_steps     JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending_steps    JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_step     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ,
    UNIQUE (execution_id, sequence)
);
CREATE INDEX idx_checkpoints_execution ON checkpoints (tenant_id, execution_id);

-- C39: runtime types a binding requires (empty = any runtime).
ALTER TABLE bindings ADD COLUMN required_runtime_types JSONB NOT NULL DEFAULT '[]'::jsonb;

-- CONF-007: worker-level quota column, always NULL in this phase, part of the unique scope.
ALTER TABLE operation_quotas ADD COLUMN worker_id TEXT REFERENCES workers(worker_id);
ALTER TABLE operation_quotas ADD CONSTRAINT chk_operation_quotas_no_worker CHECK (worker_id IS NULL);
DO $$
DECLARE c TEXT;
BEGIN
    SELECT conname INTO c FROM pg_constraint
     WHERE conrelid = 'operation_quotas'::regclass AND contype = 'u';
    EXECUTE format('ALTER TABLE operation_quotas DROP CONSTRAINT %I', c);
END $$;
ALTER TABLE operation_quotas ADD CONSTRAINT uq_operation_quotas_scope
    UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start);

-- Transition log for every persisted machine (C24): run, step, reservation, lease, dead letter, episode, confirmation.
DO $$
DECLARE c TEXT;
BEGIN
    SELECT con.conname INTO c FROM pg_constraint con
      JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
     WHERE con.conrelid = 'state_transitions'::regclass AND con.contype = 'c' AND a.attname = 'entity_type';
    EXECUTE format('ALTER TABLE state_transitions DROP CONSTRAINT %I', c);
END $$;
ALTER TABLE state_transitions ADD CONSTRAINT chk_state_transitions_machine
    CHECK (entity_type IN ('run', 'step', 'reservation', 'lease', 'dead_letter', 'episode', 'confirmation'));
ALTER TABLE state_transitions ADD COLUMN execution_id TEXT;
CREATE INDEX idx_state_transitions_machine ON state_transitions (tenant_id, entity_type, entity_id, transition_id);
CREATE INDEX idx_state_transitions_execution ON state_transitions (tenant_id, execution_id, transition_id);

-- Row-level security on every new tenant table (C34), same policy as 001/009.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['workers', 'worker_leases', 'step_reconciliations', 'dead_letters', 'idempotency_ledger',
                             'checkpoints'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;

-- The step reservation link (C33) and the dispatch marker (C35) already exist (009/010).
