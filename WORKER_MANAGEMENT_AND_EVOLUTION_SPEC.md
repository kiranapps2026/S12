# Worker Management & Evolution Specification

**Version**: 1.1.0
**Status**: PROPOSED — pending owner review before propagation to master documents
**Date**: 2026-09-29
**Purpose**: Single consolidated reference for all worker-level features, future evolution paths, and document changes. This document does NOT modify any master document. After owner review, changes are propagated to the authoritative docs (`FINAL_ARCHITECTURE.md`, `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md`, `S12_S15_EXECUTION_GATE.md`, `S12_S15_IMPLEMENTATION_PLAN.md`, `S12_SESSION0_PREFLIGHT_PROMPT.md`).

**Rule**: Nothing in this document modifies S0–S11 certified artifacts. All changes are additive.

---

## Table of Contents

1. [Complete Feature Inventory](#1-complete-feature-inventory)
2. [New Database Schema](#2-new-database-schema)
3. [Admission Gates G12–G17](#3-admission-gates-g12g17)
4. [Batch Processing](#4-batch-processing)
5. [Document Change Specification](#5-document-change-specification)
6. [Future Evolution Roadmap](#6-future-evolution-roadmap)
7. [Seven-Layer Architecture Invariant](#7-seven-layer-architecture-invariant)
8. [Browser/RPA Execution Path](#8-browserrpa-execution-path)
9. [S0–S11 Protection List](#9-s0s11-protection-list)
10. [Implementation Sequence](#10-implementation-sequence)

---

## 1. Complete Feature Inventory

### P0 — Blocking for S12 install (must land before M0)

| ID | Feature | Type | Description |
|----|---------|------|-------------|
| F0 | Execution tree visibility | New column | `execution_runs.parent_execution_id` — enables supervisor pattern traceability |
| F1 | Worker config store | New column | `workers.settings` JSONB — skills prompt, business rules, restricted capabilities, execution policy, LLM preference |
| F2 | Timestamp pause | New column + gate | `workers.paused_until` DateTime nullable — admission blocks new work while set |
| F3 | Scheduled activation | New column + gate | `workers.scheduled_activation_at` DateTime nullable — worker stays dormant until this time |
| F4 | Three-level timestamp hierarchy | Gate extension | Tenant `settings.paused_until`, workspace `settings.paused_until`, worker `paused_until` — most-restrictive-wins |
| F5 | Employee assignment | New column + gate | `workers.assigned_user_id` UUID FK nullable — REJECT if different user tries to use it |
| F6 | Operations quota | New table + gate | `operation_quotas` — count-based quota per tenant/workspace/worker; hard=REJECT, soft=QUEUE+upgrade prompt |
| F7 | Sub-agent spawning | New columns + table + gate | `max_sub_agents`, `parent_worker_id`, `depth_level`, `WorkerSpawnAudit` table |
| F8 | Worker type enforcement | New gate | G17 validates execution type matches worker type (standard/event/hybrid) using existing `WorkerSubscription` |
| F9 | Batch processing | New table + S1/S12 logic | `execution_batches` — split large payloads in S1, execute in parallel in S12, consolidate results |
| F31 | Replanning checkpoint | S12 logic | Checkpoint-driven replanning — S12 can replace the execution plan at any checkpoint without kernel changes |

### P1 — Before marketplace launch (competitive differentiation)

| ID | Feature | Type | Description |
|----|---------|------|-------------|
| F10 | Worker config versioning | New table | `worker_config_versions` — every settings save creates versioned snapshot; rollback support |
| F11 | Worker execution analytics | Read-side aggregation | Per-worker success rate, latency, cost, failure breakdown from ledger data |
| F12 | Tool/capability deny-list | Settings JSONB key | `settings.restricted_capabilities` — blocks specific mutation types within allowed capabilities |
| F13 | Dry-run / test mode | ExecutionContext flag | `dry_run` bool — test execution with synthetic responses, no side effects |
| F14 | Model selection resolution chain | Runtime logic | tenant.allowed_models → workspace.allowed_models → worker.settings.llm_model; fallback if overridden model is removed |
| F15 | Worker state-change webhooks | New table | `worker_webhooks` — dispatch webhook on state transitions and execution events |
| F16 | Per-worker execution policy | Settings JSONB key | `settings.execution_policy` — per-worker timeout, max_retries, backoff, circuit breaker threshold |
| F17 | Worker groups | New tables | `worker_groups` + `worker_group_members` — bulk pause/resume/schedule/assign |
| F18 | L2 session memory | New tables | `worker_sessions` + `session_memory` — conversation history scoped to worker-user pairs |
| F19 | Heterogeneous workers | New column + routing | `workers.runtime_type` — LLM, rules, vision, browser, data, rag, code, human; pipeline path selection |
| F20 | Progressive autonomy | CapabilityGrant extension | `autonomy_level` per grant — observed, assisted, limited, expanded, high_trust; capability-specific, not global |
| F32 | Browser/RPA execution path | New path B0–B7 | Parallel lightweight path that bypasses S0–S11. Shares worker lifecycle and execution kernel. Own entry point, adapter, verification. |
| F33 | Capability composition (Skills) | New tables + S7 logic | `SkillDefinition` + `SkillStep` — business-level capabilities composed from kernel operations. Admin creates skills as DAGs of existing capabilities. |
| F34 | Browser adapter facade | New adapter class | `BrowserAdapter` with pluggable providers: Playwright (default), Apify (scale), BrowserUse (AI-driven). Provider selection transparent to kernel. |
| F35 | Browser session pool | New class | Manages browser instances per tenant — pool, concurrency, cleanup, cookie/auth state persistence |
| F36 | Browser verification (S13) | New verifier class | Screenshot comparison, DOM inspection, data extraction validation — plugs into existing S13 flow |

### P2 — Enterprise features (post-S15)

| ID | Feature | Type | Description |
|----|---------|------|-------------|
| F21 | Memory classification | New column | `memory_classification` on memory store — episodic, semantic, procedural, organizational, execution, relationship, policy |
| F22 | Policy-as-a-runtime | New class + layers | `PolicyEngine` with 8-layer evaluation chain; context-aware (time, location, data classification, compliance) |
| F23 | Environment independence | Documentation + deployment descriptor | Runtime Contract enforcement across local, Docker, VM, K8s, serverless, edge, on-prem |
| F24 | Event evolution | Event Gateway extensions | Ordering, causality tracking, replay, event versioning, correlation, dead-lettering for events |
| F25 | Worker templates | New table | `worker_templates` — clone worker config for fast creation from blueprints |
| F26 | Plan-based entitlements | New tables | `plans` + `tenant_plan` — Starter/Pro/Enterprise with configurable quota templates |
| F27 | Worker marketplace listing | Settings JSONB key | `is_listed` bool + `listing_config` JSONB — discoverability via existing WorkerSubscription |

### P3 — Future (roadmap, no implementation commitment)

| ID | Feature | Type | Description |
|----|---------|------|-------------|
| F28 | Multi-agent supervisor pattern | Enabled by parent_execution_id + sub-agent spawning + F32 | Supervisor delegates to child workers (API, browser, vision); execution tree visible in kernel |
| F29 | Advanced A2A protocols | Extension of existing A2A | Task handoffs, concurrent handoff logs (already adopted from CrewMeld/AgentsMesh) |
| F30 | Agentic strategies | Pipeline routing | AGENTIC, BATCH, PLAN_EXECUTE, HUMAN_ASSISTED execution strategies (stubbed in M0, activated later) |

---

## 2. New Database Schema

### 2.1 Workers table — additive columns

```sql
ALTER TABLE workers ADD COLUMN settings JSONB NOT NULL DEFAULT '{}';
ALTER TABLE workers ADD COLUMN assigned_user_id UUID REFERENCES users(user_id);
ALTER TABLE workers ADD COLUMN paused_until TIMESTAMPTZ;
ALTER TABLE workers ADD COLUMN scheduled_activation_at TIMESTAMPTZ;
ALTER TABLE workers ADD COLUMN max_sub_agents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workers ADD COLUMN parent_worker_id UUID REFERENCES workers(worker_id);
ALTER TABLE workers ADD COLUMN depth_level INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workers ADD COLUMN runtime_type TEXT NOT NULL DEFAULT 'llm';  -- F19: llm, rules, vision, browser, rpa, data, rag, code, human
```

### 2.2 Execution runs table — additive columns

```sql
ALTER TABLE execution_runs ADD COLUMN parent_execution_id UUID REFERENCES execution_runs(execution_id);
ALTER TABLE execution_runs ADD COLUMN batch_mode BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE execution_runs ADD COLUMN total_batches INTEGER;
ALTER TABLE execution_runs ADD COLUMN completed_batches INTEGER NOT NULL DEFAULT 0;
ALTER TABLE execution_runs ADD COLUMN dry_run BOOLEAN NOT NULL DEFAULT FALSE;  -- F13
```

### 2.3 New table: operation_quotas

```sql
CREATE TABLE operation_quotas (
    quota_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    workspace_id UUID REFERENCES workspaces(workspace_id),
    worker_id UUID REFERENCES workers(worker_id),
    resource_type TEXT NOT NULL,          -- 'executions', 'api_calls', 'sub_agents', 'browser_sessions'
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    limit_value INTEGER NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    is_hard BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_quotas_tenant_resource ON operation_quotas(tenant_id, resource_type, period_start, period_end);
CREATE INDEX idx_quotas_workspace ON operation_quotas(workspace_id);
CREATE INDEX idx_quotas_worker ON operation_quotas(worker_id);
```

### 2.4 New table: execution_batches

```sql
CREATE TABLE execution_batches (
    batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES execution_runs(execution_id),
    batch_number INTEGER NOT NULL,
    input_slice JSONB NOT NULL,
    result JSONB,
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, RUNNING, SUCCESS, FAILED, DEAD_LETTER
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_batches_execution ON execution_batches(execution_id, batch_number);
CREATE INDEX idx_batches_status ON execution_batches(status);
```

### 2.5 New table: worker_spawn_audit

```sql
CREATE TABLE worker_spawn_audit (
    spawn_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_worker_id UUID NOT NULL REFERENCES workers(worker_id),
    child_worker_id UUID NOT NULL REFERENCES workers(worker_id),
    depth_level INTEGER NOT NULL,
    budget_allocated DECIMAL NOT NULL,
    triggered_by TEXT NOT NULL,  -- 'user', 'system', 'scheduled'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_spawn_parent ON worker_spawn_audit(parent_worker_id);
CREATE INDEX idx_spawn_child ON worker_spawn_audit(child_worker_id);
```

### 2.6 New table: worker_groups

```sql
CREATE TABLE worker_groups (
    group_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    name TEXT NOT NULL,
    description TEXT,
    settings JSONB NOT NULL DEFAULT '{}',
    paused_until TIMESTAMPTZ,
    scheduled_activation_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE worker_group_members (
    group_id UUID NOT NULL REFERENCES worker_groups(group_id),
    worker_id UUID NOT NULL REFERENCES workers(worker_id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, worker_id)
);

CREATE INDEX idx_group_members_worker ON worker_group_members(worker_id);
```

### 2.7 New table: worker_config_versions

```sql
CREATE TABLE worker_config_versions (
    config_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id UUID NOT NULL REFERENCES workers(worker_id),
    settings JSONB NOT NULL,
    changed_by UUID NOT NULL REFERENCES users(user_id),
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_config_versions_worker ON worker_config_versions(worker_id, created_at);
```

### 2.8 New table: worker_webhooks

```sql
CREATE TABLE worker_webhooks (
    webhook_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    worker_id UUID REFERENCES workers(worker_id),
    url TEXT NOT NULL,
    events JSONB NOT NULL DEFAULT '[]',  -- ["state_change", "execution_failed", "execution_completed"]
    secret TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_webhooks_tenant ON worker_webhooks(tenant_id);
CREATE INDEX idx_webhooks_worker ON worker_webhooks(worker_id);
```

### 2.9 New table: worker_sessions (L2 memory)

```sql
CREATE TABLE worker_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id UUID NOT NULL REFERENCES workers(worker_id),
    user_id UUID NOT NULL REFERENCES users(user_id),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE session_memory (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES worker_sessions(session_id),
    content TEXT NOT NULL,
    embedding_id TEXT,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    memory_class TEXT NOT NULL DEFAULT 'episodic',  -- episodic, semantic, procedural
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sessions_worker_user ON worker_sessions(worker_id, user_id);
CREATE INDEX idx_session_memory_session ON session_memory(session_id);
```

### 2.10 New table: worker_templates

```sql
CREATE TABLE worker_templates (
    template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    name TEXT NOT NULL,
    description TEXT,
    worker_type TEXT NOT NULL,  -- 'standard', 'event', 'hybrid', 'browser', 'rpa', 'vision'
    settings JSONB NOT NULL DEFAULT '{}',
    capability_profile JSONB NOT NULL DEFAULT '[]',
    default_subscriptions JSONB NOT NULL DEFAULT '[]',
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_by UUID NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.11 New table: plans (entitlements)

```sql
CREATE TABLE plans (
    plan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,  -- 'free', 'starter', 'pro', 'enterprise'
    description TEXT,
    max_workers INTEGER NOT NULL,
    max_sub_agent_depth INTEGER NOT NULL DEFAULT 0,
    max_operations_per_month INTEGER NOT NULL,
    allowed_worker_types JSONB NOT NULL DEFAULT '["standard", "event", "hybrid"]',
    allowed_runtime_types JSONB NOT NULL DEFAULT '["llm"]',
    allowed_models JSONB NOT NULL DEFAULT '[]',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tenant_plans (
    tenant_plan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    plan_id UUID NOT NULL REFERENCES plans(plan_id),
    effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.12 New table: skill_definitions (capability composition)

```sql
CREATE TABLE skill_definitions (
    skill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    name TEXT NOT NULL,
    description TEXT,
    worker_type TEXT NOT NULL,           -- 'standard', 'event', 'browser', 'rpa', 'vision', 'hybrid'
    composition JSONB NOT NULL,          -- Array of SkillStep
    input_schema JSONB NOT NULL DEFAULT '{}',
    output_schema JSONB NOT NULL DEFAULT '{}',
    capabilities_required JSONB NOT NULL DEFAULT '[]',
    estimated_cost_units INTEGER NOT NULL DEFAULT 1,
    estimated_duration_seconds INTEGER NOT NULL DEFAULT 30,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_by UUID NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_skills_tenant ON skill_definitions(tenant_id);
CREATE INDEX idx_skills_worker_type ON skill_definitions(worker_type);
```

Where `composition` is a JSONB array of steps:

```json
[
    {
        "step_id": "step_1",
        "capability_id": "search_contact",
        "input_mapping": {"query": "{{input.search_term}}"},
        "output_mapping": {"contact_id": "result.contact_id"},
        "depends_on": [],
        "condition": null
    },
    {
        "step_id": "step_2",
        "capability_id": "retrieve_company",
        "input_mapping": {"company_name": "{{steps.step_1.result.company}}"},
        "output_mapping": {"company_data": "result"},
        "depends_on": ["step_1"],
        "condition": null
    }
]
```

---

## 3. Admission Gates G12–G17

Insert after existing G7 (worker capacity) in the admission sequence. All gates are stateless reads — no resource reservation.

### Gate ordering

```
G1  Kill switch               → system_halted
G2  Tenant quota              → tenant_quota_exceeded
G3  Tenant active             → tenant_inactive
G4  Workspace active          → workspace_inactive
G5  Execution mode allowed    → mode_not_allowed
G6  Provider allowed          → provider_blocked
G7  Worker capacity           → QUEUE (never REJECT)
─── NEW GATES START HERE ───
G12 Worker paused             → worker_paused
G13 Worker scheduled          → worker_not_yet_active
G14 Worker assigned           → not_assigned_to_you
G15 Sub-agent limit           → sub_agent_limit_reached
G16 Operation quota           → quota_exhausted
G17 Worker capability match   → capability_mismatch
G8  Provider circuit          → provider_circuit_open
G9  DB pool utilization       → db_pool_pressure
G10 Budget remaining          → budget_exhausted
G11 System load               → system_overloaded
```

### G12 — worker_paused

**Check:** `paused_until > now()` evaluated across four levels:
- Tenant: `tenants.settings.paused_until`
- Workspace: `workspaces.settings.paused_until`
- Worker group: `worker_groups.paused_until` (if worker is a member of a group)
- Worker: `workers.paused_until`

**Logic:** `effective_paused_until = MAX(tenant_paused, workspace_paused, group_paused, worker_paused)` where NULL means "not paused." If `effective_paused_until > now()`, REJECT with `worker_paused`.

**Bypass:** Tenant admins (TENANT_ADMIN, TENANT_OWNER roles) bypass G12.

### G13 — worker_scheduled

**Check:** `scheduled_activation_at > now()` evaluated across three levels (tenant, workspace, worker).

**Logic:** If `effective_activation_at > now()`, worker is not yet active. REJECT with `worker_not_yet_active`. Worker in `REGISTERED` state stays dormant until all timestamps are in the past.

**Bypass:** Tenant admins bypass G13.

### G14 — worker_assigned

**Check:** `workers.assigned_user_id` matches the requesting user's `user_id`.

**Logic:**
- `assigned_user_id IS NULL` → PASS (unassigned workers accept any tenant user)
- `assigned_user_id = requesting_user_id` → PASS
- `assigned_user_id != requesting_user_id` → REJECT with `not_assigned_to_you`

**Bypass:** Tenant admins (TENANT_ADMIN, TENANT_OWNER) bypass G14.

### G15 — sub_agent_limit

**Check:** Enforced only on sub-agent spawn paths, not on normal execution paths.

**Logic:**
- Count current children: `SELECT COUNT(*) FROM workers WHERE parent_worker_id = :parent_id`
- If `child_count >= workers.max_sub_agents` → REJECT with `sub_agent_limit_reached`
- If `parent.depth_level + 1 >= tenant_settings.max_depth` → REJECT with `max_depth_exceeded`
- Both checks must pass for spawn to proceed

**Enforcement at spawn time:** The `spawn_child_worker()` function (M12.5) writes `WorkerSpawnAudit` row atomically with worker creation. If the audit write fails (constraint violation), the spawn is rolled back.

### G16 — operation_quota

**Check:** `operation_quotas` table for the tenant (and workspace/worker if applicable).

**Logic:**
- Query: `SELECT used_count, limit_value, is_hard FROM operation_quotas WHERE tenant_id = :tid AND resource_type = :rtype AND period_start <= now() AND period_end >= now()`
- If no row exists → PASS (no quota configured for this resource type)
- If `used_count >= limit_value` and `is_hard = TRUE` → REJECT with `quota_exhausted`
- If `used_count >= limit_value` and `is_hard = FALSE` → QUEUE with `retry_after_ms` and `upgrade_prompt` pointing to plan upgrade
- If `used_count < limit_value` → PASS (increment happens on execution completion, not at admission)

**Increment on completion:** After S13 verification passes, the execution service atomically increments `used_count` in `operation_quotas`. This happens in the same transaction as the step result commit.

**Batch counting:** Each batch counts as 1 operation against G16, not each item within the batch.

### G17 — worker_capability_match

**Check:** Execution type matches worker type.

**Logic:**
- Execution came from event → worker must have active `WorkerSubscription` matching the event type
- Execution came from plan → worker must have the required capability in `capability_profile`
- Execution is a sub-agent spawn → worker must have `runtime_type` compatible with the delegated task
- Execution came from browser/RPA workflow → worker must have `runtime_type` in (`browser`, `rpa`, `hybrid`) and matching `WorkerSubscription` or capability profile

**Worker type matrix:**

| Worker type | Has capabilities | Has subscriptions | Accepts from |
|-------------|-----------------|-------------------|-------------|
| Standard | Yes | No | Plan executions only |
| Event-based | No | Yes | Event triggers only |
| Hybrid | Yes | Yes | Both plan and event |
| Browser/RPA | Browser capabilities | Optional | Workflow executions (B0–B7 path) |
| Vision | Vision capabilities | Optional | Vision task executions (V0–V4 path) |

A worker with `worker_class = "execution"` AND active subscriptions → treated as hybrid (both paths accepted).

---

## 4. Batch Processing

### Trigger conditions

S1 (Normalize) checks the payload size after parsing:

```
IF raw_input.items_count > BATCH_THRESHOLD (default 500)
   OR raw_input.payload_size_bytes > BATCH_SIZE_BYTES (default 1MB)
THEN
    Set ExecutionContext.batch_mode = True
    Emit BatchSplit signal with: item_count, threshold, suggested_batch_size
```

**Configuration:** `BATCH_THRESHOLD` and `BATCH_SIZE_BYTES` are tenant-configurable in `tenant_settings`. Defaults prevent surprise batching for normal requests.

### S7 behavior (batch mode)

When `batch_mode = True`, S7 creates `N = CEILING(item_count / BATCH_THRESHOLD)` `ExecutionBatch` rows instead of a single plan. Each batch gets:
- `input_slice`: subset of `raw_input` for this batch
- `batch_number`: 1..N
- `status`: PENDING

S7 creates a single `ExecutionPlan` that wraps all batches: "process N batches, then consolidate."

### S12 behavior (batch execution)

```
FOR each batch in execution_batches (parallelism = BATCH_CONCURRENCY, default 5):
    1. Admission check (G1–G17)
    2. Worker selection
    3. Lease + budget reservation (per batch)
    4. Execute steps
    5. Checkpoint
    6. Verification (S13)
    7. Store batch result
    8. IF batch FAILED → dead-letter queue (independently)
    9. Increment completed_batches counter
```

**Batch timeout:** Each batch has a `batch_timeout_seconds` (tenant-configurable, default 1800 = 30 minutes). If a batch exceeds this, it's marked DEAD_LETTER and the next batch starts. One slow batch does not block the others.

**Budget isolation:** Each batch reserves its own budget independently. A 10-batch job reserves budget for one batch at a time. Total budget = sum of all batch budgets.

### Consolidation (after all batches terminal)

```
IF all batches SUCCESS        → overall result = SUCCESS
IF all batches DEAD_LETTER    → overall result = FAILED
IF mixed (some SUCCESS, some FAILED/DEAD_LETTER)
                               → overall result = PARTIAL
                               → dead-letter batches go to retry queue
```

Consolidation writes a `BatchConsolidation` record to `execution_runs.result`:
```json
{
    "batch_mode": true,
    "total_batches": 10,
    "successful_batches": 8,
    "failed_batches": 1,
    "dead_lettered_batches": 1,
    "consolidated_result": "partial",
    "failed_batch_ids": ["batch-3-uuid"],
    "dead_lettered_batch_ids": ["batch-7-uuid"],
    "retry_recommendation": "retry batches 3 and 7"
}
```

### Checkpoint resume with batches

On restart, the system queries `execution_batches` for the execution:
- `status IN ('SUCCESS', 'FAILED')` → skip (already terminal)
- `status IN ('PENDING', 'RUNNING')` → re-execute (RUNNING batches are treated as failed — the lease expired)
- `status = 'DEAD_LETTER'` → skip unless retry is explicitly requested

This means a 10-batch job that crashes after batch 5 resumes from batch 6. No re-execution of completed work.

---

## 5. Document Change Specification

### 5.1 WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md

**Add §16: Worker Management Settings** (after current §15 Implementation Rules)

Subsections:
- §16.1: WorkerIdentity management columns (additive) — all 8 new columns from §2.1
- §16.2: Admission gates G12–G17 — full gate definitions, bypass rules, logic
- §16.3: WorkerSpawnAudit table schema
- §16.4: operation_quotas table schema
- §16.5: execution_batches table schema
- §16.6: worker_groups tables schema
- §16.7: Three-level timestamp precedence rule
- §16.8: Worker config versioning (F10)
- §16.9: Worker state-change webhooks (F15)
- §16.10: Worker groups (F17)

### 5.2 FINAL_ARCHITECTURE.md

**Five edits:**

1. §33 "Worker Capacity & Scale" — Add paragraph: capacity counting includes sub-agent children and batch slots. `effective_load = current_load + child_count + batch_count`.

2. §34 "Terminology" — Add WorkerGroup definition. Clarify Worker Runtime is deployment-target agnostic (area 8). Add runtime_type taxonomy (area 9) including browser, rpa, vision.

3. §41 "Architecture Extension Points" — Add extension points for: worker management API, batch processing, policy engine, browser/RPA execution path, capability composition.

4. §21 "Memory Architecture" — Add memory classification table (area 7) with 7 classes.

5. §29 "Key Decisions & Rationale" — Add decision records for: progressive autonomy (area 10), heterogeneous workers (area 9), memory-is-not-authorization (area 7), kernel as control envelope not workflow (area 13).

### 5.3 S12_S15_EXECUTION_GATE.md

- **Add C39:** Worker management admission gates G12–G17
- **Add C40:** Batch processing for large payloads
- **Add C41:** Replanning — checkpoint-driven plan replacement
- **Update preflight item 3:** Workers table inventory — include new columns
- **Update preflight item 16:** New table inventory

### 5.4 S12_S15_IMPLEMENTATION_PLAN.md

- **Add M8.5:** Worker management admission gates (G12–G17)
- **Add M9.5:** Batch processing (S1 split, S12 consolidate)
- **Add M12.5:** Sub-agent spawning
- **Add W7:** Operations quota and batch processing workstream

### 5.5 S12_SESSION0_PREFLIGHT_PROMPT.md

- **Add preflight item 16:** Worker management columns and new tables verification

### 5.6 DATA_CONTRACTS.md

- **Add one section:** `BatchSplit` signal contract (S1→S7) and `BatchConsolidation` result (S12→S13)
- **Add one section:** `BrowserExecutionContext` contract (F32)
- **Add one section:** `SkillDefinition` and `SkillStep` contracts (F33)
- **No modifications** to existing contracts, enums, or dataclasses

### 5.7 IDENTITY_AND_TENANCY.md

- **Add one paragraph:** Worker settings JSONB contract shape — documented schema for the `settings` column
- **Add one extension:** CapabilityGrant gets `autonomy_level` field (F20)

### 5.8 PIPELINE_STAGES.md

- **Add one section:** Pipeline path selection based on `runtime_type` (F19, heterogeneous workers)
- **Add one note:** "S0–S11 is the API execution path. Browser/RPA workers use a parallel lightweight path (B0–B7) that bypasses S0–S11. Both paths converge at the execution kernel."
- **No modifications** to existing stage handlers or contracts

---

## 6. Future Evolution Roadmap

### 6.1 Replanning — kernel as control envelope (F31)

**The invariant:** The execution kernel (S0–S15) is a fixed control envelope. The execution plan is a dynamic computation graph. The kernel executes the graph; the graph can be replaced at any checkpoint without changing the kernel.

**How it works:**

```
S12 executes step N
    │
    ▼
Step N returns UNKNOWN (unexpected state)
    │
    ▼
S12 checkpoints current state
    │
    ▼
S12 calls S7 (replan) with updated context
    │
    ▼
New plan fragment produced (steps N+1, N+2, ...)
    │
    ▼
S12 continues from step N+1 of NEW plan
    │
    ▼
Original plan + replan fragments are both in the ledger
```

The replan trigger fires when:
- A step returns UNKNOWN and the probe cycle is inconclusive
- New information arrives that invalidates the current plan (e.g., a webhook event during execution)
- A worker delegates to a sub-agent and the sub-agent's result changes the execution context

**What must be designed before M12:** The checkpoint system must support "resume from arbitrary plan version." Currently, checkpoints resume the same plan. For replanning, the checkpoint must capture: original plan hash, current plan hash, steps completed, steps remaining, and the new plan hash. The kernel doesn't care about plan structure — it just executes steps sequentially.

**Why this matters now:** The AGENTIC and PLAN_EXECUTE strategies are stubbed in M0. When they activate, S12 must handle plans that can be replaced mid-execution. If S12 is built around "execute a fixed plan," replanning is a rewrite. If S12 is built around "execute steps from a graph, graph can be replaced," replanning is a natural extension.

### 6.2 Capability composition / Skills (F33)

**The concept:** Business-level capabilities composed from kernel operations. A `SkillDefinition` is a DAG of `SkillStep` entries, each mapping to a kernel capability. The admin creates skills as data, not code. The planner (S7) reads the composition and produces an ExecutionPlan.

```python
class SkillDefinition:
    skill_id: str                    # UUID
    tenant_id: str
    name: str                        # "qualify_lead"
    description: str                  # Business description
    worker_type: str                  # 'standard', 'browser', 'hybrid', etc.
    composition: list[SkillStep]      # The DAG of kernel operations
    input_schema: dict                # What the skill needs
    output_schema: dict               # What the skill produces
    capabilities_required: list[str]  # Capability grants needed
    estimated_cost: int
    estimated_duration: int
    is_active: bool

class SkillStep:
    step_id: str
    capability_id: str                # Maps to a kernel operation
    input_mapping: dict               # Maps skill input → capability input
    output_mapping: dict              # Maps capability output → skill context
    depends_on: list[str]             # step_ids this step depends on
    condition: str | None             # "if previous score > 0.7"
```

**Why this matters:** A tenant admin can create "lead qualification" as a skill without touching code. They compose existing capabilities (search_contact → retrieve_company → analyze_lead → score_lead → update_CRM → schedule_followup) into a new business capability. Other workers use this skill. Skills can be shared via the marketplace. The kernel doesn't change — it just executes a longer plan.

**Where it lands:** `skill_definitions` and `skill_steps` tables at M0. S7 planner handles skill compositions at M7. Skill marketplace at M21.

### 6.3 Memory classification (area 7)

Seven memory classes stored with a `memory_classification` column:

| Class | What | Storage | Example |
|-------|------|---------|---------|
| Episodic | What happened? | L0 (transient) → L1 (checkpoint) | "On Sep 28, created contact John Doe" |
| Semantic | What does the worker know? | L3 (long-term, vector) | "John Doe is a VP of Sales at Acme Corp" |
| Procedural | How should it perform something? | L2 (session) → L3 | "When qualifying leads, always check company size first" |
| Organizational | What does the company permit? | L3 (tenant-wide) | "This tenant allows CRM writes but not deletions" |
| Execution | What happened during this execution? | L1 (working, checkpointed) | "Step 3 returned 247 contacts, took 12s" |
| Relationship | What is known about this customer/entity? | L3 (per-entity) | "John prefers email contact, responds in mornings" |
| Policy | What is allowed? | L3 (tenant-wide, read-only) | "Finance transfers require two-person approval" |

**Critical invariant:** Memory is never consulted for authorization decisions. The authorization chain (tenant → workspace → user role → capability grants → safety gate) never reads memory. Memory informs the LLM's behavior; the policy engine decides what's allowed.

### 6.4 Environment independence (area 8)

Worker Runtime is deployment-target agnostic. The `runtime_image` field on `WorkerVersion` holds a deployment descriptor:
- Docker: `"ghcr.io/tenant/worker:v1.2.3"`
- Lambda: `"arn:aws:lambda:us-east-1:123456:function:worker-name"`
- Edge: `"https://worker.tenant.edge.workers.dev"`
- On-prem: `"/opt/workers/worker-binary"`
- Kubernetes: `"deployment/worker-name/namespace/tenant"`

The Runtime Contract (§38) is the abstraction layer. The kernel never inspects `runtime_image` — consumed only by the deployment subsystem.

### 6.5 Heterogeneous workers (area 9)

`runtime_type` column determines pipeline path. The kernel asks one question: **"Can this worker execute this contract?"** — answered by capability matching. `runtime_type` determines how, not whether.

| runtime_type | Pipeline path | Adapter |
|-------------|--------------|---------|
| `llm` | S0–S15 (full) | LLM adapters (Claude, GPT, Gemini) |
| `rules` | S0→S1→S3→S5→S12 (skip S2, S4, S6) | RulesEngine adapter |
| `vision` | S0→S1→S2(vision)→S5→S12 | Vision adapter |
| `browser` | B0–B7 (parallel path) | BrowserAdapter |
| `rpa` | B0–B7 (parallel path) | BrowserAdapter (RPA composition) |
| `data` | S0→S1→S3→S5→S12 (skip S2, S4, S6) | DataEngine adapter |
| `rag` | S0→S1→S2→S5→S12 with retrieval | RAG adapter |
| `code` | S0→S1→S2→S5→S12 with sandbox | CodeExecution adapter |
| `human` | S0→S1→S8→HITL (skip S2–S7, S12) | HumanTask adapter |

### 6.6 Progressive autonomy (area 10)

`autonomy_level` per CapabilityGrant — capability-specific, not global:

| Autonomy level | Meaning | S8 behavior |
|---------------|---------|------------|
| `observed` | Worker executes, human reviews after | Execute → S13 verify → notify human |
| `assisted` | Worker proposes, human confirms before side effect | S8 → CLARIFY → human confirms → S12 execute |
| `limited` | Worker executes low-risk operations autonomously | Execute for READ and IDEMPOTENT_WRITE; CLARIFY for DELETE/IRREVERSIBLE |
| `expanded` | Worker executes most operations autonomously | Execute for all except IRREVERSIBLE; CLARIFY for IRREVERSIBLE |
| `high_trust` | Full autonomy for this capability | Execute without CLARIFY |

Progression is admin-managed, not automatic. Success tracking feeds the admin's decision, but the admin decides. The architecture tracks `successful_executions` and `failed_executions` per worker per capability — the admin sees the data and promotes/demotes autonomy levels.

### 6.7 Policy-as-a-runtime (area 11)

Eight-layer policy evaluation chain. Each layer can only restrict, never expand the layer above:

```
Tenant Policy (existing)
  └── Industry Policy (new: healthcare, finance, SaaS defaults)
       └── Regulatory Policy (new: GDPR, HIPAA, SOC2)
            └── Company Policy (new: org-specific rules)
                 └── Workspace Policy (existing)
                      └── Worker Policy (new: worker-specific overrides)
                           └── Capability Policy (existing, extended)
                                └── Data Policy (new: PII, financial, health data rules)
                                     └── Risk Policy (existing)
```

`PolicyEngine` as dedicated runtime component called at S8. Context dimensions: time, location, data classification, compliance frameworks.

**Critical invariant:** LLM proposes, policy engine evaluates, kernel enforces. Never: LLM decides authorization.

### 6.8 Event evolution

Event Gateway extensions (all outside S0–S15):
- Event ordering: `sequence_number` in `event_log`, Event Gateway sorts by sequence
- Causality tracking: `causation_id` in `EventEnvelope` (points to triggering event)
- Replay: `event_replay` table records replay sessions; Event Gateway replays from `event_log`
- Event versioning: `event_schema_version` in `EventEnvelope`; Gateway normalizes to latest
- Event correlation: `EventCorrelator` class — multiple events trigger one execution
- Dead-lettering for events: `event_dead_letters` table

### 6.9 Multi-agent delegation

Execution tree visibility via `parent_execution_id`. Supervisor → child worker pattern enabled by sub-agent spawning + execution tree + browser/RPA path. Delegation safety: children inherit parent's scoped capabilities, never expand them. PrincipalChain preserves full delegation chain.

---

## 7. Seven-Layer Architecture Invariant

### The model

```
┌───────────────────────────────────────────────────────────────┐
│ 7. Worker Marketplace / Business Outcomes                    │
│   Worker listing, templates, plans, skill marketplace         │
├───────────────────────────────────────────────────────────────┤
│ 6. Multi-Agent / A2A Coordination                            │
│   Sub-agent spawning, delegation safety, execution tree       │
├───────────────��───────────────────────────────────────────────┤
│ 5. Skills / Capability Composition                           │
│   SkillDefinition, SkillStep, composition engine              │
├───────────────────────────────────────────────────────────────┤
│ 4. Model / Runtime / Worker Routing                          │
│   Worker selection, runtime_type routing, model resolution    │
├───────────────────────────────────────────────────────────────┤
│ 3. Provider / Protocol / Event Ecosystem                      │
│   API adapters, BrowserAdapter, Event Gateway, subscriptions  │
├───────────────────────────────────────────────────────────────┤
│ 2. Durable Execution + Evidence                               │
│   Checkpoint, lease, fence, ledger, batch, replan             │
├───────────────────────────────────────────────────────────────┤
│ 1. Safety / Identity / Authorization Kernel                   │
│   S0–S8, RBAC, capability grants, safety gate, policy engine │
└───────────────────────────────────────────────────────────────┘
```

### Layer contracts

| Layer | Provides to above | Requires from below | Stability |
|-------|-------------------|--------------------|-----------|
| 1. Safety/Identity | Authorization decisions, capability grants, user identity | Identity data, policy data | **FROZEN** — no changes after S11 cert |
| 2. Durable Execution | Execution slots, leases, evidence, checkpoint/resume | Authorization from L1, frozen manifest | **STABLE** — only additive (batch, replan) |
| 3. Provider/Event | Capability execution, event ingestion | Execution steps from L2 | Stable — new providers are additive |
| 4. Worker Routing | Worker assignment, model selection, runtime routing | Capabilities from L3, worker state from L1 | Evolving — worker management adds gates |
| 5. Skills | Composed capabilities, skill marketplace | Kernel capabilities from L3/L4 | Evolving — composition is additive |
| 6. Multi-Agent | Sub-agent spawning, delegation, execution tree | Worker lifecycle from L1, execution from L2 | Evolving — spawning is additive |
| 7. Marketplace | Worker listing, plans, templates, entitlements | All layers below | Evolving — marketplace is additive |

### Key rules

1. **Layers 1–2 must become extremely stable.** S0–S11 certifies layer 1. S12–S15 implements layer 2. After certification, only additive changes.
2. **No layer may bypass the layer below it.** Layer 5 cannot execute a capability without going through L4→L3→L2. Layer 6 cannot spawn a worker without going through L1 authorization.
3. **Each layer can only restrict, never expand, the layer above it.** A tenant policy restricts what the workspace can do. A worker policy restricts what the capability allows.
4. **The kernel (L1–L2) never knows about marketplace mechanics (L7).** The marketplace is a management layer on top. The kernel executes — it doesn't sell.

---

## 8. Browser/RPA Execution Path

### Overview

Browser and RPA workers use a parallel execution path (B0–B7) that bypasses S0–S11 entirely. This path shares the worker lifecycle, admission gates (G1–G17), lease/fencing, budget tracking, ledger, and checkpoint — everything from the execution kernel. It has its own entry point, its own adapter, and its own verification.

**Why a separate path:** S0–S11 exists because API calls are dangerous (mutations, costs, irreversibility). Browser/RPA workers have a recorded workflow definition instead of free-text intent. They don't need intent analysis, capability discovery, risk assessment from capability metadata, binding resolution, or confirmation flows. The workflow IS the plan.

### B0–B7 execution flow

```
B0 — Load workflow definition
    │   Input: workflow_id (references skill_definitions where worker_type = 'browser' or 'rpa')
    │   Output: BrowserExecutionContext (simplified — no intent, no plan)
    ▼
B1 — Admission (same G1–G17 gates)
    │   Same logic as S12 admission
    │   G17 additionally checks: worker runtime_type in ('browser', 'rpa', 'hybrid')
    ▼
B2 — Worker selection (same as S12)
    │   Same scheduler, same WorkerSelectionScore
    │   Filters workers by runtime_type = 'browser' or 'rpa'
    ▼
B3 — Lease acquisition (same as S12)
    │   Same execution_leases table
    ▼
B4 — Execute workflow steps
    │   For each step in the workflow definition:
    │     browser_open(url)           → Playwright/Apify/BrowserUse
    │     browser_click(selector)     → Playwright
    │     browser_type(selector, text) → Playwright
    │     browser_wait(selector)      → Playwright
    │     browser_extract(selector)   → Playwright/Apify
    │     browser_screenshot()        → Playwright
    │     browser_filter(field, val)  → Playwright
    │     browser_export(format)      → Playwright
    ▼
B5 — Verification
    │   Screenshot comparison (before vs after)
    │   DOM inspection (element exists, text matches)
    │   Data extraction validation (schema check)
    │   File existence check (for exports)
    ▼
B6 — Consolidation
    │   Same consolidation rules as S12
    ▼
B7 — Response
    │   Collected data → stored → returned
```

### BrowserExecutionContext

A separate frozen dataclass — does NOT touch `ExecutionContext` (the S0 one). Zero impact on S0–S11.

```python
@dataclass(frozen=True)
class BrowserExecutionContext:
    trace_id: str                    # Same UUID pattern
    request_id: str                  # Same UUID pattern
    tenant_id: str                   # Same
    user_id: str                     # Same
    worker_id: str                   # Same
    workspace_id: str                # Same
    
    # Browser-specific
    workflow_id: str                 # References skill_definitions
    workflow_version: str            # For reproducibility
    session_data: dict               # Data collected during execution
    screenshots: list[str]           # Screenshot references (S3 paths)
    
    # Shared
    auth_passed: bool = False        # Simplified check (G3 + G4 only)
    dry_run: bool = False            # Same as API path
```

### BrowserAdapter — facade with pluggable providers

```python
class BrowserAdapter(BaseAdapter):
    """Facade over multiple browser automation providers.
    
    The kernel never knows which provider is active.
    Provider selection is per-tenant, per-capability, configurable.
    """
    
    def __init__(self, config: BrowserAdapterConfig):
        self.providers = {
            "playwright": PlaywrightProvider(config.playwright),
            "apify": ApifyProvider(config.apify),
            "browseruse": BrowserUseProvider(config.browseruse),
        }
        self.default_provider = config.default_provider  # usually "playwright"
    
    async def call(self, capability_id: str, params: dict,
                   context: BrowserExecutionContext) -> KernelResult:
        provider = self._select_provider(capability_id, params)
        return await provider.execute(capability_id, params, context)
    
    def _select_provider(self, capability_id: str, params: dict) -> BrowserProvider:
        """Route to the right provider based on capability and params."""
        if capability_id == "browser_crawl" and params.get("max_pages", 0) > 50:
            return self.providers["apify"]
        if capability_id in ("browser_navigate_ai", "browser_extract_ai"):
            return self.providers["browseruse"]
        return self.providers[self.default_provider]
```

### Browser capability registry entries

Additive entries in existing `kernel_definitions.yaml`:

```yaml
browser_open:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.1
  mutation_type: READ
  estimated_duration_seconds: 10

browser_click:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.3
  mutation_type: IDEMPOTENT_WRITE
  estimated_duration_seconds: 5

browser_type:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.3
  mutation_type: IDEMPOTENT_WRITE
  estimated_duration_seconds: 5

browser_extract:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.1
  mutation_type: READ
  estimated_duration_seconds: 15

browser_screenshot:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.0
  mutation_type: READ
  estimated_duration_seconds: 3

browser_wait:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.0
  mutation_type: READ
  estimated_duration_seconds: 5

browser_filter:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.1
  mutation_type: READ
  estimated_duration_seconds: 10

browser_export:
  provider: browser
  adapter: BrowserAdapter
  risk_floor: 0.2
  mutation_type: IDEMPOTENT_WRITE
  estimated_duration_seconds: 15
```

### Browser verification (S13 integration)

```python
class BrowserVerifier:
    """Plugs into existing S13 verification flow."""
    
    async def verify_screenshot(self, expected: str, actual_path: str) -> bool:
        """Pixel-level or AI-level comparison."""
    
    async def verify_dom_state(self, expected: dict, dom_snapshot: dict) -> bool:
        """Check DOM matches expected state."""
    
    async def verify_extracted_data(self, expected_schema: dict, extracted: dict) -> bool:
        """Validate extracted data against expected schema."""
```

### What browser/RPA shares vs. what's separate

| Component | Shared with API path | Separate for browser |
|-----------|---------------------|---------------------|
| Worker identity | Yes | — |
| Admission gates G1–G17 | Yes | — |
| Lease/fencing | Yes | — |
| Budget tracking | Yes | — |
| Ledger | Yes | — |
| Checkpoint | Yes | — |
| Worker groups, config, webhooks | Yes | — |
| Worker spawning | Yes | — |
| Entry point | No | B0 (workflow loader) |
| Intent analysis | No | None — workflow IS the intent |
| Capability discovery | No | None — capabilities are predefined in workflow |
| Risk assessment | No | Simplified — fixed risk profiles per browser action |
| Binding resolution | No | None — one adapter, no provider selection |
| Authorization | Simplified | G3+G4+G12–G17 only, no capability-specific auth |
| Planning | No | None — plan is the recorded workflow |
| Confirmation | Optional | Configurable per workflow |
| Execution | No | B4 — BrowserAdapter |
| Verification | Different method | B5 — screenshots, DOM, data validation |
| Response | No | B7 — collected data |

### Build vs. integrate for browser infrastructure

| Component | Approach | Rationale |
|-----------|----------|-----------|
| Browser automation engine | **Buy** — Playwright (self-hosted, free) | Handles all browser quirks, actively maintained |
| Browser session management | **Build** | Pool browsers, concurrency per tenant, cookie/auth state, cleanup |
| Browser orchestration | **Build** | Maps to existing WorkerPool and scheduler |
| High-scale scraping | **Integrate** — Apify | 1,000+ concurrent scrapes; self-hosted hits resource walls |
| AI-driven browsing | **Integrate** — BrowserUse | Vision-driven navigation for ambiguous UIs |
| Screenshot storage | **Build** (on existing infra) | Part of execution evidence record |
| Proxy management | **Build** | Tenant-specific proxies, geo-routing, IP rotation |
| Anti-bot handling | **Integrate** | CAPTCHA solving, fingerprint randomization — arms race |

---

## Appendix A: Timestamp Precedence Rules

### Pause precedence (G12)

```
effective_paused_until = GREATEST(
    COALESCE(tenant.settings.paused_until, '1970-01-01'),
    COALESCE(workspace.settings.paused_until, '1970-01-01'),
    COALESCE(group.paused_until, '1970-01-01'),
    COALESCE(worker.paused_until, '1970-01-01')
)

IF effective_paused_until > NOW()
    → REJECT with worker_paused
```

`'1970-01-01'` is the sentinel for "not paused." Any real timestamp will be after it.

### Activation precedence (G13)

```
effective_activation_at = GREATEST(
    COALESCE(tenant.settings.scheduled_activation_at, '1970-01-01'),
    COALESCE(workspace.settings.scheduled_activation_at, '1970-01-01'),
    COALESCE(worker.scheduled_activation_at, '1970-01-01')
)

IF effective_activation_at > NOW()
    → REJECT with worker_not_yet_active
```

### Operations quota precedence (G16)

```
effective_limit = MIN(
    COALESCE(tenant_quota.limit_value, infinity),
    COALESCE(workspace_quota.limit_value, infinity),
    COALESCE(worker_quota.limit_value, infinity)
)

IF effective_limit IS infinity
    → PASS (no quota configured)
ELSE IF used_count >= effective_limit
    → REJECT or QUEUE based on is_hard
```

---

## Appendix B: Settings JSONB Schema Contract

The `workers.settings` JSONB column uses this documented schema. Frontend and admission controller both reference this contract. Fields are additive — new keys can be added without migrations.

```json
{
    "skills_prompt": "string — the worker's business skills and instructions prompt",
    "rules": ["string — structured business rules, e.g., never create contact without phone"],
    "restricted_capabilities": ["string — capability IDs this worker cannot execute, regardless of grants"],
    "llm_model": "string — preferred model ID, must be in tenant's allowed_models",
    "execution_policy": {
        "timeout_seconds": "integer — per-step timeout override",
        "max_retries": "integer — retry ceiling for this worker",
        "retry_backoff": "string — 'exponential' | 'linear' | 'fixed'",
        "circuit_breaker_threshold": "integer — failures before circuit opens"
    },
    "memory_policy": {
        "session_ttl_hours": "integer — L2 session lifetime",
        "compaction_strategy": "string — 'summarize' | 'truncate' | 'none'",
        "max_session_memories": "integer — cap on L2 entries per session"
    },
    "browser_policy": {
        "headless": "boolean — run browser headless or headed",
        "viewport_width": "integer",
        "viewport_height": "integer",
        "default_timeout_ms": "integer — default timeout for browser actions",
        "screenshot_on_error": "boolean — capture screenshot on step failure",
        "proxy_url": "string — tenant-specific proxy for this worker"
    },
    "is_listed": "boolean — visible in marketplace",
    "listing_config": {
        "category": "string — marketplace category",
        "tags": ["string — searchable tags"],
        "preview_enabled": "boolean — allow test executions before purchase"
    },
    "custom_fields": {}
}
```

All keys are optional. Missing keys fall back to tenant defaults or global defaults.

---

## Appendix C: Admission Gate Decision Matrix

| Gate | When checked | Stateless? | Reserves resource? | Bypass for admins | Failure action |
|------|-------------|-----------|-------------------|-------------------|----------------|
| G1 | Every execution | Yes | No | No | REJECT → run CANCELLED |
| G2 | Every execution | Yes | No | No | REJECT |
| G3 | Every execution | Yes | No | No | REJECT |
| G4 | Every execution | Yes | No | No | REJECT |
| G5 | Every execution | Yes | No | No | REJECT |
| G6 | Every execution | Yes | No | No | REJECT |
| G7 | Every execution | Yes | No | No | QUEUE |
| G12 | Every execution | Yes | No | Yes | REJECT |
| G13 | Every execution | Yes | No | Yes | REJECT |
| G14 | Every execution | Yes | No | Yes | REJECT |
| G15 | Sub-agent spawn only | Yes | No | No | REJECT |
| G16 | Every execution | Yes | No | No | REJECT or QUEUE |
| G17 | Every execution | Yes | No | No | REJECT |
| G8 | Every execution | Yes | No | No | REJECT |
| G9 | Every execution | Yes | No | No | REJECT |
| G10 | Every execution | Yes | No | No | REJECT |
| G11 | Every execution | Yes | No | No | REJECT |

G7 is the only gate that QUEUEs instead of REJECTing (capacity). G16 can REJECT or QUEUE based on `is_hard`. All other gates REJECT on failure. First gate that fails stops evaluation — no further gates are checked.

---

## Appendix D: What This Document Does NOT Cover

These are explicitly out of scope for the S12 install and are left for post-S15 phases:

- AIOS-style provider failover implementation (pattern adopted, implementation deferred)
- Debug replay (SystemOneHarness pattern, deferred)
- Escalation chains beyond HITL (deferred)
- Agentic loop strategies (AGENTIC, BATCH, PLAN_EXECUTE — stubbed in M0)
- Memory write barrier implementation (L0–L3 storage, deferred)
- Multi-region deployment
- Fleet-level worker management (horizontal scaling, node assignment)
- Billing integration (operation_quotas tracks counts; billing conversion to money is separate)
- Marketplace payment processing
- Third-party worker publishing (workers listed by other tenants)
- Advanced A2A protocols beyond TaskHandoff
- Browser-specific anti-bot evasion (delegated to third-party providers)
- Computer vision model selection and optimization (deferred to V0–V4 implementation)
- RPA workflow recording (UI-based workflow creation tool — deferred)

These are documented as extension points in `FINAL_ARCHITECTURE.md` §41. None require kernel changes.
