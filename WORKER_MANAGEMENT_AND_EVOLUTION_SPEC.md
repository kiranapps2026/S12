# Worker Management & Evolution Specification

**Version**: 1.2.1 (audit round 2, 2026-09-29: pause at S0.1 via S0–S11 ruling R-P; no per-step pause or quota check; tenant/workspace-level quotas only; eligibility filters 4b and 17a–d; see `WORKER_MGMT_SPEC_REVIEW.md` Part G)
**Status**: REFERENCE — propagated. The binding text is `S12_S15_EXECUTION_GATE.md` v10 (C39–C41) and the master documents listed in §5. Where this document and a master document differ, the master document wins.
**Date**: 2026-09-29
**Purpose**: Consolidated reference for worker-level features, their phase, and their evolution path.
**Rule**: Nothing in this document modifies S0–S11 certified artifacts. Features that would need an S0–S11 change are marked **S0–S11 change control** and wait for gate §19.3.

### Changes from v1.1.0

v1.1.0 was reviewed in `WORKER_MGMT_SPEC_REVIEW.md` (Parts A–F). Rulings RD-1…RD-18 were confirmed by the owner on 2026-09-29. The main corrections:

| Area | v1.1.0 | v1.2.0 | Ruling |
|---|---|---|---|
| Key types | `UUID` FKs to `TEXT` keys | `TEXT` keys everywhere, incl. `workers.worker_id` | RD-1 |
| Timestamps | — | `TIMESTAMPTZ`, compared with database `NOW()` | RD-2 |
| Tenant column | Missing on 5 tables | `tenant_id TEXT NOT NULL` + RLS on every table | RD-3 |
| Worker gates | G12–G17 in admission, before a worker exists | Two phases: admission (tenant/workspace) + eligibility filters (worker) | RD-4 |
| Pause | Undefined for running work | New work only; kill switch is the hard stop | RD-5 |
| Quota | Counted at completion (overshoot) | Consumed once per run at durable admission | RD-6 |
| Admin roles | `TENANT_ADMIN` / `TENANT_OWNER` | Membership `owner` / `admin` in the run's workspace | RD-7 |
| Browser/RPA | B0–B7 path bypassing S0–S11 | Adapters under S0→S15; I-029 | RD-8, RD-9 |
| Worker type | `worker_type` + `runtime_type` + `worker_class` | `runtime_type` only; plan/event/hybrid derived | RD-10 |
| Replanning | S12 calls "S7" mid-run | Child execution; out of S12–S15 | RD-11 |
| Batch | Batch table with its own states | BATCH-strategy PlanSteps; out of S12–S15 | RD-12 |
| Spawning | Admission gate G15 | Check inside `spawn_child_worker()`; deferred | RD-13 |
| Autonomy | Second enum on `CapabilityGrant` | `AutonomyLevel` only; restrict-only refinement | RD-14 |
| "Seven-Layer Architecture" | Collided with FINAL_ARCHITECTURE §6 | Stability Tiers T1–T7 | RD-15 |
| Stage names | Planning at "S7" | Planning at **S9** (S7 is Path Routing) | review #13 |
| Browser mutation classes | `READ`, `IDEMPOTENT_WRITE` | `R` / `IRREVERSIBLE` (or `W`/`D` with an inverse) | review #15, round 3 |
| Milestones | M7, M21, M8.5, M9.5, M12.5, W7 | Plan v3 IDs (M1, M8a) or "post-S15" | RD-17 |
| Missing §9, §10 | Listed in TOC only | Written | review A-1 |

---

## Table of Contents

1. [Feature Inventory and Phase](#1-feature-inventory-and-phase)
2. [Database Schema](#2-database-schema)
3. [Admission and Worker Eligibility](#3-admission-and-worker-eligibility)
4. [Batch Processing (deferred)](#4-batch-processing-deferred)
5. [Propagation Record](#5-propagation-record)
6. [Future Evolution Roadmap](#6-future-evolution-roadmap)
7. [Stability Tiers T1–T7](#7-stability-tiers-t1t7)
8. [Browser and RPA Execution](#8-browser-and-rpa-execution)
9. [S0–S11 Protection List](#9-s0s11-protection-list)
10. [Implementation Sequence](#10-implementation-sequence)
- [Appendix A: Timestamp and Quota Precedence](#appendix-a-timestamp-and-quota-precedence)
- [Appendix B: Settings JSONB Contract](#appendix-b-settings-jsonb-contract)
- [Appendix C: Admission and Eligibility Decision Matrix](#appendix-c-admission-and-eligibility-decision-matrix)
- [Appendix D: Out of Scope](#appendix-d-out-of-scope)

---

## 1. Feature Inventory and Phase

"S12–S15" = implemented in the S12–S15 phase under gate v10 C39 (plan v3 milestones M1, M8a). "Post-S15" = designed here, recorded in gate §14 and blocker register §19.3, not implemented now.

### P0 — In the S12–S15 phase

| ID | Feature | Where it lives | Phase |
|----|---------|----------------|-------|
| F1 | Worker config store `workers.settings` JSONB | DATABASE workers; IDENTITY §5 contract | S12–S15 (read by S12 only; restrict-only) |
| F2 | Worker pause `workers.paused_until` | Eligibility filter 12b | S12–S15 |
| F3 | Scheduled activation `workers.scheduled_activation_at` | Eligibility filter 13b | S12–S15 |
| F4 | Tenant/workspace pause and activation (typed columns) | S0.1 check (S0–S11 ruling R-P) + S12-entry safety net | S12–S15 (R-P lands in S0–S11) |
| F5 | Employee assignment `workers.assigned_user_id` | Eligibility filter 14 | S12–S15 |
| F6 | Operation quota `operation_quotas` | Consumed once per run at durable admission; no per-step check | S12–S15 (tenant/workspace levels; hard + soft) |
| F8 | Runtime/capability match | Eligibility filter 17 on `runtime_type` and `capability_profile` | S12–S15 |

### Moved out of P0

| ID | Feature | New tier | Why |
|----|---------|----------|-----|
| F0 | `execution_runs.parent_execution_id` | Post-S15 | No consumer in S12–S15; lands with replanning or delegation (RD-11) |
| F7 | Sub-agent spawning | Post-S15 | Not needed by the S12 install; worker registration is out of phase (RD-13) |
| F9 | Batch processing | Post-S15 | Depends on idempotency, loop, consolidation and recovery (M11, M12, M16, M19); parallel steps deferred (RD-12) |
| F31 | Replanning | P2 | Needs S12 first; model is a child execution (RD-11) |

### P1 — Before marketplace launch (post-S15)

| ID | Feature | Design |
|----|---------|--------|
| F10 | Worker config versioning | Reuse `ConfigurationVersion` (DATA_CONTRACTS §48); record the version on each leased step; changes affect new leases only (I-017) |
| F11 | Worker execution analytics | Read-side aggregation of the ledger |
| F12 | Capability deny-list `settings.restricted_capabilities` | Capability IDs; restrict-only; S12 eligibility filter 17b now (in phase), S8 enforcement needs S0–S11 change control |
| F13 | Dry-run | A sandbox connection/binding resolved at S5 (mock adapter); no `ExecutionContext` flag (I-009) |
| F14 | Model selection | `RuntimeRoutingDecision` (DATA_CONTRACTS §42) at S7, frozen per execution; needs a tenant model allow-list in `TenantPolicy` |
| F15 | Worker state-change webhooks | Secret reference via `CredentialProvider`; outbox dispatch (I-020); SSRF validation |
| F16 | Per-worker `execution_policy` | `max_mutation` live now (filter 17d); `max_retries`, `timeout_seconds`, `retry_backoff` reserved (may only lower limits when they land); no per-worker breaker threshold |
| F17 | Worker groups | `worker_groups` + members; group pause in filter 12b |
| F18 | L2 session memory | Needs `MemoryWriteBarrier` (I-014) first |
| F19 | Heterogeneous workers | `runtime_type` selects routing, binding family and eligibility; never skips a stage (§6.5) |
| F20 | Progressive autonomy | Restrict-only refinement of `AutonomyLevel`; S0–S11 change control |
| F32 | Browser/RPA execution | Adapters under S0→S15 (§8) |
| F33 | Capability composition (skills) | `SkillDefinition` planned at S9 (§6.2) |
| F34 | Browser providers | One adapter per provider; provider choice = binding (§8) |
| F35 | Browser session pool | Per tenant; credentials via `CredentialProvider` |
| F36 | Browser verification | `observe()` on the adapter + S13 verification layers |

### P2 — Enterprise (post-S15)

| ID | Feature | Design |
|----|---------|--------|
| F21 | Memory classification | Orthogonal to layers L0–L3 (FINAL_ARCHITECTURE §21) |
| F22 | PolicyEngine | Guardrail level 6 (extension point #8); S8 change control |
| F23 | Environment independence | Runtime Contract (FINAL_ARCHITECTURE §38) |
| F24 | Event evolution | Extends existing ordering/causality/correlation (§6.8) |
| F25 | Worker templates | `worker_templates` with `runtime_type` |
| F26 | Plan-based entitlements | `plans` + `tenant_plans`; entitlement check per extension point #15 |
| F27 | Marketplace listing | `settings.is_listed`, `listing_config` |
| F31 | Replanning | Child execution (§6.1) |

### P3 — Roadmap, no commitment

| ID | Feature | Design |
|----|---------|--------|
| F28 | Supervisor pattern | Child executions + delegation (§6.9) |
| F29 | Advanced A2A protocols | Extension of existing A2A |
| F30 | Agentic strategies | AGENTIC, BATCH, PLAN_EXECUTE, HUMAN_ASSISTED (stubbed; route to CLARIFY) |

---

## 2. Database Schema

Authoritative DDL: DATABASE.md. Keys are `TEXT` (RD-1). New time columns are `TIMESTAMPTZ` compared with database `NOW()` (RD-2). Every table carries `tenant_id TEXT NOT NULL` with the standard RLS policy (RD-3, gate C34).

### 2.1 In the S12–S15 phase (gate v10 C39, migration 018)

```sql
-- workers (management columns; worker_id and tenant_id are TEXT)
ALTER TABLE workers ADD COLUMN settings JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE workers ADD COLUMN assigned_user_id TEXT REFERENCES users(user_id);
ALTER TABLE workers ADD COLUMN paused_until TIMESTAMPTZ;
ALTER TABLE workers ADD COLUMN scheduled_activation_at TIMESTAMPTZ;
ALTER TABLE workers ADD COLUMN runtime_type TEXT NOT NULL DEFAULT 'llm'
    CHECK (runtime_type IN ('llm','rules','vision','browser','rpa','data','rag','code','human'));

-- tenants and workspaces (typed columns, not keys inside their TEXT settings JSON)
ALTER TABLE tenants    ADD COLUMN paused_until TIMESTAMPTZ;
ALTER TABLE tenants    ADD COLUMN scheduled_activation_at TIMESTAMPTZ;
ALTER TABLE workspaces ADD COLUMN paused_until TIMESTAMPTZ;
ALTER TABLE workspaces ADD COLUMN scheduled_activation_at TIMESTAMPTZ;

CREATE TABLE operation_quotas (
    quota_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id TEXT REFERENCES workspaces(workspace_id),
    worker_id TEXT REFERENCES workers(worker_id),
    resource_type TEXT NOT NULL DEFAULT 'executions' CHECK (resource_type IN ('executions')),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    limit_value INTEGER NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    is_hard BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (used_count >= 0 AND limit_value >= 0),
    CHECK (period_end > period_start),
    CHECK (worker_id IS NULL OR workspace_id IS NOT NULL),
    UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)
);
```

Also in migration 018 (RD-1): `workers.worker_id`, `workers.tenant_id`, `worker_leases.lease_id`, `worker_leases.worker_id` and `worker_assignments.*_id` change from `UUID` to `TEXT`.

### 2.2 Deferred designs (post-S15; not created now)

Each lands with `tenant_id TEXT NOT NULL` + RLS and `TEXT` keys.

| Table / column | Design notes |
|---|---|
| `workers.max_sub_agents`, `parent_worker_id TEXT`, `depth_level` | Spawning (§3.4) |
| `worker_spawn_audit` | `tenant_id`; `budget_allocated` as INTEGER minor units, drawn from the tenant pool by a design still to be made |
| `worker_groups`, `worker_group_members` | Members table carries `tenant_id`; a worker may be in several groups |
| `worker_config_versions` | Or reuse `ConfigurationVersion`; `changed_by TEXT` |
| `worker_webhooks` | `secret_ref` (not `secret`), resolved via `CredentialProvider` |
| `worker_sessions`, `session_memory` | `tenant_id` on both; default class is **not** "episodic" (§6.3) |
| `worker_templates`, `skill_definitions` | `runtime_type` instead of `worker_type`; `created_by TEXT` |
| `plans`, `tenant_plans` | `allowed_runtime_types` instead of `allowed_worker_types` |
| `execution_runs.parent_execution_id TEXT` | With its first consumer (RD-11) |
| `execution_runs.dry_run` | Derived from a sandbox binding (F13) |
| `execution_batches`, `batch_mode`, `total_batches`, `completed_batches` | **Not planned**: batches are PlanSteps (§4) |

---

## 3. Admission and Worker Eligibility

Binding text: gate v10 C39; WORKER_LIFECYCLE §10, §13, §16.

### 3.1 Where each check runs

Admission runs before a worker is selected (gate §8 steps 1 → 2), and the run row is created only at S12 entry (§7.2). So: checks about the tenant or workspace run as **entry checks**; checks about a particular worker **filter the candidates** during selection; quota is **charged once** when the run row is created. Per-step admission (gates 1–11) is unchanged.

### 3.2 Entry checks

| Check | Where | Outcome |
|------|-------|---------|
| Tenant/workspace `paused_until > NOW()` | **S0.1** (S0–S11 ruling R-P), primary; S12 entry (§7.1 item 7), safety net | DENY `tenant_paused` / `workspace_paused`; nothing written; no S1–S11 work when caught at S0.1 |
| Tenant/workspace `scheduled_activation_at > NOW()` | S0.1; S12 entry | DENY `not_yet_active` |
| Operation quota | S12 entry, inside the §7.2 transaction | Charged once per run (§3.5); hard → DENY; soft → bounded retry, then DENY with `retry_after_ms` |

No pause, activation or quota check runs per step (audit A1, A2): a per-step pause check would cancel running work, and a per-step quota check would count the run's own consumption and cancel admitted runs. Entry denials are logged, not ledger events.

### 3.3 Worker-eligibility filters (pure; gate §8 step 2, before locality scoring)

| Filter | Removes a candidate when | Filter reason | Admin bypass |
|--------|--------------------------|---------------|---|
| 4b | `workers.workspace_id` ≠ the run's workspace, or NULL (legacy row) | `workspace_mismatch` | No |
| 12b | `workers.paused_until > NOW()` (worker groups: post-S15, not evaluated) | `worker_paused` | Yes |
| 13b | `workers.scheduled_activation_at > NOW()` | `worker_not_yet_active` | Yes |
| 14 | Only for runs whose original principal is a human user and that are not EVENT_DRIVEN: `assigned_user_id` set and ≠ `PrincipalChain.original_principal_id` | `not_assigned` | Yes |
| 17a–c | Step capability not in `capability_profile`; or in `settings.restricted_capabilities`; or the binding's `required_runtime_types` is non-empty and lacks `runtime_type` | `capability_mismatch` | No |
| 17d | `settings.execution_policy.max_mutation` set and below the step's frozen `effective_mutation` | `mutation_ceiling` | No |

Admin bypass: the run's original principal holds membership role `owner` or `admin` in the run's workspace, read live at selection, audited. No candidate left → the step ends `no_worker`, with every filter reason in the ledger event.

### 3.4 Pause semantics

Pause and activation block **new** runs (S0.1, S12 entry) and **new** leases (12b, 13b). A pause never cancels a running step or a held lease. The kill switch (C23) is the hard stop. Unpausing takes effect for the next submission.

### 3.5 Quota consumption

Tenant- and workspace-level quotas only in this phase (`worker_id` must be NULL: the worker is chosen per step, after entry). Once per run, in the durable-admission transaction (gate §7.2), after the `(tenant_id, request_id)` duplicate check; levels in the order tenant → workspace; `UPDATE … AND used_count < limit_value RETURNING …`; zero rows at any level rolls back (hard → DENY; soft → bounded retry, then DENY with `retry_after_ms` and upgrade text). Refund only when the run ends CANCELLED with no step COMPLETED. Invariant I17: `CHECK (used_count <= limit_value)` on every row, so lowering a limit below current usage is rejected; a lower limit goes on the next period's row.

### 3.6 Spawning check (post-S15)

G15 is not an admission gate. Inside `spawn_child_worker()`: lock the parent row (`FOR UPDATE`); count children not in `TERMINATED`; reject `sub_agent_limit_reached` when `count >= max_sub_agents`; reject `max_depth_exceeded` when `depth_level + 1 > max_depth` (one source for `max_depth`: the tenant's plan); child `capability_profile` and grants ⊆ parent's; write the audit row in the same transaction.

---

## 4. Batch Processing (deferred)

Not implemented in S12–S15 (gate v10 C40). The model for its phase:

1. **Selection.** S7 selects the existing BATCH strategy when the input exceeds tenant-configurable thresholds. There is no `BatchSplit` signal from S1 (that would change the certified `NormalizedInput`).
2. **Planning.** S9 produces N ordinary PlanSteps, one per slice, each with its own `plan_step_id`. Each slice therefore has its own step idempotency key `request_id:plan_step_id` (I-021).
3. **Execution.** Each slice is a normal step: admission, eligibility, lease, budget reservation, idempotency, probe, verification. Parallel slices wait for the parallel-step phase.
4. **Recovery.** A slice that was RUNNING at a crash follows gate §13 (ledger → dispatch marker → probe); it is never blindly re-executed.
5. **Consolidation.** Gate §10: all COMPLETED → COMPLETED; mixed → PARTIAL; any DEAD_LETTER → DEAD_LETTER. No batch table with its own states.
6. **Quota.** A batch run consumes one unit of quota, at durable admission.
7. **Data flow.** Combining slice results needs step-to-step data flow (register P0-B), which is still open.

---

## 5. Propagation Record

v1.1.0 §5 proposed edits to five documents. The corrected edits were applied on 2026-09-29 to these documents (details: `WORKER_MGMT_SPEC_REVIEW.md` Part F; change log: `REPAIRS_APPLIED.md`; register: blocker register §19):

| Document | Content |
|---|---|
| `S12_S15_EXECUTION_GATE.md` v10 | C39, C40, C41; preflight 15–16; suite 20; I17, I18 |
| `S12_S15_IMPLEMENTATION_PLAN.md` v3 | M8a; M1 schema |
| `FINAL_ARCHITECTURE.md` 4.5.0 | I-029; §30 tiers; §21 memory classes; §29 decisions; §51 extension points; numbering |
| `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md` | §16; §10, §13 |
| `DATABASE.md` | §2.1 schema; `TEXT` keys; migration 018 |
| `DATA_CONTRACTS.md` | §50–§53 |
| `IDENTITY_AND_TENANCY.md` | Settings contract; assignment; pause vs kill switch |
| `PIPELINE_STAGES.md` | §14, §19, §21 |
| `S12_SESSION0_PREFLIGHT_PROMPT.md` | Gate v10; items 3–16 |
| `STATE_TRANSITIONS.md`, `MUTATION_SAFETY.md`, `SECURITY.md`, `PROVIDER_ADAPTERS.md`, `EVENT_GATEWAY_AND_ROUTER.md`, `VALIDATION.md`, `VOCABULARY_INDEX.md`, `BUILD_READINESS_MATRIX.md` | Supporting rules, terms and tests |

---

## 6. Future Evolution Roadmap

### 6.1 Replanning (F31) — child executions

The plan of a running execution never changes (I-006, I-017; plan digest I9). A replan is a **new execution**:

```
Parent run: step N ends FAILED, or its uncertainty ends DEAD_LETTER (gate §9)
    │
    ▼
Parent consolidates normally (e.g. PARTIAL / DEAD_LETTER) and records the replan request
    │
    ▼
Child execution enters S0 with parent_execution_id = parent
    │  S0 → … → S8 (authorization) → S9 (new plan) → S10 → S11 (new manifest)
    ▼
Child runs through S12–S15 with its own admission, quota and budget
```

Triggers when it lands: a step's definitive failure, an event that invalidates the remaining plan, or a sub-agent result. An inconclusive probe is **not** a replan trigger: it ends DEAD_LETTER (gate §9).

### 6.2 Capability composition / skills (F33)

A `SkillDefinition` (DATA_CONTRACTS §53) is a data-defined DAG of `SkillStep`s, each naming a capability resolved through the registry at S3/S5. **S9** plans a composition into ordinary PlanSteps; S8, S10 and S11 apply unchanged. Admins create compositions as data; the kernel sees only the plan. The Skill Factory compile path is open (register WM-O3).

### 6.3 Memory classification (F21)

Orthogonal to layers L0–L3 (FINAL_ARCHITECTURE §21): Historical (renamed from "Episodic", which is the L0 layer name), Semantic, Procedural, Organizational, Execution, Relationship, Policy. Memory is never read for authorization; "Organizational" and "Policy" entries are informational copies. Every write goes through `MemoryWriteBarrier` (I-014).

### 6.4 Environment independence (F23)

Worker Runtime is deployment-target agnostic behind the Runtime Contract (FINAL_ARCHITECTURE §38) and `WorkerRuntime` (§37a Principle 5). A deployment descriptor (container image, function ARN, edge URL, binary path, Kubernetes deployment) belongs to the deployment subsystem; the kernel never reads it. Worker version/deployment lifecycle is out of the S12–S15 phase.

### 6.5 Heterogeneous workers (F19)

`runtime_type` answers **how** a worker executes; capability matching answers **whether** it can. It never removes a stage (I-029).

| runtime_type | Typical strategy (S7) | Binding family (S5) | Notes |
|---|---|---|---|
| `llm` | Any | LLM runtime adapters | Default |
| `rules` | FAST / REFLEX | Rules engine adapter | No LLM call needed after S2 |
| `vision` | FAST / WORKFLOW | Vision adapter | |
| `browser`, `rpa` | FAST / WORKFLOW (skill compositions) | Browser adapters (§8) | |
| `data` | FAST / WORKFLOW | Data engine adapter | |
| `rag` | WORKFLOW | Retrieval adapter | |
| `code` | WORKFLOW | Sandboxed processor (FINAL_ARCHITECTURE §42) | |
| `human` | HUMAN_ASSISTED | Human task adapter | Stubbed until HITL phase |

### 6.6 Progressive autonomy (F20)

`AutonomyLevel` (`READ_ONLY`, `CONFIRM_ALL`, `SUPERVISED`, `FULLY_AUTONOMOUS`) stays the only autonomy enum. A per-capability refinement, if added, has a different name and can only **restrict** the manifest's level. Promotion is an admin decision, informed by per-worker, per-capability success counts. Changing S8 or S10 behavior is S0–S11 change control.

### 6.7 Policy as a runtime (F22)

Rebased on the IDENTITY §5 chain; each level can only restrict the one above:

```
Tenant Policy
 └── Industry / Regulatory Policy (new)
      └── Workspace Policy
           └── User Role (RBAC)
                └── User Capability Grants
                     └── Worker Capability Grants
                          └── Worker Management Settings (restrict-only)
                               └── Data Policy (new: PII, financial, health)
                                    └── Execution Mode
                                         └── SafetyGate (S8) / Risk Policy
```

The `PolicyEngine` is a kernel-evaluated guard at guardrail level 6 (FINAL_ARCHITECTURE §51 extension point #8). The LLM proposes, the policy engine evaluates, the kernel enforces. S8 change control applies.

### 6.8 Event evolution (F24)

Already present: `sequence_number` and `causation_id` (DATA_CONTRACTS §29; FINAL_ARCHITECTURE §37a Principle 7), `EventCorrelator` (EVENT_GATEWAY §7), replay (FINAL_ARCHITECTURE §47). New: event schema versioning and event dead-lettering. All outside S0–S15. Pause does not change routing (EVENT_GATEWAY §14.7).

### 6.9 Multi-agent delegation (F28)

Delegations and replans are child executions linked by `parent_execution_id`. Children inherit a subset of the parent's capabilities and grants, never more; the PrincipalChain preserves the whole chain and assignment is checked against the original principal.

---

## 7. Stability Tiers T1–T7

Renamed from "Seven-Layer Architecture" (RD-15); the master copy is FINAL_ARCHITECTURE §30. Tiers rank stability; they are not a second layer model (layers are FINAL_ARCHITECTURE §6).

| Tier | Concern | Stability |
|------|---------|-----------|
| T1 | Safety / identity / authorization (S0–S8) | FROZEN after S0–S11 certification |
| T2 | Durable execution + evidence | STABLE after S12–S15 certification; additive only |
| T3 | Providers, protocols, events | Stable; additive |
| T4 | Worker routing, `runtime_type`, model routing | Evolving (C39 filters) |
| T5 | Skill compositions | Evolving; planned at S9 |
| T6 | Multi-agent coordination | Evolving; spawning deferred |
| T7 | Marketplace / business outcomes | Evolving; the kernel never knows marketplace mechanics |

Rules: no tier bypasses a lower tier; each tier can only restrict what lower tiers allow; the PolicyEngine, when it lands, is a T1 change under S0–S11 change control.

---

## 8. Browser and RPA Execution

Replaces v1.1.0's B0–B7 path (RD-8, RD-9). Browser and RPA executions follow S0→S15 like every other execution (FINAL_ARCHITECTURE §37a Principle 8, I-029).

| Concern | Design |
|---|---|
| Entry and authorization | S0 → S8 as usual; S10 confirms IRREVERSIBLE actions; S11 freezes the manifest |
| Recorded sequences | Skill compositions (§6.2) planned at S9 with FAST/WORKFLOW; no LLM planning needed |
| Adapters | `PlaywrightAdapter`, `ApifyAdapter`, `BrowserUseAdapter` behind `BaseAdapter` (PROVIDER_ADAPTERS §9) |
| Provider choice | A binding resolved and frozen at S5; never chosen inside an adapter |
| Mutation levels | MUTATION_SAFETY §1 "Browser and RPA Actions": page-local actions `R`; external-effect actions `IRREVERSIBLE` unless an inverse exists |
| Worker eligibility | Filter 17: `runtime_type` in (`browser`, `rpa`) |
| Verification | Adapter `observe()` (DOM state, extracted-data schema, file existence, screenshot comparison) feeding S13 layers |
| Evidence | Screenshots are artifacts, not context |
| Sessions and credentials | Per-tenant session pool; cookies, logins and proxies via `CredentialProvider` |

Kernel metadata for browser operations comes from the Provider Package (DATA_CONTRACTS header), with levels per the table above:

| Operation | Level | Retry |
|---|---|---|
| `browser_open`, `browser_wait`, `browser_extract`, `browser_screenshot`, `browser_filter`, `browser_export` | `R` | Yes |
| `browser_type` (no submission) | `R` | Yes |
| `browser_click` (navigation only, declared) | `R` | Yes |
| `browser_click` / submit (external effect, no inverse) | `IRREVERSIBLE` | Never |

Build vs integrate: Playwright (self-hosted engine); session management, orchestration, proxy management and screenshot storage are built; high-scale scraping (Apify), AI-driven browsing (BrowserUse) and anti-bot handling are integrated as separate bindings.

---

## 9. S0–S11 Protection List

None of the following may change for worker management. A feature that needs one waits for gate §19.3 change control and re-certification. **One approved exception:** S0–S11 ruling R-P adds a read-only tenant/workspace pause check to the S0 handler (S0.1), with re-certification before S12 starts; it adds no stage, `StageStatus` or contract field.

| Certified artifact | Why it matters here | Affected feature (status) |
|---|---|---|
| `ExecutionContext` (frozen at S0, I-009) | No `dry_run` or worker fields | F13 via sandbox binding instead |
| `NormalizedInput` (S1) | No `BatchSplit` | F9 via BATCH strategy at S7/S9 (deferred) |
| S2 intent analysis (one LLM call, I-011) | `skills_prompt`, `llm_model` would be read here | Inert until change control |
| S5 resolution / `FrozenBindingIdentity` (I-002, I-010) | Provider choice must stay frozen | Browser providers as bindings |
| S7 path routing / `RuntimeRoutingDecision` | Strategy and model frozen per execution | F14, F19 |
| S8 SafetyGate / `SafetyResult` | No new authorization in S12 (gate §1) | F12 at S8, F20, F22 wait |
| `CapabilityGrant` | No `autonomy_level` field | F20 waits |
| S9 plan / `plan_hash` (I9) | No mid-run replacement | F31 as child execution |
| S10 confirmation | Autonomy may not skip confirmation | F20 waits |
| S11 manifest (frozen) | Worker config is not a manifest field | F10 records the version on the step |

---

## 10. Implementation Sequence

| Order | Work | Where |
|---|---|---|
| 1 | Owner rulings RD-1…RD-18 | Done 2026-09-29 |
| 2 | Documents propagated (§5) | Done 2026-09-29 |
| 2a | S0–S11 ruling R-P (pause at S0.1) implemented and S0–S11 re-certified | S0–S11 runbook; gate preflight item 17 |
| 3 | Session 0 preflight on gate v10 (items 1–17, P1–P6), incl. key types and worker tables | Plan M0 |
| 4 | Migration 018 with the rest of the S12–S15 schema | Plan M1 |
| 5 | Leases, fencing, admission, selection | Plan M7, M8 |
| 6 | Worker-management admission, eligibility filters, quota consumption (suite 20, I17, I18) | Plan **M8a** |
| 7 | Remaining S12–S15 milestones and certification | Plan M9–M21 |
| 8 | Post-S15 "worker management II": groups, config versions, webhooks, spawning, batch, replanning, skills, browser adapters | Blocker register §19.3 |
| 9 | Items needing S0–S11 change control: `skills_prompt`/`llm_model`, S8 deny-list, autonomy, PolicyEngine | Gate §19.3 |

---

## Appendix A: Timestamp and Quota Precedence

### Pause and activation

Each level is compared with database `NOW()` on its own; NULL means "not paused" / "already active":

```
S0.1 and S12 entry:  tenant.paused_until > NOW()  OR workspace.paused_until > NOW()        → DENY *_paused
                     tenant.scheduled_activation_at > NOW() OR workspace.… > NOW()          → DENY not_yet_active
Worker selection:    worker.paused_until > NOW()                                            → filter 12b
                     worker.scheduled_activation_at > NOW()                                 → filter 13b
```

Worker groups are post-S15. When they land, a worker in several groups is paused if any of its groups is.

### Operation quota (16)

```
FOR each applicable level IN (tenant, workspace):   -- this order, one transaction, at S12 entry only
    UPDATE ... SET used_count = used_count + 1
     WHERE ... AND used_count < limit_value RETURNING ...
    IF 0 rows → ROLLBACK; hard → DENY quota_exhausted; soft → retry up to quota_retry_max, then DENY with retry_after_ms
No row at any level → no quota configured → PASS
No per-step check.
```

A level blocks when its own `used_count >= limit_value`; there is no single `MIN()` limit compared with one counter.

---

## Appendix B: Settings JSONB Contract

Master copy: IDENTITY_AND_TENANCY §5. All keys optional; restrict-only.

```json
{
    "skills_prompt": "string — inert until S2 change control",
    "rules": ["string — LLM behavior rules; never an authorization input"],
    "restricted_capabilities": ["capability_id — narrows grants"],
    "llm_model": "string — inert until TenantPolicy has a model allow-list",
    "execution_policy": {
        "max_mutation": "'R' | 'W' | 'D' | 'IRREVERSIBLE' — LIVE: worker ineligible above this level (filter 17d)",
        "timeout_seconds": "integer — RESERVED (post-S15); may only shorten",
        "max_retries": "integer — RESERVED (post-S15); may only lower (MUTATION_SAFETY §3 worker_policy_ceiling)",
        "retry_backoff": "'exponential' | 'linear' | 'fixed' — RESERVED (post-S15)"
    },
    "memory_policy": {"session_ttl_hours": "integer", "compaction_strategy": "string", "max_session_memories": "integer"},
    "browser_policy": {"headless": "boolean", "viewport_width": "integer", "viewport_height": "integer",
                        "default_timeout_ms": "integer", "screenshot_on_error": "boolean",
                        "proxy_ref": "string — reference resolved via CredentialProvider"},
    "is_listed": "boolean",
    "listing_config": {"category": "string", "tags": ["string"], "preview_enabled": "boolean"},
    "custom_fields": {}
}
```

Removed from v1.1.0: `execution_policy.circuit_breaker_threshold` (breakers are per provider); `browser_policy.proxy_url` (replaced by a credential reference).

---

## Appendix C: Admission and Eligibility Decision Matrix

| Check | Phase | When | Stateless? | Reserves? | Admin bypass | Failure |
|---|---|---|---|---|---|---|
| 1 Kill switch | Admission | Entry + every step | Yes | No | No | CANCELLED `kill_switch_engaged` (C23) |
| 2 Tenant quota | Admission | Every step | Yes | No | No | REJECT |
| 3 Tenant active | Admission | Every step | Yes | No | No | CANCELLED `authorization_revoked` (C23) |
| 4–6 | Admission | Every step | Yes | No | No | REJECT |
| Tenant/workspace paused | Entry check | S0.1 (R-P) + S12 entry | Yes | No | No | DENY, nothing written, logged |
| Tenant/workspace not yet active | Entry check | S0.1 (R-P) + S12 entry | Yes | No | No | DENY, nothing written, logged |
| 8–9, 11 | Admission | Every step | Yes | No | No | REJECT |
| 10 Budget | Admission | Every step | Yes | No | No | CANCELLED `budget_exhausted` (C15) |
| 7 Capacity | Admission (last) | Every step | Yes | No | No | QUEUE |
| 4b Workspace match | Eligibility | Selection | Yes | No | No | Candidate removed |
| 12b Worker paused | Eligibility | Selection | Yes | No | Yes | Candidate removed |
| 13b Worker not yet active | Eligibility | Selection | Yes | No | Yes | Candidate removed |
| 14 Assignment (human, non-event runs) | Eligibility | Selection | Yes | No | Yes | Candidate removed |
| 17a–c Capability / restricted / runtime match | Eligibility | Selection | Yes | No | No | Candidate removed |
| 17d Mutation ceiling | Eligibility | Selection | Yes | No | No | Candidate removed |
| Quota consumption | Durable admission (S12 entry) | Once per run | No (writes) | Yes (count) | No | DENY (soft: after bounded retry) |

No candidate after eligibility → step `no_worker` with the filter reasons in the ledger.

---

## Appendix D: Out of Scope

Out of scope for S12–S15 and recorded in blocker register §19.3 or earlier registers: provider failover implementation; debug replay; escalation chains beyond HITL; agentic strategies (stubbed); `MemoryWriteBarrier` and L0–L3 storage; multi-region; fleet-level worker management; billing conversion of quota counts; marketplace payment; third-party worker publishing; A2A protocols beyond TaskHandoff; anti-bot evasion (integrated providers only); vision model selection; a UI for recording skill compositions. Extension points: FINAL_ARCHITECTURE §51.
