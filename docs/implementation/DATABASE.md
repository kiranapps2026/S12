# Database

**Purpose**: Complete database schema, migrations, connection management, backup/restore procedures, and data seeding. This is the data layer that supports all other components.

**Worker-management update (2026-09-29)**: gate v10 C39 and rulings RD-1…RD-18 (`WORKER_MGMT_SPEC_REVIEW.md` Part E). Worker keys unified to `TEXT` (RD-1); management columns on `workers`, `tenants`, `workspaces`; new table `operation_quotas`; RLS, indexes, integrity rules and migration `018` updated. Changed passages carry a `Worker-management repair (RD-n)` marker.

---

## Table of Contents

1. [Database Overview](#1-database-overview)
2. [Connection Management](#2-connection-management)
3. [Schema Definition](#3-schema-definition)
4. [Migrations](#4-migrations)
5. [Backup & Restore](#5-backup--restore)
6. [Data Seeding](#6-data-seeding)
7. [Queries & Performance](#7-queries--performance)
8. [Connection Pool Governance](#8-connection-pool-governance)
9. [Row-Level Security (RLS) Policies](#9-row-level-security-rls-policies)
10. [Checkpoint & Recovery](#10-checkpoint--recovery)
11. [PostgreSQL WAL & Write Barriers](#11-postgresql-wal--write-barriers)
12. [Index Strategy](#12-index-strategy)
13. [Data Integrity Rules](#13-data-integrity-rules)
14. [Testing Database](#14-testing-database)
15. [Monitoring & Alerts](#15-monitoring--alerts)

---

## 1. Database Overview

### Technology

| Attribute | Value |
|-----------|-------|
| Engine | PostgreSQL 16 |
| Mode | Row-Level Security (RLS) enabled |
| Location | Configurable via DATABASE_URL |
| Connections | Pooled (SQLAlchemy) |
| Migrations | Versioned SQL files (Alembic) |

### Why PostgreSQL

PostgreSQL is the production engine from M0. Row-Level Security (RLS) enforces tenant isolation at the database level. SQLite exists only in `tests/`, `local-dev/`, and `isolated-unit-tests/`.

- Row-Level Security (RLS) enforces tenant isolation at the database level
- Connection pooling via SQLAlchemy for concurrent access
- ACID compliant with full transaction support
- Production-grade with built-in replication and backup tools

> **Note**: Every table is defined exactly once in this document.

### PostgreSQL Role Boundaries

PostgreSQL is the system of record. It is NOT the message bus.

| Responsibility | PostgreSQL | Redis / Message Layer | Stream Layer |
|----------------|-----------|----------------------|--------------|
| Durable state | YES | — | — |
| Authoritative execution state | YES | — | — |
| Budget reservations | YES | — | — |
| Heartbeats | — | YES | — |
| Progress events | — | YES | — |
| A2A messages | — | YES | — |
| Scheduler ticks | — | YES | — |
| Retry signals | — | YES | — |
| Health updates | — | YES | — |
| Streaming tokens | — | — | YES |
| Real-time client updates | — | — | YES |

At 10,000-worker scale, PostgreSQL handles durable state only. All ephemeral coordination uses Redis or the message layer.

---

## 2. Connection Management

### The Database Class (SQLAlchemy Singleton)

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

class Database:
    """Singleton database connection manager using SQLAlchemy."""

    _instance = None
    _engine = None
    _SessionFactory = None

    def __new__(cls, url: str):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, url: str):
        if hasattr(self, '_initialized'):
            return
        self._url = url
        self._init()
        self._initialized = True

    def _init(self):
        """Create engine, session factory, and run migrations."""
        self._engine = create_engine(
            self._url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
        self._SessionFactory = sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
        )
        # Run migrations
        self._run_migrations()

    @contextmanager
    def session(self):
        """Get a database session. Auto-commits on success, rolls back on error."""
        session = self._SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _run_migrations(self) -> None:
        """Run pending Alembic migrations."""
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("db/alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", self._url)
        command.upgrade(alembic_cfg, "head")
```

### Connection Rules

| Rule | Enforcement |
|------|-------------|
| Singleton pattern | Only one Database instance per process |
| Session per operation | Use `with db.session() as s:` |
| NEVER store sessions | No session as instance variable |
| Connection pooling | SQLAlchemy pool (10 base, 20 overflow) |
| pool_pre_ping=True | Validates connections before use |
| expire_on_commit=False | Prevents stale data after commit |

### CI Enforcement

```bash
# Check no direct sqlite3 imports in engine/ shared/ logic/
grep -r "import sqlite3" engine/ shared/ logic/ | grep -v "tests/"
# Should return empty (sqlite3 allowed in tests only)
```

---

## 3. Schema Definition

### Tables

#### kernel_ops

```sql
CREATE TABLE providers (
    provider_id TEXT PRIMARY KEY,        -- Provider identifier (e.g., "ghl", "notion")
    name TEXT NOT NULL,
    adapter_module TEXT NOT NULL,         -- Python module path
    adapter_class TEXT NOT NULL,          -- Adapter class name
    is_active BOOLEAN DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE kernel_ops (
    kernel_op_id TEXT PRIMARY KEY,       -- e.g., "ghl.contact_create"
    name TEXT NOT NULL,                   -- Human-readable name
    description TEXT,                     -- What this operation does
    provider TEXT NOT NULL,               -- Provider prefix (ghl, notion, etc.)
    mutation TEXT NOT NULL,               -- R, W, D, IRREVERSIBLE
    risk_floor REAL NOT NULL DEFAULT 0.0, -- Minimum risk (0.0-1.0)
    risk_rule REAL NOT NULL DEFAULT 0.0,  -- Rule-based risk
    risk_implied REAL NOT NULL DEFAULT 0.0, -- Context-implied risk
    cost INTEGER NOT NULL DEFAULT 1,      -- Budget cost units
    retry_safety TEXT NOT NULL DEFAULT 'safe', -- safe, idempotent, never
    inverse TEXT,                         -- Inverse kernel_op_id for rollback
    timeout INTEGER DEFAULT 30,           -- Max seconds for this operation
    input_schema TEXT NOT NULL,           -- JSON schema for params
    output_schema TEXT NOT NULL,          -- JSON schema for results
    is_implemented BOOLEAN DEFAULT 0,     -- Is the kernel implemented?
    is_enabled BOOLEAN DEFAULT 1,         -- Is the capability enabled?
    status TEXT DEFAULT 'discovered',     -- DISCOVERED, LIVE_VERIFIED, CERTIFIED, PRODUCTION_ENABLED
    verification_status TEXT DEFAULT 'phantom', -- phantom, pending, verified, certified
    created_at REAL NOT NULL,             -- Unix timestamp
    updated_at REAL NOT NULL,             -- Unix timestamp
    FOREIGN KEY (provider) REFERENCES providers(provider_id)
);
CREATE INDEX idx_kernel_ops_provider ON kernel_ops(provider);
CREATE INDEX idx_kernel_ops_status ON kernel_ops(status);
CREATE INDEX idx_kernel_ops_verification ON kernel_ops(verification_status);
```

#### capabilities

```sql
CREATE TABLE capabilities (
    capability_id TEXT PRIMARY KEY,        -- Provider-neutral identity (e.g., "contact_create")
    name TEXT NOT NULL,
    description TEXT,
    mutation TEXT NOT NULL,                -- "R" | "W" | "D" | "IRREVERSIBLE"
    risk_floor REAL NOT NULL,
    risk_rule REAL NOT NULL,
    risk_implied REAL NOT NULL,
    cost INTEGER NOT NULL,
    retry_safety TEXT NOT NULL,            -- "safe" | "idempotent" | "never"
    inverse TEXT,                          -- Inverse kernel_op_id
    input_schema TEXT,                     -- JSON Schema
    output_schema TEXT,                    -- JSON Schema
    truth_state TEXT NOT NULL,             -- DISCOVERED → LIVE_VERIFIED → CERTIFIED → PRODUCTION_ENABLED
    is_active BOOLEAN DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_capabilities_truth_state ON capabilities(truth_state);

-- D-DB5: capabilities stay provider-neutral. Provider mapping is through bindings only,
-- matching RESOLVE_LAYER.md's capability → binding → kernel_op flow.
```

#### bindings

```sql
CREATE TABLE bindings (
    binding_id TEXT PRIMARY KEY,          -- UUID
    capability_id TEXT NOT NULL,          -- Maps to capabilities.capability_id
    kernel_op_id TEXT NOT NULL,           -- Maps to kernel_ops.kernel_op_id
    provider TEXT NOT NULL,               -- Provider prefix
    priority INTEGER DEFAULT 1,           -- Lower = higher priority
    engine_module TEXT NOT NULL,          -- Python module path
    adapter_class TEXT NOT NULL,          -- Adapter class name
    endpoint TEXT,                        -- API endpoint
    is_active BOOLEAN DEFAULT 1,
    required_runtime_types JSONB NOT NULL DEFAULT '[]'::jsonb,  -- gate v10 C39 filter 17c; empty = any runtime
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (capability_id) REFERENCES capabilities(capability_id),
    FOREIGN KEY (kernel_op_id) REFERENCES kernel_ops(kernel_op_id),
    FOREIGN KEY (provider) REFERENCES providers(provider_id)
);
CREATE INDEX idx_bindings_capability ON bindings(capability_id);
CREATE INDEX idx_bindings_kernel ON bindings(kernel_op_id);
CREATE INDEX idx_bindings_provider ON bindings(provider);
```

> **Worker-management repair (audit round 2 B1; gate v10 C39):** `required_runtime_types` lists the `RuntimeType` values (DATA_CONTRACTS §50) whose workers may run this binding; empty means any. Values are validated at binding registration; a binding that no current worker can serve is a readiness warning, not an error. It is **not** part of `FrozenBindingIdentity`: S12 reads it from the binding row it already reads once at entry (gate C32), so no S0–S11 contract changes.

#### actions

```sql
CREATE TABLE actions (
    action_id TEXT PRIMARY KEY,           -- UUID
    name TEXT NOT NULL,                   -- User-facing name
    description TEXT,                     -- User-facing description
    aliases TEXT,                         -- JSON array of alias strings
    tags TEXT,                            -- JSON array of tags
    category TEXT,                        -- Category for grouping
    is_active BOOLEAN DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_actions_category ON actions(category);
CREATE INDEX idx_actions_tags ON actions(tags);
```

#### users

```sql
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,             -- Claude Code user ID or UUID
    tenant_id TEXT NOT NULL,              -- Tenant this user belongs to
    workspace_id TEXT NOT NULL,           -- Primary workspace
    username TEXT,                        -- Claude Code username
    display_name TEXT,                    -- Display name
    is_active BOOLEAN DEFAULT 1,
    max_risk TEXT DEFAULT 'W',            -- Max mutation level: R, W, D, IRREVERSIBLE
    granted_capabilities TEXT,            -- DEPRECATED: use capability_grants table. JSON array retained for migration only.
    scopes TEXT DEFAULT '["user"]',       -- JSON array of scopes
    budget_period TEXT DEFAULT 'monthly', -- daily, weekly, monthly
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
);
CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_workspace ON users(workspace_id);
CREATE INDEX idx_users_active ON users(is_active);
```

> **Note**: Canonical budget ownership: `tenants.budget_pool`. Budget reservations are tracked in `budget_reservations` table scoped by `tenant_id`.
> Database constraint: `budget_reservations.amount <= tenants.budget_pool` (enforced at application layer with atomic UPDATE).

#### budget_reservations

```sql
CREATE TABLE budget_reservations (
    reservation_id   TEXT PRIMARY KEY,               -- UUID v4
    tenant_id        TEXT NOT NULL,                  -- RLS tenant key
    user_id          TEXT NOT NULL,                  -- Attribution
    execution_id     TEXT NOT NULL,                  -- Parent execution
    step_id          TEXT NOT NULL,                  -- Specific step
    cost             INTEGER NOT NULL,               -- Minor units
    status           TEXT NOT NULL DEFAULT 'reserved',  -- ReservationState values: reserved | locked | committed | released ('pending' is in-memory only)
    created_at       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    committed_at     TEXT,
    released_at      TEXT,
    locked_at        TEXT,

    FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id),
    FOREIGN KEY (step_id) REFERENCES execution_steps(step_id)
);

CREATE INDEX idx_reservations_execution ON budget_reservations(execution_id);
CREATE INDEX idx_reservations_step ON budget_reservations(step_id);
CREATE INDEX idx_reservations_locked ON budget_reservations(locked_at)
    WHERE status = 'locked';
```

> **S12–S15 gate v9 repair (C3, C33, C34):** Budget is reserved per step (`step_id` NOT NULL). Availability = `tenants.budget_pool` − Σ `cost` of the tenant's `reserved`/`locked`/`committed` reservations created in the current period; the period start is `date_trunc` of database time (UTC) per `tenants.budget_period`. When this table is created in S12–S15, `created_at` is `TIMESTAMPTZ NOT NULL DEFAULT now()`; if it already exists as TEXT, add `created_at_ts TIMESTAMPTZ NOT NULL DEFAULT now()` and use that. The column is `cost` (the §13 "amount" wording is a naming error), and there is no `tenant_budget` table.


---

#### capability_grants

```sql
CREATE TABLE capability_grants (
    capability_grant_id TEXT PRIMARY KEY,   -- UUID
    tenant_id TEXT NOT NULL,                -- Tenant boundary
    workspace_id TEXT NOT NULL,             -- Workspace boundary
    grantee_type TEXT NOT NULL,             -- "user" | "worker"
    grantee_id TEXT NOT NULL,               -- user_id or worker_id
    capability_id TEXT,                     -- Provider-neutral capability
    kernel_op_id TEXT,                      -- Provider-qualified operation
    scope TEXT,                             -- JSON scope object
    connection_id TEXT,                     -- Optional connection restriction
    resource_id TEXT,                       -- Optional resource restriction
    granted_by TEXT NOT NULL,               -- user_id or worker_id
    granted_at REAL NOT NULL,               -- Unix timestamp
    expires_at REAL,                        -- Unix timestamp (NULL = permanent)
    is_active BOOLEAN DEFAULT 1,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (grantee_id) REFERENCES users(user_id)
);
CREATE INDEX idx_capability_grants_grantee ON capability_grants(grantee_type, grantee_id);
CREATE INDEX idx_capability_grants_tenant ON capability_grants(tenant_id);
CREATE INDEX idx_capability_grants_capability ON capability_grants(capability_id);
```

#### memberships

```sql
CREATE TABLE memberships (
    membership_id TEXT PRIMARY KEY,         -- UUID v4
    tenant_id TEXT NOT NULL,                -- Tenant this membership belongs to
    user_id TEXT NOT NULL,                  -- User who holds the membership
    workspace_id TEXT NOT NULL,             -- Workspace within the tenant
    role TEXT NOT NULL DEFAULT 'member',    -- owner, admin, member, viewer
    is_active BOOLEAN DEFAULT 1,
    granted_at REAL NOT NULL,               -- Unix timestamp
    revoked_at REAL,                        -- Unix timestamp (NULL = active)
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id),
    UNIQUE(tenant_id, user_id, workspace_id)
);
CREATE INDEX idx_memberships_user ON memberships(user_id);
CREATE INDEX idx_memberships_tenant ON memberships(tenant_id);
CREATE INDEX idx_memberships_workspace ON memberships(workspace_id);
```

#### tenants

```sql
CREATE TABLE tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    settings TEXT,                        -- JSON settings
    budget_pool INTEGER DEFAULT 10000,    -- Tenant's shared budget pool (minor units)
    budget_period TEXT DEFAULT 'monthly', -- daily, weekly, monthly
    paused_until TIMESTAMPTZ,             -- no new runs while > NOW(): S0.1 (ruling R-P) + S12 entry (C39)
    scheduled_activation_at TIMESTAMPTZ,  -- no new runs until <= NOW(): S0.1 + S12 entry
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

> **Worker-management repair (RD-2, RD-5; audit round 2 B6; gate v10 C39):** `paused_until` and `scheduled_activation_at` are typed columns, not keys inside the TEXT `settings` JSON. They are checked at S0.1 (S0–S11 ruling R-P, before any S1–S11 work) and re-checked at S12 entry, for new runs only, against database `NOW()`; a pause never cancels running work (the kill switch does). If ruling R-P lands before migration 018, R-P adds these four columns and 018 skips them. Existing `REAL` timestamps are unchanged.

#### connections

```sql
CREATE TABLE connections (
    connection_id TEXT PRIMARY KEY,       -- Claude Code chat ID or connection ID
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,            -- Workspace this connection belongs to
    provider TEXT,                        -- Primary provider
    is_active BOOLEAN DEFAULT 1,
    last_activity REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
);
CREATE INDEX idx_connections_user ON connections(user_id);
CREATE INDEX idx_connections_workspace ON connections(workspace_id);
CREATE INDEX idx_connections_active ON connections(is_active);
```

#### workspaces

```sql
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY,          -- UUID
    tenant_id TEXT NOT NULL,                 -- Parent tenant
    name TEXT NOT NULL,
    description TEXT,
    settings TEXT,                           -- JSON settings
    is_active BOOLEAN DEFAULT 1,
    paused_until TIMESTAMPTZ,                -- see tenants: S0.1 + S12 entry
    scheduled_activation_at TIMESTAMPTZ,     -- see tenants: S0.1 + S12 entry
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX idx_workspaces_tenant ON workspaces(tenant_id);
```

> **Worker-management repair (RD-2, RD-5; gate v10 C39):** same semantics as the tenant columns; the effective value is `GREATEST(tenant, workspace)` (WORKER_LIFECYCLE §16.5).

#### execution_runs

```sql
CREATE TABLE execution_runs (
    execution_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,                  -- Links all downstream objects (D-TRACE1)
    task_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,            -- D-DB4: workspace context
    conversation_id TEXT NOT NULL,
    plan_id TEXT,                         -- NULL for single-step
    status TEXT NOT NULL,                 -- ExecutionStatus values: pending, running, reconciling, completed, partial, failed, cancelled, dead_letter (gate C7, C28)
    actor_type TEXT NOT NULL DEFAULT 'user',  -- "user" | "worker" | "system"
    actor_id TEXT NOT NULL,                    -- user_id or worker_id
    consolidation TEXT,                   -- ok, partial, failed
    budget_spent INTEGER DEFAULT 0,
    duration_ms INTEGER,
    started_at REAL,
    completed_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id)
);
CREATE INDEX idx_execution_runs_trace ON execution_runs(trace_id);
CREATE INDEX idx_execution_runs_user ON execution_runs(user_id);
CREATE INDEX idx_execution_runs_tenant ON execution_runs(tenant_id);
CREATE INDEX idx_execution_runs_workspace ON execution_runs(workspace_id);
CREATE INDEX idx_execution_runs_actor ON execution_runs(actor_type, actor_id);
CREATE INDEX idx_execution_runs_status ON execution_runs(status);
CREATE INDEX idx_execution_runs_created ON execution_runs(created_at);
```

> **S12–S15 gate v9 repair (C16, C28, C33, v7.3):** Additive: `cancel_requested_at TIMESTAMPTZ NULL` (C16) and a unique index on `(tenant_id, request_id)` (duplicate detection). Status CHECK is generated from `ExecutionStatus`. At S12 entry `task_id`, `workspace_id`, `conversation_id`, `user_id` come from ExecutionContext, `actor_type = 'user'`, `actor_id = user_id`. No `ON DELETE CASCADE` from this table (register P1-H).


#### execution_steps

```sql
CREATE TABLE execution_steps (
    step_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    plan_id TEXT,
    kernel_op_id TEXT NOT NULL,
    resolved_binding_id TEXT NOT NULL,      -- Binding used
    effective_risk REAL NOT NULL,           -- float 0.0-1.0
    effective_mutation TEXT NOT NULL,       -- R/W/D/IRREVERSIBLE
    request_fingerprint TEXT NOT NULL,      -- SHA-256 of canonical JSON {kernel_op_id, params}; diagnostics only (gate C33)
    reservation_id TEXT,                    -- FK to budget_reservations (per-step budget tracking)
    status TEXT NOT NULL,                   -- StepState values: pending, running, completed, partial, failed, cancelled, skipped, timeout, unknown, pending_probe, dead_letter (gate C22, C28)
    data TEXT,                              -- JSON result data
    error TEXT,                             -- Error message
    attempt INTEGER DEFAULT 1,
    undo_token TEXT,                        -- Token for inverse operation
    duration_ms INTEGER,
    created_at REAL NOT NULL,
    FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id),
    FOREIGN KEY (reservation_id) REFERENCES budget_reservations(reservation_id)
);
CREATE INDEX idx_execution_steps_execution ON execution_steps(execution_id);
CREATE INDEX idx_execution_steps_plan ON execution_steps(plan_id);
```

> **S12–S15 gate v9 repair (C22, C33, C34, C35):** Additive columns: `plan_step_id TEXT NOT NULL` (the S9 step id; `step_id` stores the globally unique `"{execution_id}:{plan_step_id}"`, register MC-021); `terminal_reason TEXT NULL` with `CHECK (status NOT IN ('cancelled','skipped') OR terminal_reason IS NOT NULL)`, a CHECK against `StepTerminalReason`, and a `BEFORE UPDATE` trigger rejecting any change of a non-null value; `dispatched_attempt INTEGER NULL` (dispatch marker); `tenant_id TEXT NOT NULL` (C34). `reservation_id` is set after the reservation is inserted, in the same transaction; a retry after NOT_EXECUTED points it at the new reservation.


> **Note**: `skill_id` and `business_action_id` (seen in legacy `step_results` schema) are deferred pending Skill Factory design. Columns are omitted from the canonical schema until that design is finalized.

```

#### execution_manifests

```sql
CREATE TABLE execution_manifests (
    execution_id TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    trace_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    capability_version TEXT NOT NULL,
    binding_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    risk_policy_version TEXT NOT NULL,
    authorization_version TEXT NOT NULL,
    worker_runtime_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    worker_configuration_version TEXT,
    skill_versions JSONB,
    artifact_versions JSONB,
    created_at REAL NOT NULL,
    FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)
);
CREATE INDEX idx_execution_manifests_trace ON execution_manifests(trace_id);
```

> **S12–S15 gate v9 repair (C38):** Persisted at S12 entry in the admission transaction (it references `execution_runs`), byte-identical to the manifest frozen at S11. Never updated.


#### checkpoints

```sql
CREATE TABLE checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES execution_manifests(execution_id),
    plan_id TEXT NOT NULL,
    completed_steps TEXT NOT NULL,        -- JSON array of step IDs
    failed_steps TEXT NOT NULL,           -- JSON array
    pending_steps TEXT NOT NULL,          -- JSON array
    current_step TEXT,
    context_snapshot TEXT,                -- JSON ExecutionContext
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,             -- 24h from creation
    FOREIGN KEY (execution_id) REFERENCES execution_manifests(execution_id)
);
CREATE INDEX idx_checkpoints_execution ON checkpoints(execution_id);
CREATE INDEX idx_checkpoints_expires ON checkpoints(expires_at);
```

> **S12–S15 gate v9 repair (C10, C34):** Checkpoints are rows in this table only (no files). Additive `tenant_id` (C34). The cleanup job never deletes a checkpoint of a non-terminal run. The checkpoint is a hint; database state is the source of truth on recovery.


#### pending_confirmations

```sql
CREATE TABLE pending_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,           -- gate C20: no FK (S10 writes before the run row exists)
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    plan_hash TEXT NOT NULL,
    confirmation_message TEXT NOT NULL,
    status TEXT DEFAULT 'pending',        -- pending, consumed, rejected, expired (CHECK; gate C20)
    expires_at REAL NOT NULL,             -- 5 minutes from creation
    created_at REAL NOT NULL,
    consumed_at REAL,                     -- NULL = not yet consumed
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX idx_confirmations_execution ON pending_confirmations(execution_id);
CREATE INDEX idx_confirmations_status ON pending_confirmations(status);
CREATE INDEX idx_confirmations_expires ON pending_confirmations(expires_at);
```

> **S12–S15 gate v9 repair (C20):** Additive columns `user_id`, `conversation_id`, `plan_id` so the row carries every `Confirmation` field. `tenant_id` and `execution_id` are supplied by S10 through the store interface (S0–S11 runbook ruling R-Z). Consumption is one conditional `UPDATE ... WHERE status = 'pending' AND expires_at > now AND plan_hash = :h AND user_id = :u AND tenant_id = :t`; one row updated = success.


#### dead_letters

```sql
CREATE TABLE dead_letters (
    dead_letter_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    kernel_op_id TEXT NOT NULL,
    reservation_id TEXT,                     -- FK to budget_reservations (MC-023)
    error TEXT NOT NULL,
    error_type TEXT NOT NULL,                -- transient, permanent, data, unknown_unresolved (CHECK; gate C21)
    mutation_type TEXT NOT NULL DEFAULT 'R', -- R, W, D, IRREVERSIBLE (MC-023)
    is_idempotent BOOLEAN DEFAULT 0,         -- MC-023
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    next_retry_at REAL,                      -- NULL = no more retries
    context TEXT,                            -- JSON context
    resolved BOOLEAN DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id),
    FOREIGN KEY (step_id) REFERENCES execution_steps(step_id),
    FOREIGN KEY (reservation_id) REFERENCES budget_reservations(reservation_id)
);
CREATE INDEX idx_dead_letters_execution ON dead_letters(execution_id);
CREATE INDEX idx_dead_letters_mutation ON dead_letters(mutation_type);
CREATE INDEX idx_dead_letters_retry ON dead_letters(next_retry_at) WHERE resolved = 0;
CREATE INDEX idx_dead_letters_resolved ON dead_letters(resolved);
CREATE INDEX idx_dead_letters_next_retry ON dead_letters(next_retry_at);
```

> **S12–S15 gate v9 repair (C21, C27, C29, C34):** Additive columns: `status TEXT NOT NULL DEFAULT 'pending'` CHECK in (pending, retrying, resolved, abandoned), kept consistent with `resolved`; `retry_mode TEXT NOT NULL` CHECK in (PROBE, VERIFY, NONE); `episode_id TEXT NULL`; `resolution_outcome TEXT NULL` CHECK in (EXECUTED, NOT_EXECUTED, UNDETERMINED), required when status is resolved/abandoned; `origin TEXT NOT NULL DEFAULT 'execution'` CHECK in (execution, rollback); `attempt_id TEXT NULL`; `tenant_id TEXT NOT NULL`.


#### idempotency_ledger

```sql
CREATE TABLE idempotency_ledger (
    idempotency_key TEXT PRIMARY KEY,
    kernel_op_id TEXT NOT NULL,
    result TEXT NOT NULL,                 -- JSON KernelResult
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL              -- 24h from creation
);
CREATE INDEX idx_idempotency_expires ON idempotency_ledger(expires_at);
```

> **S12–S15 gate v9 repair (C9, C17, C34):** The key is the step idempotency key `"{request_id}:{plan_step_id}"`. Additive `tenant_id` (NOT NULL when the table is empty) and an index on `(tenant_id, idempotency_key)`; every lookup filters on both. An expired record counts as no record and never authorizes a fresh call (the step is probed instead).


#### provider_tokens

```sql
CREATE TABLE provider_tokens (
    token_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,               -- ghl, notion, google, airtable
    token_type TEXT NOT NULL,             -- pit, firebase_jwt, bearer, oauth
    encrypted_token BLOB NOT NULL,        -- Encrypted token data
    expires_at REAL,                      -- NULL = no expiry
    is_active BOOLEAN DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX idx_tokens_tenant ON provider_tokens(tenant_id);
CREATE INDEX idx_tokens_provider ON provider_tokens(provider);
```

#### audit_log

```sql
CREATE TABLE audit_log (
    log_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,               -- From ExecutionContext.request_id (fast index for log-line filtering)
    trace_id TEXT NOT NULL,                 -- From ExecutionContext.trace_id (cross-document correlation — D-TRACE1)
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    event TEXT NOT NULL,                  -- Event type
    level TEXT NOT NULL,                  -- DEBUG, INFO, WARNING, ERROR, ALERT
    data TEXT NOT NULL,                   -- JSON event data (full structured event for querying)
    created_at REAL NOT NULL
);
CREATE INDEX idx_audit_request ON audit_log(request_id);
CREATE INDEX idx_audit_trace ON audit_log(trace_id);
CREATE INDEX idx_audit_user ON audit_log(user_id);
CREATE INDEX idx_audit_event ON audit_log(event);
CREATE INDEX idx_audit_created ON audit_log(created_at);
```

#### retry_log

```sql
CREATE TABLE retry_log (
    log_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,               -- kernel_op_id
    error_type TEXT NOT NULL,              -- transient, permanent, data
    attempt INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (provider) REFERENCES providers(provider_id)
);
CREATE INDEX idx_retry_provider ON retry_log(provider);
CREATE INDEX idx_retry_timestamp ON retry_log(timestamp);
```

#### workers

```sql
CREATE TABLE workers (
    worker_id TEXT PRIMARY KEY,                        -- RD-1: TEXT (was UUID)
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),  -- RD-1: TEXT (was UUID, mismatched tenants.tenant_id)
    worker_class VARCHAR(100) NOT NULL,
    runtime_version VARCHAR(50),
    capability_profile JSONB NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'REGISTERED',   -- STATE_TRANSITIONS §4 (gate C33)
    capacity INTEGER NOT NULL DEFAULT 1,               -- max concurrent executions
    current_load INTEGER NOT NULL DEFAULT 0,           -- = number of usable leases (gate C26)
    lease_epoch BIGINT NOT NULL DEFAULT 0,             -- newest fence token issued to this worker (gate C25)
    heartbeat_at TIMESTAMP,
    last_assignment_at TIMESTAMP,
    drain_state VARCHAR(20),
    -- Worker-management columns (gate v10 C39; mutable, read only by S12 admission/selection)
    workspace_id TEXT REFERENCES workspaces(workspace_id),  -- filter 4b; required for new registrations; NULL = legacy row, ineligible
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,       -- contract: IDENTITY_AND_TENANCY §5
    assigned_user_id TEXT REFERENCES users(user_id),   -- filter 14; NULL = any user
    paused_until TIMESTAMPTZ,                          -- filter 12b
    scheduled_activation_at TIMESTAMPTZ,               -- filter 13b
    runtime_type TEXT NOT NULL DEFAULT 'llm'
        CHECK (runtime_type IN ('llm','rules','vision','browser','rpa','data','rag','code','human')),  -- filter 17
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_workers_tenant ON workers(tenant_id);
CREATE INDEX idx_workers_state ON workers(state);
CREATE INDEX idx_workers_assigned_user ON workers(assigned_user_id) WHERE assigned_user_id IS NOT NULL;
CREATE INDEX idx_workers_workspace ON workers(workspace_id);
```

> **Worker-management repair (RD-1, RD-2, RD-4, RD-10; gate v10 C39):** owner ruling: `worker_id` and every column that references it are `TEXT`, like every other key in this schema. This overrides the gate §7.3 default (change the referencing column). `tenant_id` also changes to `TEXT`: the former `UUID` could not reference `tenants.tenant_id TEXT`. The management columns are additive; `runtime_type` is the only worker-type enum (plan/event/hybrid is derived from `event_subscriptions`), and its CHECK is generated from `RuntimeType` (DATA_CONTRACTS §50, C28). Pause and activation are not states: a paused worker stays `ACTIVE` and is filtered out of worker selection for **new** leases only. `workspace_id` (audit round 2 B7; WORKER_LIFECYCLE §3 and DATA_CONTRACTS `WorkerIdentity` already had it) restores the workspace boundary: a worker is eligible only for runs in its own workspace (filter 4b); it is nullable only so that legacy rows, if preflight finds any, stay ineligible until backfilled. This restores the `idx_workers_workspace` index that C33 removed for lack of the column. Deferred and **not** added in this phase: `max_sub_agents`, `parent_worker_id`, `depth_level` (spawning).

> **S12–S15 gate v9 repair (C33):** `idx_workers_workspace` was removed: this definition has no `workspace_id` column (WORKER_LIFECYCLE §3 has one; add the index only together with the column).

#### worker_versions

```sql
CREATE TABLE worker_versions (
    version_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),
    version TEXT NOT NULL,                         -- semver
    artifact_hash TEXT NOT NULL,                   -- SHA-256
    state TEXT NOT NULL DEFAULT 'REGISTERED',      -- WorkerVersionState values
    canary_percentage INTEGER NOT NULL DEFAULT 0,  -- 0-100
    rollout_config JSONB,                          -- gate thresholds, ramp schedule
    deployed_at REAL,
    promoted_at REAL,
    deprecated_at REAL,
    drained_at REAL,
    created_at REAL NOT NULL,

    UNIQUE(worker_id, artifact_hash)  -- same hash = same version
);
CREATE INDEX idx_worker_versions_worker ON worker_versions(worker_id);
CREATE INDEX idx_worker_versions_state ON worker_versions(state);
CREATE INDEX idx_worker_versions_worker_state ON worker_versions(worker_id, state);
```

#### worker_leases

```sql
CREATE TABLE worker_leases (
    lease_id TEXT PRIMARY KEY,                       -- RD-1: TEXT (referenced by execution_ownership.lease_id TEXT)
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),  -- RD-1: TEXT
    fence_token BIGINT NOT NULL,
    task_id TEXT,                                    -- RD-1: TEXT, matches execution_runs.task_id
    expires_at TIMESTAMP NOT NULL,
    acquired_at TIMESTAMP NOT NULL DEFAULT NOW(),
    released_at TIMESTAMP
);
CREATE INDEX idx_worker_leases_worker ON worker_leases(worker_id);
CREATE INDEX idx_worker_leases_expires ON worker_leases(expires_at);
CREATE INDEX idx_worker_leases_fence ON worker_leases(fence_token);
```

> **S12–S15 gate v9 repair (C25, C26, C34):** Tokens come from the sequence `CREATE SEQUENCE fence_token_seq;` (strictly increasing for every lease acquisition and renewal). Additive columns: `status TEXT NOT NULL DEFAULT 'active'` CHECK in (pending, active, expired, released); `execution_id TEXT NULL` (diagnostics); `tenant_id TEXT NOT NULL`. Index `ON worker_leases(worker_id) WHERE status = 'active'`. A lease is usable only while `status = 'active' AND expires_at > now()`. This is the lease of record; `execution_leases` (§10) is not used.

> **Worker-management repair (RD-1):** `lease_id` and `worker_id` changed from `UUID` to `TEXT`. `worker_id` must match `workers.worker_id`; `lease_id` must match `execution_ownership.lease_id TEXT`, which referenced it with a mismatched type.


#### worker_assignments

```sql
CREATE TABLE worker_assignments (
    assignment_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),              -- RD-1: TEXT
    execution_id TEXT NOT NULL REFERENCES execution_runs(execution_id), -- RD-1: TEXT (execution_runs.execution_id is TEXT)
    task_id TEXT,                                    -- RD-1: TEXT, matches execution_runs.task_id
    state VARCHAR(20) NOT NULL,
    claimed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);
CREATE INDEX idx_worker_assignments_worker ON worker_assignments(worker_id);
CREATE INDEX idx_worker_assignments_execution ON worker_assignments(execution_id);
CREATE INDEX idx_worker_assignments_state ON worker_assignments(state);
```

> **Worker-management repair (RD-1):** `assignment_id`, `worker_id` and `execution_id` changed from `UUID` to `TEXT`; the former `execution_id UUID` could not reference `execution_runs.execution_id TEXT`.

#### worker_deployments

```sql
CREATE TABLE worker_deployments (
    deployment_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),
    version_id TEXT NOT NULL REFERENCES worker_versions(version_id),
    runtime_instance_id TEXT NOT NULL,             -- pod/container ID
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 1,
    current_load INTEGER NOT NULL DEFAULT 0,
    health_status TEXT NOT NULL DEFAULT 'healthy', -- healthy | degraded | unhealthy
    last_heartbeat_at REAL NOT NULL,
    started_at REAL NOT NULL,
    terminated_at REAL
);
CREATE INDEX idx_deployments_worker ON worker_deployments(worker_id);
CREATE INDEX idx_deployments_version ON worker_deployments(version_id);
CREATE INDEX idx_deployments_health ON worker_deployments(health_status);
```

#### execution_ownership

```sql
CREATE TABLE execution_ownership (
    execution_id TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    worker_id TEXT REFERENCES workers(worker_id),
    worker_version TEXT REFERENCES worker_versions(version_id),
    runtime_instance_id TEXT,
    lease_id TEXT REFERENCES worker_leases(lease_id),
    fencing_token BIGINT NOT NULL DEFAULT 0,
    checkpoint_sequence INTEGER NOT NULL DEFAULT 0,
    state_location TEXT,
    owner_acquired_at REAL,
    lease_expires_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_exec_owner_worker ON execution_ownership(worker_id);
CREATE INDEX idx_exec_owner_lease ON execution_ownership(lease_id);
```

> **Worker Identity Invariant** (S12–S15 gate v9 repair, C25): fence tokens come from one database sequence, and `workers.lease_epoch` records the newest token issued to the worker. The write fence is **per execution**: every durable write for an execution goes through `fenced_write()`, which checks `execution_ownership.fencing_token = :holder_token AND runtime_instance_id = :runtime_instance_id` in the same transaction. A stale owner therefore cannot commit any state change for that execution, while other executions on the same worker (capacity > 1) are unaffected. The earlier per-worker session-middleware check would have fenced out every concurrent execution on a worker whenever one lease renewed.

---

### Event Gateway Tables

The `event_log`, `event_subscriptions`, and `webhook_credentials` tables are also described in [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) §10. **This file is authoritative (gate §3); §10 mirrors it.**

> **Repair (SEC-HMAC, SEC-NONCE, 2026-09-29):** the copies here had drifted from §10. `webhook_credentials` stored only `secret_hash`, which cannot verify an HMAC signature; `event_log` lacked the `idempotency_key` that replay protection depends on. Both are replaced by the full, corrected definitions below.

```sql
-- event_log: All incoming and outgoing events (full definition; EVENT_GATEWAY §10.1 mirrors it)
CREATE TABLE event_log (
    event_id TEXT PRIMARY KEY,           -- UUID v4
    tenant_id TEXT NOT NULL,             -- From auth context
    workspace_id TEXT NOT NULL,          -- From auth context
    event_type TEXT NOT NULL,            -- EventType or tenant-defined
    source TEXT NOT NULL,                -- EventSource value
    source_system TEXT NOT NULL,         -- "ghl", "stripe", "cron", etc.
    source_event_id TEXT,                -- Source's own event ID (for dedup)
    payload_ref TEXT NOT NULL,           -- "pg:event_log.{event_id}"
    payload_size_bytes INTEGER,          -- For billing
    schema_version TEXT NOT NULL,        -- Payload schema version
    correlation_id TEXT NOT NULL,        -- trace_id
    idempotency_key TEXT NOT NULL,       -- "{source}:{source_system}:{discriminator}" (EVENT_GATEWAY §3.1)
    auth_method TEXT NOT NULL,           -- "hmac_sha256", "api_key", etc.
    auth_principal TEXT NOT NULL,        -- connection_id or user_id
    processing_status TEXT NOT NULL DEFAULT 'received',  -- State machine values
    processing_execution_id TEXT,        -- execution_id if activated
    error TEXT,                          -- Error message if failed
    occurred_at REAL NOT NULL,           -- Source timestamp
    received_at REAL NOT NULL,           -- Server-authoritative timestamp
    created_at REAL NOT NULL,            -- Record creation timestamp

    -- Foreign keys
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    CONSTRAINT fk_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id),

    -- Constraints
    CONSTRAINT chk_processing_status CHECK (
        processing_status IN (
            'received', 'validated', 'deduplicated', 'routed',
            'processed', 'dropped', 'failed', 'closed'
        )
    ),
    CONSTRAINT chk_source CHECK (source IN ('webhook', 'schedule', 'mcp', 'api', 'internal'))
);
CREATE UNIQUE INDEX uq_event_log_tenant_idempotency ON event_log(tenant_id, idempotency_key);  -- replay protection (SEC-NONCE)

-- event_subscriptions: Worker declarations of event interest
CREATE TABLE event_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    event_types JSONB NOT NULL,
    source_systems JSONB NOT NULL,
    filter_expression TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    max_concurrent INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    matched_count INTEGER NOT NULL DEFAULT 0,
    last_matched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL
);

-- webhook_credentials: encrypted HMAC signing secrets (SEC-HMAC; EVENT_GATEWAY §10.3 mirrors it)
CREATE TABLE webhook_credentials (
    credential_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    source_system TEXT NOT NULL,            -- 'ghl', 'stripe', 'custom', 'mcp'
    secret_ciphertext BYTEA NOT NULL,       -- AES-256-GCM(HMAC secret) under the per-record DEK
    secret_nonce BYTEA NOT NULL,            -- 96-bit GCM nonce, fresh for every encryption
    wrapped_dek BYTEA NOT NULL,             -- per-record DEK wrapped by the KEK (the KEK never enters the database)
    kek_version INTEGER NOT NULL,           -- KEK version that wrapped the DEK; re-wrap on KEK rotation
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'retiring', 'retired')),
    retiring_until TIMESTAMPTZ,             -- end of the rotation grace period
    algorithm TEXT NOT NULL DEFAULT 'hmac-sha256' CHECK (algorithm IN ('hmac-sha256')),
    last_verified_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_system IN ('ghl', 'stripe', 'custom', 'mcp')),
    CHECK (status <> 'retiring' OR retiring_until IS NOT NULL)
);
-- one active and at most one retiring secret per (tenant, source): rotation never breaks in-flight webhooks
CREATE UNIQUE INDEX uq_webhook_credentials_active   ON webhook_credentials(tenant_id, source_system) WHERE status = 'active';
CREATE UNIQUE INDEX uq_webhook_credentials_retiring ON webhook_credentials(tenant_id, source_system) WHERE status = 'retiring';
CREATE INDEX idx_webhook_credentials_tenant ON webhook_credentials(tenant_id);

-- RLS: tenant isolation for application_role (management API)
ALTER TABLE webhook_credentials ENABLE ROW LEVEL SECURITY;
CREATE POLICY webhook_credentials_tenant_isolation ON webhook_credentials
    FOR ALL TO application_role
    USING (tenant_id = current_setting('app.current_tenant')::text)
    WITH CHECK (tenant_id = current_setting('app.current_tenant')::text);
-- Signature verification runs before any tenant context exists (the credential identifies the tenant, I-022):
-- a documented system_worker_role operation, SELECT only (DATABASE §9 Canonical Roles).
GRANT SELECT ON webhook_credentials TO system_worker_role;
CREATE POLICY webhook_credentials_gateway_lookup ON webhook_credentials
    FOR SELECT TO system_worker_role
    USING (status IN ('active', 'retiring'));
```

**Secret handling rules (SEC-HMAC, decided 2026-09-29):**

1. **Encrypted, never hashed.** HMAC verification needs the secret itself (`HMAC(secret, timestamp.body)`); a hash of the secret cannot verify a signature. Secrets use envelope encryption: AES-256-GCM under a per-record data key (DEK); the DEK is stored only wrapped by one system-wide key-encryption key (KEK) that lives in the platform secret manager and never enters the database. `kek_version` records which KEK wrapped the DEK.
2. **Decryption only through `CredentialProvider`** (gate §21 S6), inside the gateway's signature check. The plaintext secret is held in a `bytearray` for the shortest possible time and overwritten after use (best effort: Python cannot guarantee that no copy remains); it is never logged, returned by any API, written to the ledger, a checkpoint or a trace (I-018).
3. **Verification order:** the `active` secret, then a `retiring` secret while `retiring_until > NOW()` (database time). A match with the retiring secret is logged and counted, so the source's rotation can be tracked. `last_verified_at` is updated on success.
4. **Rotation:** in one transaction, move any existing `retiring` row to `retired`, move the current `active` row to `retiring` with `retiring_until = NOW() + grace` (default 24 hours, settings object), and insert the new secret as `active`; a cleanup job moves expired `retiring` rows to `retired` and deletes `retired` rows after the retention period. The two partial unique indexes allow exactly one active and at most one retiring secret per (tenant, source).
5. **KEK rotation** re-wraps each DEK (`wrapped_dek`, `kek_version`) without touching `secret_ciphertext`.
6. **Access:** `application_role` sees only its tenant's rows (RLS); the pre-tenant lookup for signature verification is a documented `system_worker_role` operation with SELECT on active and retiring rows only.

### S12–S15 Additive Tables (gate v9)

> **S12–S15 gate v9 repair (§7.3, C18, C24, C34):** tables added by the S12–S15 phase. All
> columns are PostgreSQL types; state columns store enum `.value` strings with CHECK
> constraints generated from the enums (C28); every table carries `tenant_id` with the
> standard RLS policy (C34).

```sql
CREATE SEQUENCE fence_token_seq;  -- every lease acquisition and renewal (C25)

CREATE TABLE execution_plans (
    execution_id TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    tenant_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,                 -- recomputed and compared on every load (I9)
    canonical_plan JSONB NOT NULL,
    frozen_binding_identity JSONB NOT NULL,  -- binding snapshot; never re-read after entry (C32)
    verifiers JSONB NOT NULL,                -- built at S12 entry (D1)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE step_reconciliations (
    episode_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    execution_id TEXT NOT NULL REFERENCES execution_runs(execution_id),
    step_id TEXT NOT NULL REFERENCES execution_steps(step_id),
    kind TEXT NOT NULL CHECK (kind IN ('EXECUTION', 'VERIFICATION')),
    status TEXT NOT NULL,                    -- ReconciliationStatus values (none never stored)
    outcome TEXT CHECK (outcome IN ('EXECUTED_SUCCESS','EXECUTED_FAILURE','NOT_EXECUTED',
                                    'LEDGER_HIT','VERIFIED_PASS','VERIFIED_FAIL','EXHAUSTED')),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,   -- e.g. no_dispatch_marker (C35)
    attempts INTEGER NOT NULL DEFAULT 0,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_step_open_episode ON step_reconciliations(step_id) WHERE closed_at IS NULL;

CREATE TABLE state_transitions (          -- transition log for I5/I6 (C24)
    transition_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    machine TEXT NOT NULL,                  -- run | step | reservation | lease | dead_letter | episode | confirmation
    entity_id TEXT NOT NULL,
    execution_id TEXT,
    from_state TEXT,                        -- NULL for creation
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    runtime_instance_id TEXT,
    fence_token BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_transitions_entity ON state_transitions(machine, entity_id, transition_id);
CREATE INDEX idx_transitions_execution ON state_transitions(execution_id, transition_id);
```

The transition log is append-only (FINAL_ARCHITECTURE I-027). It may equally be implemented as
rows in the execution ledger, provided the same columns are present.

### Worker-Management Additive Tables (gate v10 C39)

> **Worker-management repair (RD-1, RD-3, RD-6; gate v10 C39):** one new table in this phase.
> Keys are `TEXT` (RD-1), times are `TIMESTAMPTZ` compared with database `NOW()` (RD-2), and the
> table carries `tenant_id` with the standard RLS policy (RD-3, C34). Contract: DATA_CONTRACTS §51;
> semantics: WORKER_LIFECYCLE §16.4.

```sql
CREATE TABLE operation_quotas (
    quota_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id TEXT REFERENCES workspaces(workspace_id),   -- NULL = tenant level
    worker_id TEXT REFERENCES workers(worker_id),            -- NULL = tenant/workspace level
    resource_type TEXT NOT NULL DEFAULT 'executions'
        CHECK (resource_type IN ('executions')),              -- only value used in this phase
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    limit_value INTEGER NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    is_hard BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (used_count >= 0 AND limit_value >= 0),
    CHECK (used_count <= limit_value),                        -- I17 by construction; blocks lowering a limit below usage (audit B9)
    CHECK (period_end > period_start),
    CHECK (worker_id IS NULL),                                -- worker-level quotas out of phase: worker unknown at entry (audit A3)
    UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)  -- PostgreSQL 15+
);
CREATE INDEX idx_quotas_lookup ON operation_quotas(tenant_id, resource_type, period_start, period_end);
```

**Consumption** (once per run, inside the durable-admission transaction, gate §7.2; levels in the
fixed order tenant → workspace; zero rows at any level rolls the transaction back; there is no
per-step quota check, audit A1):

```sql
UPDATE operation_quotas
   SET used_count = used_count + 1
 WHERE quota_id = :quota_id
   AND tenant_id = :tenant_id
   AND period_start <= now() AND period_end > now()
   AND used_count < limit_value
RETURNING quota_id;
```

Hard quota with zero rows → DENY `quota_exhausted`; soft quota → bounded retry of the transaction,
then DENY `quota_exhausted` with `retry_after_ms` (audit A4). `used_count` never exceeds
`limit_value` on any row: the CHECK enforces it (invariant I17), and an `UPDATE` lowering
`limit_value` below `used_count` fails — put a lower limit on the next period's row. A refund (run CANCELLED with no step
COMPLETED) is `used_count = used_count - 1` in the transaction that consolidates the run, recorded
as a ledger event.

**Not created in this phase** (deferred, gate §14; each gets `tenant_id TEXT NOT NULL` + RLS when it
lands, RD-3): `worker_spawn_audit`, `worker_groups`, `worker_group_members`,
`worker_config_versions`, `worker_webhooks`, `worker_sessions`, `session_memory`,
`worker_templates`, `plans`, `tenant_plans`, `skill_definitions`, `execution_batches`; and the
columns `execution_runs.parent_execution_id` (RD-11), `execution_runs.batch_mode` /
`total_batches` / `completed_batches` (RD-12), `execution_runs.dry_run`.

---

### Implementation deviations of the S0–S11 repair (owner rulings R-AT, R-AU, R-AW, R-AZ, 2026-09-30)

The repair implements this schema as numbered SQL files (`adapters/postgres/migrations/001`…`010`, applied once each
by `main.py --migrate`; Alembic is not used). The following differences from the definitions above are **accepted**
and are the authoritative implementation. Everything not listed follows the text above. All tables listed as
tenant-scoped have forced row-level security on `app.current_tenant`.

| Migration | Difference from this document |
|---|---|
| 006 | `tenants.budget_period TEXT NOT NULL DEFAULT 'monthly' CHECK IN ('daily','weekly','monthly')`. `budget_reservations` as defined under "budget_reservations" (`created_at TIMESTAMPTZ`), with **no foreign keys** to `execution_runs` / `execution_steps` until the S12 reserve step adds them; one live (not released) reservation per step (010 adds the unique index). |
| 007 | `webhook_credentials` also carries `endpoint_id` (stable across rotation: the public part of the webhook URL and the pre-tenant lookup key), `workspace_id`, `user_id`, `membership_id`, `connection_id`, `resource_scope` (the fixed identity events run as, like `api_keys`); unique active/retiring indexes are on `(endpoint_id, source_system)`; **no row-level security** (pre-tenant lookup, ciphertext only; application role limited to SELECT/INSERT/UPDATE, credential reads to move to `system_worker_role` before production). `event_log` stores the raw payload in `payload BYTEA` (≤ 64 KiB) and uses `TIMESTAMPTZ` (`received_at`); it keeps `UNIQUE (tenant_id, idempotency_key)`. |
| 008 | `kernel_ops` gains `observation_method TEXT`, `observation_expects_absent BOOLEAN NOT NULL DEFAULT FALSE`, `observation_identifier_field TEXT`: the observation-method registry S12 entry needs to build verifiers (gate D1). A W/D/IRREVERSIBLE operation without `observation_method` cannot be run. |
| 009 | `execution_runs`, `execution_steps`, `execution_manifests`, `execution_plans`, `execution_ownership`, `state_transitions`, `operation_quotas`: times are `TIMESTAMPTZ` (not `REAL`); `execution_plans.frozen_bindings JSONB` (array of distinct bindings) and `step_binding_index JSONB` replace `frozen_binding_identity` (gate G4); `execution_manifests` also stores `auth_result_id`; no foreign keys to `workers`, `worker_leases` or `worker_versions` (not created yet) and none from `budget_reservations`; `operation_quotas` has no `worker_id` column (its own CHECK forced it NULL); `state_transitions` is the minimal transition log of gate C24 (`entity_type`, `entity_id`, `from_state`, `to_state`, `reason`, `runtime_instance_id`, `fence_token`); `execution_manifests` and `execution_plans` reject UPDATE by trigger. |
| 010 | `execution_runs.connection_id TEXT` (the live authorization check needs the run's connection) and `terminal_reason TEXT` (why a run was cancelled); `execution_steps.terminal_reason` (closed set, CHECK, immutable once written) and `dispatched_attempt`; `CHECK (status NOT IN ('cancelled','skipped') OR terminal_reason IS NOT NULL)`. |

## 4. Migrations

### Migration Naming Convention

```
NNN_description.sql
```

Where NNN is a zero-padded sequence number (001, 002, ...).

### Migration Files

| File | Purpose |
|------|---------|
| `001_initial.sql` | Create all tables |
| `002_kernel_ops.sql` | Populate kernel_ops from YAML |
| `003_bindings.sql` | Populate bindings from YAML |
| `004_actions.sql` | Populate actions from YAML |
| `005_execution_runs.sql` | Canonical execution tables (execution_runs, execution_steps) |
| `006_execution_attempts.sql` | Execution attempts, provider call records |
| `007_leases.sql` | Execution leases, worker assignments |
| `008_event_ledger.sql` | Immutable execution event ledger |
| `009_checkpoints.sql` | Checkpoint/resume tables |
| `010_idempotency.sql` | Idempotency ledger |
| `011_confirmations.sql` | Confirmation tokens |
| `012_dead_letters.sql` | Dead letter queue |
| `013_provider_tokens.sql` | Encrypted token storage |
| `014_audit_log.sql` | Audit logging |
| `015_worker_versions.sql` | Worker version lifecycle tables |
| `016_worker_deployments.sql` | Worker runtime instance tracking |
| `017_execution_ownership.sql` | Execution ownership and fencing |
| `018_worker_management.sql` | Gate v10 C39: worker key types to `TEXT` (RD-1), management columns on `workers` (incl. `workspace_id`), `tenants`, `workspaces` (skipped if ruling R-P added them), `bindings.required_runtime_types`, `operation_quotas` with RLS |

> **Worker-management repair (gate v10 C39):** `018` is additive except for the RD-1 type changes, which are safe only while the affected tables are empty or hold text-compatible values; preflight items 15 and P3 report the actual state. The migration tool (Alembic or other) is decided by preflight item 11.

> **Note**: Migrations 005+ replace the older `005_executions.sql`, `006_checkpoints.sql`,
> `007_idempotency.sql` pattern. The canonical model uses `execution_runs` and
> `execution_steps` (not `executions` and `step_results`). The event ledger
> (`008_event_ledger.sql`) is append-only — no UPDATE or DELETE.

### Migration Runner

```python
class MigrationRunner:
    def __init__(self, db: Database):
        self._db = db

    def run(self) -> None:
        """Run all pending migrations."""
        with self._db.session() as session:
            # Create migrations table if not exists
            session.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL
                )
            """)

            # Get applied migrations
            applied = {row[0] for row in session.execute("SELECT version FROM migrations").fetchall()}

            # Run pending migrations
            for migration in self._get_pending_migrations():
                if migration.version in applied:
                    continue

                # Execute migration SQL via Alembic-style batch execution
                session.execute(migration.sql)

                session.execute(
                    "INSERT INTO migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, time.time())
                )
                logger.info(f"Migration {migration.version}: {migration.name}")

            session.commit()

    def _get_pending_migrations(self) -> list[Migration]:
        migrations = []
        for path in sorted(Path("db/migrations").glob("*.sql")):
            version = int(path.stem.split("_")[0])
            migrations.append(Migration(version=version, name=path.stem, sql=path.read_text()))
        return migrations
```

---

### Memory tables (ADR-14; memory phase, after S15 — **not created in S12–S15**)

Defined now so the memory phase starts from the decided layout (ADR-14 §3.1–§3.3, Part 3). No S12–S15 migration creates them (gate v10 §14).

```sql
CREATE EXTENSION IF NOT EXISTS vector;                    -- memory-phase migration only

CREATE TABLE memory_vectors (
    entry_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    worker_id TEXT REFERENCES workers(worker_id),        -- NULL = entry has no worker
    user_id TEXT REFERENCES users(user_id),              -- original principal; NULL = not user-specific
    layer TEXT NOT NULL CHECK (layer IN ('L2', 'L3')),
    session_id TEXT,                                     -- required for L2, forbidden for L3
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding vector NOT NULL,                           -- untyped column; typed per index below
    content_hash TEXT NOT NULL,
    payload JSONB,                                       -- inline up to memory_payload_inline_max_bytes
    payload_ref TEXT,                                    -- S3 key when larger (ADR-14 Part 3)
    source TEXT NOT NULL,
    confidence REAL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, entry_id),                   -- includes the partition key
    CHECK ((layer = 'L2') = (session_id IS NOT NULL)),
    CHECK (vector_dims(embedding) = embedding_dim),
    CHECK (payload IS NULL OR payload_ref IS NULL)
) PARTITION BY LIST (tenant_id);
CREATE TABLE memory_vectors_default PARTITION OF memory_vectors DEFAULT;
-- A tenant above the row-count threshold (settings object) gets its own partition:
--   CREATE TABLE memory_vectors_<tenant> PARTITION OF memory_vectors FOR VALUES IN ('<tenant_id>');
ALTER TABLE memory_vectors ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memory_vectors
    USING (tenant_id = current_setting('app.current_tenant')::text)
    WITH CHECK (tenant_id = current_setting('app.current_tenant')::text);
CREATE INDEX idx_memory_scope ON memory_vectors (tenant_id, workspace_id, worker_id, user_id, layer, session_id);
-- ANN index per partition and embedding model (the cast fixes the dimension), for example:
--   CREATE INDEX ON memory_vectors_default
--       USING hnsw ((embedding::vector(1536)) vector_cosine_ops) WHERE embedding_model = '<model>';

CREATE TABLE memory_tenant_keys (
    tenant_id TEXT PRIMARY KEY REFERENCES tenants(tenant_id),
    wrapped_dek BYTEA,                                   -- NULL once destroyed (crypto-shredding)
    kek_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    destroyed_at TIMESTAMPTZ,
    CHECK ((wrapped_dek IS NULL) = (destroyed_at IS NOT NULL))
);
ALTER TABLE memory_tenant_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memory_tenant_keys
    USING (tenant_id = current_setting('app.current_tenant')::text)
    WITH CHECK (tenant_id = current_setting('app.current_tenant')::text);
```

Rules: workspace, worker, user and session boundaries are enforced by the backend's predicates, not by RLS (ADR-14 §3.3 D2). The **erasure register** is deliberately **not** a table here: it is kept outside the database backups (ADR-14 §4a.4) so that a restore can replay it.

---

## 5. Backup & Restore

> **Retention bound (ADR-14 Q7, owner 2026-09-29):** every backup and archived WAL segment that can contain memory data is deleted within **90 days** (the erasure deadline). The logical dumps below keep 30 days; `pg_basebackup` backups and the WAL archive need the same ≤ 90-day bound. After any restore, the memory erasure register is replayed before the database serves traffic (ADR-14 §4a.4; RELIABILITY §15).

### PostgreSQL Native Backup

PostgreSQL 16 provides three native backup mechanisms. Use the appropriate one for each scenario.

### Full Physical Backup — pg_basebackup

```bash
# Full base backup (consistent snapshot)
pg_basebackup \
    -h localhost \
    -U replicator \
    -D /backups/base/$(date +%Y%m%d_%H%M%S) \
    -Ft -z -P \
    --wal-method=stream
```

### WAL Archiving for PITR

Configure in `postgresql.conf`:

```conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /archive/%f'
archive_timeout = 300
max_wal_size = 4GB
```

Restore to a point in time:

```bash
# 1. Stop PostgreSQL
pg_ctl stop -D /data/pgdata

# 2. Restore base backup
rm -rf /data/pgdata/*
tar -xzf /backups/base/20260920.tar.gz -C /data/pgdata

# 3. Create recovery.signal
touch /data/pgdata/recovery.signal

# 4. Configure recovery target
echo "restore_command = 'cp /archive/%f %p'" >> /data/pgdata/postgresql.conf
echo "recovery_target_time = '2026-09-20 14:30:00'" >> /data/pgdata/postgresql.conf

# 5. Start PostgreSQL (recovery runs automatically)
pg_ctl start -D /data/pgdata
```

### Logical Backup — pg_dump / pg_restore

```bash
# Full logical backup
pg_dump \
    -h localhost \
    -U postgres \
    -d supr \
    -F c \
    -f /backups/supr_$(date +%Y%m%d).dump \
    --jobs=4 \
    --compress=6

# Restore
pg_restore \
    -h localhost \
    -U postgres \
    -d supr_restore \
    -F c \
    /backups/supr_20260920.dump \
    --jobs=4 \
    --clean \
    --if-exists
```

### Automated Backup Script

```bash
#!/bin/bash
# /etc/cron.daily/postgres-backup
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups/logical"
mkdir -p $BACKUP_DIR

# Logical backup of all databases
pg_dumpall -h localhost -U postgres -f $BACKUP_DIR/all_$DATE.sql

# Per-database compressed backup
pg_dump -h localhost -U postgres -d supr -F c -f $BACKUP_DIR/supr_$DATE.dump

# Retain last 30 days
find $BACKUP_DIR -name "*.dump" -mtime +30 -delete
find $BACKUP_DIR -name "*.sql" -mtime +30 -delete
```

### Backup Verification

```bash
# Verify dump integrity
pg_restore --list /backups/supr_20260920.dump | head

# Verify base backup WAL completeness
pg_verifybackup /backups/base/20260920/
```

---

## 6. Data Seeding

### Seed Data

```sql
-- Seed tenants
INSERT INTO tenants (tenant_id, name, is_active, created_at, updated_at)
VALUES ('default', 'Default Tenant', 1, extract(epoch from now()), extract(epoch from now()));

-- Seed admin user
INSERT INTO users (user_id, tenant_id, username, display_name, is_active, max_risk, granted_capabilities, scopes, created_at, updated_at)
VALUES ('admin', 'default', 'admin', 'Administrator', 1, 'IRREVERSIBLE', '[]', '["global"]', extract(epoch from now()), extract(epoch from now()));

-- Seed default workspace
INSERT INTO workspaces (workspace_id, tenant_id, name, is_active, created_at, updated_at)
VALUES ('default', 'default', 'Default Workspace', 1, extract(epoch from now()), extract(epoch from now()));

-- Seed default connection
INSERT INTO connections (connection_id, user_id, tenant_id, workspace_id, is_active, created_at)
VALUES ('default', 'admin', 'default', 'default', 1, extract(epoch from now()));
```

### Seeding Script

```python
def seed_database(db: Database) -> None:
    """Seed initial data if database is empty."""
    with db.session() as session:
        # Check if already seeded
        tenant_count = session.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        if tenant_count > 0:
            logger.info("Database already seeded")
            return

        # Run seed SQL via Alembic migration
        migration_sql = Path("db/seeds/initial.sql").read_text()
        for statement in migration_sql.split(';'):
            statement = statement.strip()
            if statement:
                session.execute(statement)

        session.commit()
        logger.info("Database seeded")
```

---

## 7. Queries & Performance

### Query Patterns

```python
class DatabaseQueries:
    """Common query patterns with proper parameterization."""

    def __init__(self, db: Database):
        self._db = db

    def get_kernel_ops_by_provider(self, provider: str) -> list[dict]:
        with self._db.session() as session:
            return session.execute(
                "SELECT * FROM kernel_ops WHERE provider = :provider AND is_implemented = 1",
                {"provider": provider}
            ).fetchall()

    def get_eligible_bindings(self, capability_id: str) -> list[dict]:
        """Returns all eligible bindings for a capability.
        Provider is resolved by selection algorithm, not provided by caller."""
        with self._db.session() as session:
            return session.execute(
                """SELECT * FROM bindings
                   WHERE capability_id = :capability_id AND is_active = 1
                   ORDER BY priority ASC""",
                {"capability_id": capability_id}
            ).fetchall()

    def select_binding(self, eligible_bindings: list[dict]) -> dict:
        """Deterministic selection: lowest priority wins.
        Requires at least one eligible binding."""
        if not eligible_bindings:
            raise ValueError("No eligible bindings for selection")
        return sorted(eligible_bindings, key=lambda b: b["priority"])[0]

    def get_user(self, user_id: str) -> dict | None:
        with self._db.session() as session:
            return session.execute(
                "SELECT * FROM users WHERE user_id = :user_id AND is_active = 1",
                {"user_id": user_id}
            ).fetchone()

    def reserve_budget(self, tenant_id: str, cost: int) -> bool:
        """Atomically reserve budget for a tenant. Returns True if successful.

        BUDGET-001 fix: Uses tenant_id (not user_id) for budget ownership.
        The source of truth is tenants.budget_pool, not users.budget_remaining.
        """
        with self._db.session() as session:
            result = session.execute(
                "UPDATE tenants SET budget_pool = budget_pool - :cost "
                "WHERE tenant_id = :tid AND budget_pool >= :cost",
                {"cost": cost, "tenant_id": tenant_id}
            )
            return result.rowcount > 0

    def get_execution(self, execution_id: str) -> dict | None:
        with self._db.session() as session:
            return session.execute(
                "SELECT * FROM execution_runs WHERE execution_id = :execution_id",
                {"execution_id": execution_id}
            ).fetchone()

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        with self._db.session() as session:
            session.execute(
                """INSERT INTO checkpoints
                   (checkpoint_id, execution_id, plan_id, completed_steps,
                    failed_steps, pending_steps, current_step, context_snapshot,
                    created_at, expires_at)
                   VALUES (:checkpoint_id, :execution_id, :plan_id, :completed_steps,
                           :failed_steps, :pending_steps, :current_step, :context_snapshot,
                           :created_at, :expires_at)""",
                {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "execution_id": checkpoint.execution_id,
                    "plan_id": checkpoint.plan_id,
                    "completed_steps": json.dumps(checkpoint.completed_steps),
                    "failed_steps": json.dumps(checkpoint.failed_steps),
                    "pending_steps": json.dumps(checkpoint.pending_steps),
                    "current_step": checkpoint.current_step,
                    "context_snapshot": json.dumps(checkpoint.context_snapshot),
                    "created_at": checkpoint.created_at,
                    "expires_at": checkpoint.expires_at,
                }
            )

    def cleanup_expired(self) -> None:
        """Clean up expired records."""
        import time
        now = time.time()
        with self._db.session() as session:
            # Expired checkpoints
            session.execute("DELETE FROM checkpoints WHERE expires_at < :now", {"now": now})
            # Expired confirmations
            session.execute("UPDATE pending_confirmations SET status = 'expired' WHERE expires_at < :now AND status = 'pending'", {"now": now})
            # Expired idempotency keys
            session.execute("DELETE FROM idempotency_ledger WHERE expires_at < :now", {"now": now})

### Performance Rules

| Rule | Implementation |
|------|---------------|
| Use indexes | Every foreign key has an index |
| Parameterize queries | Never string-concatenate SQL |
| Pre-load data | Cache bindings and capabilities before execution |
| Clean up regularly | Delete expired checkpoints, idempotency keys, audit logs |
| Analyze periodically | Run `ANALYZE` after bulk changes |
| Vacuum periodically | Run `VACUUM` after large deletions |

---

## 8. Connection Pool Governance

### Pool Configuration

PostgreSQL 16 connection parameters, tuned for multi-tenant workloads:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `max_connections` | 200 | PostgreSQL server limit |
| `application_pool_size` | 100 | Total application pool across all services |
| `reserved_for_system` | 20 | Superuser, monitoring, maintenance connections |
| `per_service_pool` | 20 | Each service (API, worker, scheduler) gets its own pool |
| `per_tenant_pool` | 5 | Isolation pool per active tenant |
| `connection_timeout` | 5s | Fail fast if pool is exhausted |
| `statement_timeout` | 30s | Prevent runaway queries |
| `idle_in_transaction_timeout` | 10s | Kill idle-in-transaction sessions |
| `lock_timeout` | 5s | Fail fast on lock contention |

```python
# Application pool configuration per service
SERVICE_POOL_CONFIGS = {
    "api": {"pool_size": 20, "max_overflow": 10},
    "worker": {"pool_size": 20, "max_overflow": 10},
    "scheduler": {"pool_size": 10, "max_overflow": 5},
}

# Per-tenant pool (via pgbouncer transaction pooling)
TENANT_POOL_CONFIG = {
    "pool_size": 5,
    "reserve_pool_size": 2,
    "max_db_connections": 10,
    "server_lifetime": 3600,
}
```

### Transaction Budget

| Budget | Limit | Action on Exceed |
|--------|-------|-----------------|
| Max concurrent DB operations per execution | 10 | Queue or reject |
| Max total DB time per execution | 60s | Cancel execution |
| Max retry on deadlock | 3 | Escalate to DLQ |

```python
class TransactionBudget:
    """Track and enforce DB resource consumption per execution."""

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.db_operations = 0
        self.total_db_time_ms = 0
        self.deadlock_retries = 0

    def check(self, operation_cost: int = 1) -> None:
        if self.db_operations + operation_cost > 10:
            raise BudgetExhausted(f"Max DB operations (10) exceeded for {self.execution_id}")
        self.db_operations += operation_cost

    def record_db_time(self, ms: float) -> None:
        self.total_db_time_ms += ms
        if self.total_db_time_ms > 60000:
            raise BudgetExhausted(f"Max DB time (60s) exceeded for {self.execution_id}")
```

### DB Exhaustion Behavior

When the connection pool is exhausted:

1. **Connection timeout** (5s): Request waits for a free connection
2. **Pool overflow**: Borrowed connections up to `pool_size + max_overflow` total
3. **Hard limit**: If all connections are in use, raise `PoolExhausted` immediately
4. **Circuit breaker**: If exhaustion rate > 10% over 60s, reject new requests with 503
5. **Graceful degradation**: Non-critical queries (audit log, metrics) are dropped first

```python
from sqlalchemy.exc import PoolExhausted

@retry(max_retries=2, backoff=exponential)
def execute_with_fallback(session, query, fallback=None):
    try:
        return session.execute(query)
    except PoolExhausted:
        if fallback:
            return fallback()
        raise ServiceUnavailable("Database pool exhausted")
```

> **Note**: PostgreSQL 16 is the only production database. SQLite exists only in `tests/`, `local-dev/`, and `isolated-unit-tests/`.

---

## 9. Row-Level Security (RLS) Policies

**Purpose**: Enforce tenant isolation at the database level. Every query is filtered by `tenant_id` automatically.

### Policy Definition

```sql
-- Enable RLS on all tenant-scoped tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_confirmations ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letters ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE capability_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE retry_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE operation_quotas ENABLE ROW LEVEL SECURITY;   -- gate v10 C39 (RD-3)
```

### Policy Templates

```sql
-- Generic tenant-isolation policy (uses current_setting)
CREATE POLICY tenant_isolation ON users
    FOR ALL TO application_role
    USING (tenant_id = current_setting('app.current_tenant')::text);

-- Worker-management repair (RD-3, gate v10 C39): same pattern for operation_quotas
CREATE POLICY tenant_isolation ON operation_quotas
    FOR ALL TO application_role
    USING (tenant_id = current_setting('app.current_tenant')::text)
    WITH CHECK (tenant_id = current_setting('app.current_tenant')::text);

-- Audit reader: specific immutable audit access only
CREATE POLICY audit_read ON audit_log
    FOR SELECT TO audit_reader
    USING (true);
```

### Canonical Roles (Exactly Three)

```sql
-- 1. Application role: tenant-scoped operations only
CREATE ROLE application_role;

-- 2. System worker role: controlled internal operations (scheduler, heartbeats, leases)
CREATE ROLE system_worker_role;

-- 3. Audit reader: specific immutable audit access
CREATE ROLE audit_reader;
GRANT SELECT ON audit_log TO audit_reader;
```

**Rules**:
1. `application_role` can NEVER bypass tenant isolation
2. `system_worker_role` can ONLY perform documented internal operations (worker heartbeats, lease management, scheduler ticks, and — SEC-HMAC — SELECT of active/retiring `webhook_credentials` rows for webhook signature verification before a tenant context exists)
3. `audit_reader` can ONLY SELECT from `audit_log` — no other grants
4. The `admin_override` and `admin_role` patterns are REMOVED
5. The cross-tenant read policy is REMOVED
6. Every privileged operation MUST produce an audit event
7. No role can grant itself additional permissions

### Application Role Setup

```sql
-- Create application roles
CREATE ROLE application_role;
CREATE ROLE system_worker_role;
CREATE ROLE audit_reader;

-- application_role: full tenant-scoped CRUD
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO application_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO application_role;

-- system_worker_role: limited to documented internal operations
-- (specific grants defined per table as needed)
GRANT USAGE ON SCHEMA public TO system_worker_role;

-- audit_reader: read-only audit access
GRANT SELECT ON audit_log TO audit_reader;
```

### Session Variable Pattern

```python
class Database:
    """Singleton database connection manager using SQLAlchemy."""

    def session(self, tenant_id: str | None = None):
        """Get a database session with tenant context set."""
        session = self._SessionFactory()
        if tenant_id:
            # Set tenant context for RLS — MUST be set before any queries
            session.execute(
                "SET LOCAL app.current_tenant = :tenant_id",
                {"tenant_id": tenant_id}
            )
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

**Rules**:
1. `current_setting('app.current_tenant')` is set on every session before queries
2. `tenant_id` is taken from `ExecutionContext.tenant_id`, never from user input
3. `system_worker_role` performs only documented internal operations via explicit policies
4. Every table with `tenant_id` MUST have RLS enabled
5. RLS is enforced at the PostgreSQL level — application bugs cannot bypass it

---

## 10. Checkpoint & Recovery

### Checkpoint Model

```sql
-- checkpoint_steps tracks which steps are done/failed/pending per checkpoint
CREATE TABLE checkpoint_steps (
    checkpoint_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    status TEXT NOT NULL,        -- completed, failed, pending
    result TEXT,                 -- JSON result
    error TEXT,
    PRIMARY KEY (checkpoint_id, step_id),
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id),
    FOREIGN KEY (step_id) REFERENCES execution_steps(step_id)
);
```

### Recovery Flow

> **S12–S15 gate v9 repair (C33, ADR-7):** the earlier flow (restore context from the checkpoint, re-resolve bindings, re-reserve budget) is superseded. Re-resolving bindings violates I-002/I-010 and ADR-7; re-reserving would double-count budget. The normative recovery is S12_S15_EXECUTION_GATE §13:

```
1. Sweeper finds a running/reconciling run whose ownership lease expired
   (FOR UPDATE SKIP LOCKED)
2. Take ownership: new lease (token from fence_token_seq) + execution_ownership CAS
3. Reload the plan and frozen binding from execution_plans; verify the digest
4. LiveAuthorizationCheck (revocations, binding/credential validity)
5. Resolve the in-flight step: open episode → ledger → dispatch marker → probe
   (never a blind re-execution; existing reservation reused)
6. Continue from the first pending step
```

### Lease-Based Recovery

> **S12–S15 gate v9 repair (C5):** `execution_leases` is a duplicate of `worker_leases` and is not used. `worker_leases` is the lease of record.

```sql
CREATE TABLE execution_leases (
    lease_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    renewed_at REAL,
    status TEXT NOT NULL DEFAULT 'active',  -- active, expired, released
    FOREIGN KEY (execution_id) REFERENCES execution_runs(execution_id)
);
CREATE INDEX idx_leases_execution ON execution_leases(execution_id);
CREATE INDEX idx_leases_worker ON execution_leases(worker_id);
CREATE INDEX idx_leases_expires ON execution_leases(expires_at);
```

---

## 11. PostgreSQL WAL & Write Barriers

### WAL Configuration

PostgreSQL 16 WAL (Write-Ahead Log) provides crash safety and replication. Configure in `postgresql.conf`:

```conf
# WAL settings
wal_level = replica
wal_log_hints = on
full_page_writes = on
wal_buffers = 64MB
wal_writer_delay = 200ms
wal_writer_flush_after = 1MB

# Checkpoint settings
checkpoint_completion_target = 0.9
max_wal_size = 4GB
min_wal_size = 1GB

# Replication for HA
max_wal_senders = 10
wal_keep_size = 1GB
```

### Write Barrier Pattern

```python
class WriteBarrier:
    """Ensure related writes are atomic."""

    def __init__(self, db: Database):
        self._db = db

    def write_execution_with_steps(self, execution: Execution, steps: list[Step]) -> None:
        """Write execution and all steps atomically."""
        with self._db.session() as session:
            # 1. Write execution
            session.execute(INSERT_EXECUTION, execution.to_dict())

            # 2. Write all steps
            for step in steps:
                session.execute(INSERT_STEP, step.to_dict())

            # 3. Write checkpoint
            session.execute(INSERT_CHECKPOINT, self._build_checkpoint(execution, steps))

            # All-or-nothing: if any write fails, NONE are committed
```

### PostgreSQL-Specific Durability

```sql
-- Synchronous replication for durability
SET synchronous_commit = on;  -- Wait for WAL flush before ACK

-- Two-phase commit for distributed transactions
BEGIN;
PREPARE TRANSACTION 'tx_name';
-- ... operations ...
COMMIT PREPARED TRANSACTION 'tx_name';
```

---

## 12. Index Strategy

### Required Indexes

| Table | Index | Purpose |
|-------|-------|---------|
| `execution_runs` | `(tenant_id, created_at)` | Tenant execution history queries |
| `execution_runs` | `(actor_type, actor_id, created_at)` | Worker execution history |
| `execution_steps` | `(execution_id, step_index)` | Step ordering per execution |
| `budget_reservations` | `(tenant_id, status)` | Budget queries |
| `dead_letters` | `(resolved, next_retry_at)` | DLQ polling |
| `checkpoints` | `(execution_id, created_at)` | Checkpoint recovery |
| `retry_log` | `(provider, operation, timestamp)` | Retry analysis |
| `operation_quotas` | `(tenant_id, resource_type, period_start, period_end)` | Quota lookup at durable admission (C39) |
| `workers` | `(assigned_user_id)` partial, where not NULL | Assignment filter (C39) |

---

## 13. Data Integrity Rules

### NOT NULL Constraints

| Table | Column | Reason |
|-------|--------|--------|
| `execution_runs` | `tenant_id` | Tenant isolation |
| `execution_runs` | `actor_type` | Auditing |
| `execution_runs` | `actor_id` | Auditing |
| `execution_steps` | `kernel_op_id` | Traceability |
| `execution_steps` | `resolved_binding_id` | Binding audit |
| `budget_reservations` | `tenant_id` | Budget isolation |
| `operation_quotas` | `tenant_id` | Tenant isolation (C39, RD-3) |
| `workers` | `runtime_type` | Eligibility filter 17 (C39) |

### Cascading Rules

| Parent | Child | Action |
|--------|-------|--------|
| `execution_runs` | `execution_steps` | CASCADE DELETE |
| `execution_runs` | `checkpoints` | CASCADE DELETE |
| `execution_runs` | `dead_letters` | CASCADE DELETE |
| `execution_runs` | `budget_reservations` | RESTRICT (prevent accidental deletion) |

### Budget Constraint

| Constraint | Rule |
|------------|------|
| `budget_reservations.cost` (per step) | Σ cost of the tenant's live reservations in the current period MUST be <= `tenants.budget_pool` (gate C3, invariant I1) |
| Enforcement | Atomic UPDATE with WHERE clause (see `reserve_budget` in §7) |

### Operation Quota Constraint

| Constraint | Rule |
|------------|------|
| `operation_quotas.used_count` | `0 <= used_count <= limit_value` on every row (gate v10 C39, invariant I17) |
| Enforcement | `CHECK (used_count <= limit_value)`; conditional UPDATE `... AND used_count < limit_value RETURNING` in the durable-admission transaction; an admin UPDATE lowering `limit_value` below `used_count` fails; no `ON DELETE CASCADE` from any parent |
| `operation_quotas.worker_id` | Must be NULL in this phase (`CHECK (worker_id IS NULL)`) |

---

## 14. Testing Database

### Test Database Setup

```python
@pytest.fixture
def test_db():
    """In-memory SQLite for tests."""
    db = Database(":memory:")
    db.run_migrations()
    db.seed()
    yield db
    db.drop_all()

def test_budget_reserve(test_db):
    result = test_db.budget.reserve(
        tenant_id="test-tenant",
        user_id="test-user",
        execution_id="exec-1",
        step_id="step-1",
        cost=5
    )
    assert result.allowed is True
```

> **S12–S15 gate v9 repair (C33):** in-memory SQLite is not acceptable for any lease, budget, fencing, confirmation, recovery or concurrency test (gate §15.1): those run against real PostgreSQL 16 (`TEST_DATABASE_URL`), in a schema created and dropped per test module.

### Test Data Rules

1. Use in-memory SQLite for unit tests
2. Use dedicated test database for integration tests
3. Each test starts with clean database (fixture)
4. Never depend on test execution order
5. Use factory fixtures for test data

---

## 15. Monitoring & Alerts

### Database Metrics

| Metric | Query | Alert Threshold |
|--------|-------|-----------------|
| Connection pool usage | `SELECT count(*) FROM pg_stat_activity` | > 80% |
| Long-running queries | `SELECT * FROM pg_stat_activity WHERE state = 'active' AND now() - query_start > interval '30 seconds'` | Any |
| Table bloat | `pgstattuple` extension | > 20% |
| Index usage | `pg_stat_user_indexes` | < 90% scans |
| Dead tuples | `pg_stat_user_tables` | > 10k |
| Replication lag | `pg_stat_replication` | > 5s |

### Alerting Rules

| Condition | Severity | Action |
|-----------|----------|--------|
| Connection pool > 80% | Warning | Scale up or investigate |
| Query > 30s | Warning | Log and investigate |
| Replication lag > 5s | Critical | Failover or fix network |
| Table bloat > 20% | Warning | Schedule VACUUM |

---

*End of Database.*
