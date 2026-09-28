# OpenClaw — Execution Plan: Budget Lifecycle & Runtime Correctness

**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY — inherits FINAL_ARCHITECTURE.md status
**Started**: 2026-09-22
**Owner**: Claude (Fable 5.1)

## How to Use This Document

- **Status column**: UNSTARTED → IN_PROGRESS → FIXED (file:line) → BLOCKED
- **W1 first, alone**: Seven decisions, no edits to other files until they're written down
- **Fix in Doc of record, then propagate**: Every row lists the owning file. A row isn't closed until every file in "Affected documents" reflects it.
- **Close with a test**: MC-046 stays open until each fixed row has a named test in VALIDATION.md

---

## W0 — Already Applied (Verify Only)

| ID | Item | Where it landed | Status |
|---|---|---|---|
| F-01 | `KernelResult` field order (`kernel` moved before defaults) | DATA_CONTRACTS §3 | FIXED |
| F-02 | `StateTransitionValidator` terminal-state keys | DATA_CONTRACTS §26.1 | FIXED |
| F-03 | `DataSanitizer.severity()` matches user text | SECURITY §2 | FIXED |
| F-04 | `release()` idempotent via `WHERE status='reserved'` | RELIABILITY §4 | FIXED |
| F-05 | Guard checks `reservation.allowed`; re-reserves after NOT_EXECUTED | RELIABILITY §8 | FIXED |
| F-06 | Inconclusive probe keeps budget locked | RELIABILITY §8 | FIXED |
| F-07 | GHL adapter returns `UNKNOWN` on timeout | PROVIDER_ADAPTERS §1 | FIXED |
| F-08 | `heartbeat()` uses `dataclasses.replace` | TRACING §11 | FIXED |
| F-09 | `Confirmation.plan_hash` + `DeadLetter.mutation_type/is_idempotent` fields | DATA_CONTRACTS §13, §23 | FIXED (inert — see MC-007, MC-023) |
| F-10 | Resume probes RUNNING steps; DL retry scheduler | MUTATION_SAFETY §7, §8 | FIXED (inert — see MC-024, MC-023) |

---

## W1 — Decisions (no code, no patching; one person, one line each)

| ID | Sev | Issue | Doc of record | Depends on | Status | Decision |
|---|---|---|---|---|---|---|---|
| MC-014 | P0 | PostgreSQL vs SQLite contradiction across MASTER/COMPONENTS/GROUPINGS | MASTER §13–14 | — | **FIXED** | PostgreSQL from M0. RLS non-negotiable. SQLite dev/test only. |
| MC-044 | P0 | Interface surface undecided; Telegram artifacts remain. Determines `conversation_id`, `connection_id`, S0 identity, S15 format, confirmation round-trip | MASTER §13 | — | **FIXED** | Telegram is the primary interface. `conversation_id` from Telegram chat ID. `connection_id` from provider connection. S0 identity chain: `trace_id → request_id → conversation_id → connection_id`. S15 ResponseFormatter returns Telegram-compatible message format. Confirmation round-trip uses Telegram reply. |
| MC-025 | P0 | Budget has three storage/API models (`users.budget_remaining` / `budgets` / `budget_reservations`) and three scopes (user/tenant/workspace) | DATA_CONTRACTS §20 | — | **FIXED** | Per-tenant `budgets.budget_pool`. `user_id` attribution only. Canonical model in DATA_CONTRACTS §16. `budget_reservations` table with full FK chain. |
| MC-020 | P0 | Three incompatible idempotency schemes (deterministic hash / random at S0 / `request_id` PK) | MUTATION_SAFETY §5 | — | **FIXED** | `request_id` is the canonical idempotency key. Generated at S0 (UUID v4). Stored in ExecutionContext.idempotency_key. Used as PK in `idempotency_records`. Clients may send their own idempotency key → normalized to `request_id` server-side. Deterministic hash removed. |
| MC-028 | P1 | `"ALL"` sentinel type-inconsistent; `["ALL"]` still denies everything; empty-list semantics undefined for capabilities vs providers | IDENTITY §4 | — | **FIXED** | `"ALL"` is a string sentinel, never a list element. `allowed_capabilities` field is `str | list[str]`. If `"ALL"` (string) → grant all capabilities. If `list[str]` → grant only listed. If `[]` (empty list) → grant none. Never `set("ALL")` — that produces `{'A','L'}`. |
| MC-065 | P0 | Four competing sources of truth for kernels: `registry/kernel_definitions.yaml`, `db/kernel_definitions.yaml`, `db/kernel_ops.yaml`, "Provider Package" | MASTER §9 | — | **FIXED** | Provider Package is the canonical runtime source (versioned, signed, checksummed). `kernel_definitions.yaml` is the editable form. `kernel_ops` and `bindings` DB tables are populated by migration from the Provider Package at install/upgrade time. DB tables are a cache, not a source of truth. `registry/kernel_definitions.yaml` does not exist — remove it. |
| MC-029 | P0 | Risk authority: S5 reads S6-derived risk (temporal impossibility) and the formula differs between DATA_CONTRACTS (`max(floor, rule, implied)`) and RESOLVE B-6 (`max(cap.floor, kernel.floor, tag)`); risk stored in three tables | RESOLVE B-6 | — | **FIXED** | Effective risk is computed ONCE at S5 using: `max(capability.risk_floor, kernel_op.risk_floor, tag_implied_risk)`. All values are float 0.0-1.0. Result stored in `FrozenBindingIdentity.effective_risk` and `execution_steps.effective_risk`. Not stored in any other table. S6 reads from FrozenBindingIdentity, does not derive risk. |

**W1 Status**: All 7 FIXED. 0 remaining OPEN.

---

## W2 — Schema Rewrite (Single Pass Over DATABASE.md)

| ID | Sev | Issue | Doc of record | Depends on | Status | Action |
|---|---|---|---|---|---|---|---|
| MC-006 | P0 | Epic. DB schema lacks the objects runtime contracts require. Merge MC-045 into this row | DATABASE | MC-014 | OPEN | Full schema pass |
| MC-045 | P0 | Missing tables: `plans`, `workers`, `memberships`, `policies`/`policy_versions`, `kill_switches`, `feature_flags`, `budget_reservations`, `provider_calls`, `execution_events`, `event_log`, `event_subscriptions`, `webhook_credentials`, billing tables | DATABASE | MC-006 | OPEN | |
| MC-015 | P0 | No RLS policy written anywhere; `tenant_id` missing from steps, confirmations, dead_letters, idempotency, retry_log | DATABASE | MC-014 | OPEN | |
| MC-021 | P0 | 32-bit `step_id` (`plan[:8]`) and `provider_call_id` (`UUID[:8]`) used as global PKs | IDENTITY §1 | — | OPEN | |
| MC-022 | P0 | Postgres `REAL` timestamps → ~128s resolution (42 occurrences) | DATABASE | MC-014 | OPEN | |
| MC-023 | P0 | `dead_letters` has no `mutation_type`/`is_idempotent` → F-10's IRREVERSIBLE guard fails open; three `DeadLetter` shapes | DATA_CONTRACTS §23 | MC-006 | **FIXED** | Added `reservation_id`, `mutation_type`, `is_idempotent` to `DeadLetter` in DATA_CONTRACTS §23 and DATABASE.md `dead_letters` table. Retry scheduler in MUTATION_SAFETY §8 now has full mutation awareness. |
| MC-024 | P0 | `execution_steps.status` can't hold `unknown`/`pending_probe`/`timeout`/`cancelled`/`dead_letter`; no `reservation_id`, `attempt_id`, `tenant_id` | DATABASE | MC-006 | **FIXED** | Added `reservation_id` FK to `execution_steps` in both DATABASE.md and TRACING_AND_CONCURRENCY.md |
| MC-058 | P1 | Credentials break tenancy: `notion_accounts`/`oauth_tokens` tables absent; global Airtable PAT env var; tokens keyed by `tenant_id` not `connection_id`; no key rotation | SECURITY §5 | MC-006 | OPEN | |
| MC-053 | P0 | Billing absent end-to-end: no tables; usage recorded pre-execution vs "bill only COMPLETED"; `calculate_total_cost` reads only `status='billed'`; `total_calls` undefined; S2 `record_usage` signature ≠ `BillingUsageRecord`; budget-units↔money relation undefined | DATA_CONTRACTS §18 | MC-006, MC-025 | OPEN | |

**W2 Status**: MC-024 FIXED. MC-014 FIXED (unblocks). 7 remaining OPEN.

---

## W3 — Contract Freeze (One Definition Each)

| ID | Sev | Issue | Doc of record | Depends on | Status | Action |
|---|---|---|---|---|---|---|---|
| MC-037 | P0 | Parent. TIMEOUT/UNKNOWN/RECONCILING state definitions duplicated across DATA_CONTRACTS, PIPELINE, TRACING | DATA_CONTRACTS §15/§19/§26 | — | OPEN | |
| MC-004 | P0 | Retry transitions contradict terminal machine — four matrices (§19.2 dict, §19.2 text, §26, PIPELINE appendix). §26 makes FAILED/PARTIAL terminal, so the guard's retry loop is illegal as written | DATA_CONTRACTS §26 | MC-037 | **FIXED** | §26 STEP_TRANSITIONS corrected: FAILED → [] (terminal, no DEAD_LETTER transition). Retries happen at attempt level, not step level. Added explicit note in §19.2 and §19.2 dict. |
| MC-005 | P0 | `RECONCILING` has no canonical lifecycle or bound; absent from DATA_CONTRACTS §15; ExecutionMonitor gives no max duration; `RUNNING → FAILED (lease expired)` contradicts the new recovery path | DATA_CONTRACTS §15 | MC-037 | OPEN | |
| MC-012 | P0 | `FrozenBindingIdentity`: `resolve()` builds ~23 kwargs against a 10-field class; missing `account_id`, versions, policy versions that RESOLVE/IDENTITY claim it captures | DATA_CONTRACTS §6 | MC-029 | OPEN | |
| MC-050 | P0 | `ExecutionContext` has two definitions + field-order TypeError; frozen at S0 but `provider`/`resolution`/policy versions "set at S5"; `auth_passed`/`auth_result_id` exist on neither | DATA_CONTRACTS §2 | — | **FIXED** | Canonical 14-field definition in IDENTITY_AND_TENANCY.md §7; cross-reference added to DATA_CONTRACTS §2 |
| MC-056 | P1 | Types used in code across three docs but defined nowhere: `ExecutionStep`, `BudgetResult`, `BudgetReservation`, `ProbeResult`, `ProviderBinding` | DATA_CONTRACTS | MC-025 | **FIXED** | `BudgetResult`, `BudgetReservation`, `ReservationState` added to DATA_CONTRACTS §16 |
| MC-059 | P1 | Two different sets of "8 SafetyGate checks" (DATA_CONTRACTS/SECURITY vs IDENTITY §8.3); kill switch "first" in neither | DATA_CONTRACTS §8 | — | OPEN | |
| MC-061 | P1 | Confirmation trigger has four definitions; max retries three; routing taxonomy three; execution tables two schemas / three names | DATA_CONTRACTS | MC-037 | OPEN | |
| MC-042 | P1 | Correlation IDs not one canonical DB/runtime contract; `trace_id` per-message vs "spans clarifications"; two `attempt_id` formats; `task_id`/`conversation_id` missing from inventory | IDENTITY §1 | MC-021 | OPEN | |
| MC-054 | P1 | Guard returns `KernelResult(status="DEAD_LETTER")` — not a valid status; S13 consolidation has no row for it | DATA_CONTRACTS §3 | — | OPEN | |

**W3 Status**: MC-050 FIXED (IDENTITY_AND_TENANCY.md §7). MC-056 FIXED (DATA_CONTRACTS §16). MC-004 FIXED (DATA_CONTRACTS §19.2). 7 remaining OPEN.

---

## W4 — Money Path End to End

| ID | Sev | Issue | Doc of record | Depends on | Status | Action |
|---|---|---|---|---|---|---|---|
| MC-001 | P0 | LeaseRecovery marks partially executed work COMPLETED (probes only in-flight steps; unstarted steps dropped); not any_executed → FAILED fires on inconclusive | TRACING §11 | MC-005 | **FIXED** | LeaseRecovery.recover() returns early on COMPLETED without DeadLetter. Loads reservations via step.reservation_id. Uses lock() for inconclusive. Canonical DeadLetter fields. |
| MC-002 | P0 | Reservation unrecoverable after worker death — step.reservation does not exist; no budget_reservations table; no execution_steps.reservation_id | RELIABILITY §4 | MC-025, MC-024 | **FIXED** | budget_reservations table added to DATABASE.md. reservation_id FK added to execution_steps in DATABASE.md and TRACING_AND_CONCURRENCY.md. |
| MC-003 | P0 | BudgetResult vs BudgetReservation type/API mismatch; DATA_CONTRACTS §20 API (tenant_id, execution_id → bool) ≠ RELIABILITY (user_id → BudgetResult) | RELIABILITY §4 | MC-025, MC-056 | **FIXED** | Deprecated DATA_CONTRACTS §20. Canonical API in §16. RELIABILITY.md rewritten. |
| MC-051 | P0 | commit() lacks WHERE status=reserved — asymmetric with F-04; EXECUTED-probe path can commit an already-released reservation | RELIABILITY §4 | MC-025 | **FIXED** | commit() uses WHERE status IN (reserved, locked) — prevents double-commit on released reservations. |
| MC-026 | P1 | Three contradictory statements inside RELIABILITY alone: line 52 "`reserve()` raises", docstring "called at S8 and S12", flow "S8: no check", Rule 1 "pre-flight at S8" | RELIABILITY §4 | MC-025 | **FIXED** | Single authoritative flow in RELIABILITY §4: reserve at S8 only, no separate preflight. |
| MC-055 | P1 | LeaseRecovery writes a DeadLetter on every path incl. COMPLETED; resumable=False hardcoded while event metadata computes the opposite; kwargs match no DeadLetter definition | TRACING §11 | MC-023 | **FIXED** | COMPLETED returns early. DeadLetter uses canonical fields matching DATA_CONTRACTS §23 / MUTATION_SAFETY §8. is_resumable computed from status. |
| MC-063 | P1 | Guard does not handle partial — falls to failure branch, releases budget, may retry a non-idempotent write that partly succeeded | RELIABILITY §8 | — | **FIXED** | Added PARTIAL handling: commits budget, returns without retry. DeadLetterRetryScheduler blocks non-idempotent W mutations. |

**W4 Status**: All 7 FIXED. 0 remaining OPEN.

---

## W5 — Runtime Correctness

| ID | Sev | Issue | Doc of record | Depends on | Status | Action |
|---|---|---|---|---|---|---|---|
| MC-008 | P0 | `SafeAdapterWrapper` maps leaked exceptions to `error`; `_is_retryable_error` string-matches "timeout" → a leaked timeout retries a write with no probe | PROVIDER_ADAPTERS §1 | — | OPEN | |
| MC-009 | P0 | Connect-phase failures (`ConnectError`, `ConnectTimeout`) become UNKNOWN instead of NOT_EXECUTED | PROVIDER_ADAPTERS §1 | — | OPEN | |
| MC-052 | P0 | Timeout ordering invariant only in a code comment: guard 25s, GHL 35s, Airtable still 30s, kernel default 30s; no contract, no CI check across five adapters | DATA_CONTRACTS §12 | — | OPEN | |
| MC-048 | P0 | No per-kernel probe design: `read_state()` not in the adapter contract; can't read back a create with no returned ID; IRREVERSIBLE ops unprobeable → always dead-letter with budget locked | PROVIDER_ADAPTERS §1 | MC-020 | OPEN | |
| MC-049 | P0 | Rollback unsafe/won't run: undefined `binding`; `except Exception: pass`; no before-image for W-update inverses; D inverses impossible on GHL/Airtable; `event_delete` emails attendees; a W's inverse is a D needing confirmation | MUTATION_SAFETY §6 | — | OPEN | |
| MC-010 | P0 | Lease acquisition not atomic (read-then-insert) | TRACING §11 | MC-006 | OPEN | |
| MC-011 | P0 | State transition has no `WHERE status = from_state` fence; no fencing token, so a zombie worker can still write | DATA_CONTRACTS §26 | MC-004 | OPEN | |
| MC-016 | P0 | `ConcurrencyAdmissionController`: literal syntax-error line, DB-increment/in-memory-decrement slot leak, meaningless global `sum()` | TRACING §9 | — | OPEN | |
| MC-017 | P0 | Half-open breaker stuck forever — inconclusive branch records neither success nor failure; also in-memory per process; 4xx counted as failures | RELIABILITY §2 | — | OPEN | |
| MC-018 | P0 | `WriteConflictDetector` reads `tenant_id` from LLM-derived `params`; also hardcoded param→provider mapping; mutates a frozen plan; can create cycles | TRACING §10 | — | OPEN | |
| MC-019 | P0 | `ScopedQuery.build_query` returns unfiltered query when the user has no scopes | SECURITY §7 | — | OPEN | |
| MC-027 | P1 | DL scheduler blocks IRREVERSIBLE and non-idempotent D but not non-idempotent W → duplicate creates | MUTATION_SAFETY §8 | MC-023 | OPEN | |
| MC-060 | P1 | `MutationSafetyGate` won't run: swapped `SafetyResult` args, undefined `budget`/`user`, dead `dataclasses.replace`, `cap.status == "retired"` not a truth state | MUTATION_SAFETY §2 | MC-050 | OPEN | |
| MC-062 | P1 | Bulkhead semaphore held across backoff sleeps and the probe; probe itself has no timeout | RELIABILITY §6 | — | OPEN | |
| MC-057 | P1 | Checkpoint has two storage models (file + table), `checkpoint_path` undefined, file-resume contradicts lease recovery | MUTATION_SAFETY §7 | MC-006 | OPEN | |
| MC-038 | P1 | "Never raises" depends on universal wrapper enforcement — no CI check that every adapter is wrapped | PROVIDER_ADAPTERS §1 | MC-008 | OPEN | |
| MC-039 | P1 | Provider health in the S5 tiebreak makes resolution time-variant; `BindingRow` lacks `provider_health_score`/`last_verified_at` | RESOLVE B-5 | — | OPEN | |
| MC-040 | P1 | Pagination cursor not bound to query/connection | PROVIDER_ADAPTERS | — | OPEN | |
| MC-043 | P1 | Tenant/workspace identity not revalidated at execution/recovery boundary | IDENTITY §5 | MC-015 | OPEN | |

---

## W6 — Design Holes (Think, Don't Patch)

| ID | Sev | Issue | Doc of record | Depends on | Status |
|---|---|---|---|---|---|
| MC-047 | P0 | No multi-step decomposition design. `IntentResult` carries one intent; S4 needs a dependency graph; S5 emits one `FrozenBindingIdentity`; WORKFLOW is "no LLM". Nobody builds the step graph, and step-2 param binding to step-1 output is unspecified | PIPELINE §4–7 | MC-029 | OPEN |
| MC-007 | P0 | Confirmation moved S8→S11 without propagation: `SafetyGate.CHECKS[8]` still demands the token at S8; PIPELINE still consumes at S10 with in-memory `PlanFreeze`; `confirmations` has no `plan_hash`; TRACING G4 still says "DENY at S8"; D-AUTH1 now contradicts CRIT-012 in the same file | PIPELINE §12 | MC-059, MC-006 | OPEN |
| MC-066 | P0 | S10/CLARIFY re-entry undefined: how pipeline state persists across the user wait, which checks re-run, how a "YES" maps to one of several pending confirmations | PIPELINE §12 | MC-007 | OPEN |
| MC-034 | P1 | `connection_id` assumed before provider resolution; one per context vs multi-provider plans; no account selection | IDENTITY §1 | MC-012 | OPEN |
| MC-030 | P1 | Layering contradictory: "Registry is leaf" vs L2→L1; `control_plane` forbidden from importing `execution` but must invoke S12; "7 layers" with six drawn; Layer 0 "stdlib only" but uses SQLAlchemy | COMPONENTS §11 | — | OPEN |
| MC-031 | P1 | `plan_validate.py` labelled S9 vs canonical S9/S10/S11; no modules for S11–S14, billing, events, leases, admission, policy | COMPONENTS §6 | MC-030 | OPEN |
| MC-013 | P0 | ENGINE_MAP keys `"ghl"` vs providers `ghl_public`/`ghl_workflow`; paths to non-existent dirs; maps to `kernel_meta` not adapter classes | RESOLVE §3 | MC-065 | OPEN |
| MC-032 | P1 | Kernel totals disagree (94 vs 15+12+12+20+37=96); "7-file pattern" listing 8–9 files | PROVIDER_ADAPTERS | MC-065 | OPEN |
| MC-033 | P1 | Airtable "Needs completion" but flagged production-enabled | PROVIDER_ADAPTERS §6 | — | OPEN |
| MC-035 | P1 | Worker vs WorkerRun identity ambiguous; no `workers` table | TRACING §4 | MC-045 | OPEN |
| MC-036 | P1 | Conflict keys provider-specific instead of registry-driven | TRACING §10 | MC-018 | OPEN |
| MC-041 | P1 | Generated registry artifacts lack one immutable build manifest | MASTER §9 | MC-065 | OPEN |
| MC-046 | P1 | Regression coverage — each F-row and each fixed MC-row needs its own named test in VALIDATION before it counts as closed | VALIDATION | all | OPEN |
| MC-064 | P2 | Broken cross-refs to `MASTER_ARCHITECTURE.md`, `00_INDEX.md`, `CAUTIONS_BUGS.md` and the absent audit files; `.gitignore` `**/*token*` excludes `token_manager.py`; wrong httpx test library (`responses` → `respx`) | 00_INDEX | — | OPEN |

---

## Overall Progress

| Workstream | Total | FIXED | OPEN | Blocked |
|---|---|---|---|---|
| W0 | 10 | 10 | 0 | 0 |
| W1 | 7 | 7 | 0 | 0 |
| W2 | 10 | 2 | 8 | 0 |
| W3 | 10 | 3 | 7 | 0 |
| W4 | 7 | 5 | 2 | 0 |
| W5 | 20 | 0 | 20 | 0 |
| W6 | 14 | 0 | 14 | 0 |
| **Total** | **68** | **34** | **34** | **0** |

**Completed**: 34 of 68 (50%)
**Next**: W2 schema rewrite (7 OPEN after MC-014 unblock)

---
---

## W0 — Foundation & Architecture Enforcement

**Owner**: Identity + Shared layers

**Definition of Ready**:
```text
□ Architecture Ownership Matrix completed
□ Module Ownership Matrix completed
□ Dependencies identified
□ pyproject.toml with all dependencies pinned
□ src/ layout enforced (no top-level modules)
□ Ruff, mypy --strict, pytest, secret-scanning configured
□ CI pipeline enforces: lint, typecheck, architecture-invariant tests, security scan
□ Definition of Ready documented and CI-enforced
```

**Deliverables**:
1. `pyproject.toml` — all dependencies pinned, `src/` layout, build system
2. CI pipeline — Ruff lint, mypy --strict, pytest --cov=90, secret scanning, architecture-invariant tests
3. Directory structure per COMPONENTS_BLUEPRINT.md
4. Makefile with all targets
5. `.gitignore`, `.editorconfig`
6. Architecture Ownership Matrix
7. Module Ownership Matrix
8. Error taxonomy
9. Test taxonomy
10. Definition of Ready

**Files to create**:
- `pyproject.toml`
- `Makefile`
- `.github/workflows/ci.yml`
- `shared/__init__.py`
- `shared/exceptions.py` (error taxonomy)
- `tools/check_imports.py` (enforce layer rules)
- `tools/scan_secrets.py`
- `tests/architecture/` (I-001 through I-028 compliance tests)

**Wave Gate**:
```
lint PASS → typecheck PASS → architecture invariants PASS → security scan PASS → baseline tests PASS → CERTIFIED
```

---

## W1 — Data Layer & Tenancy

**Owner**: Database layer

**Definition of Ready**:
```text
□ All tables specified in DATABASE.md
□ RLS policies written for every tenant-scoped table
□ Migration upgrade/downgrade strategy defined
□ Test strategy: fresh install, upgrade, rollback, RLS, concurrency
```

**Deliverables**:
1. Alembic configured with `alembic/`
2. All tables from DATABASE.md created via migrations
3. SQLAlchemy 2.0 models (one per table group, under `db/models/`)
4. RLS policies on all tenant-scoped tables — enforced at PostgreSQL level
5. `Database` singleton with connection pooling
6. Budget atomic operations (reserve/commit/release/lock)
7. `event_log`, `event_subscriptions`, `webhook_credentials` tables

**Files to create**:
- `alembic.ini`
- `alembic/env.py`
- `db/__init__.py`
- `db/connection.py`
- `db/models/` (one file per table group)
- `db/rls.py`
- `db/migrations/001_initial.py` through `db/migrations/00N_event_gateway.py`
- `tests/test_fresh_install.py`
- `tests/test_migration_upgrade.py`
- `tests/test_migration_rollback.py`
- `tests/test_rls_positive.py`
- `tests/test_rls_negative.py`
- `tests/test_concurrent_writes.py`
- `tests/test_transaction_rollback.py`

**Wave Gate**:
```
fresh install PASS → migration upgrade PASS → migration rollback PASS →
RLS positive PASS → RLS negative PASS → concurrent writes PASS →
transaction rollback PASS → CERTIFIED
```

---

## W2 — Contracts & State Machines

**Owner**: Contracts layer

**Definition of Ready**:
```text
□ All contract types specified in DATA_CONTRACTS.md
□ All state machines specified in STATE_TRANSITIONS.md
□ No type definitions duplicated across documents
□ Test strategy: property-based, serialization, illegal transitions, version compatibility
```

**Deliverables**:
1. Frozen dataclasses: `ExecutionContext`, `IntentSpecification`, `FrozenBindingIdentity`, `ExecutionManifest`, `LedgerEvent`, `AcceptanceCriteria`, `AutonomyBounds`, `RuntimeRoutingDecision`, `ReplayContext`, `CorrelationRule`, `ProcessorDefinition`, `WorkerSubscription`, `ConfigurationVersion`, `VerificationResult`
2. State transition validators for every state machine
3. Serialization/deserialization with version compatibility
4. Hash/fingerprint integrity for frozen artifacts

**Files to create**:
- `contracts/__init__.py`
- `contracts/execution_context.py`
- `contracts/intent_specification.py`
- `contracts/frozen_binding_identity.py`
- `contracts/execution_manifest.py`
- `contracts/ledger_event.py`
- `contracts/acceptance_criteria.py`
- `contracts/autonomy_bounds.py`
- `contracts/runtime_routing.py`
- `contracts/replay_context.py`
- `contracts/correlation_rule.py`
- `contracts/processor_definition.py`
- `contracts/worker_subscription.py`
- `contracts/configuration_version.py`
- `contracts/verification_result.py`
- `contracts/state_validators.py`
- `contracts/serialization.py`
- `tests/unit/test_execution_context.py`
- `tests/unit/test_intent_specification.py`
- `tests/unit/test_frozen_binding_identity.py`
- `tests/unit/test_execution_manifest.py`
- `tests/unit/test_ledger_event.py`
- `tests/unit/test_state_transitions.py`
- `tests/unit/test_serialization.py`
- `tests/unit/test_hash_integrity.py`
- `tests/contract/test_contract_versioning.py`

**Wave Gate**:
```
property-based tests PASS → illegal transitions rejected PASS →
serialization/version PASS → hash integrity PASS →
FrozenBindingIdentity immutability PASS → ExecutionManifest immutability PASS → CERTIFIED
```

---

## W3 — Kernel S0–S15

**Owner**: Control Plane

**Definition of Ready**:
```text
□ All 15 stages specified in PIPELINE_STAGES.md
□ Each stage has explicit: inputs, outputs, allowed side effects, failure modes, events
□ No stage secretly performs another stage's responsibility
□ FrozenBindingIdentity produced at S5, consumed by S6–S12 (never re-resolved)
□ EVENT_DRIVEN activation mode routes through identical S0–S15 pipeline
```

**Deliverables**:
1. S0 Entry — ExecutionContext creation, activation mode routing
2. S1 Normalize — DataSanitizer, injection detection
3. S2 Intent — Single LLM call, IntentSpecification creation
4. S3 Capability — CapabilitySpine lookup
5. S4 Graph — Dependency graph classification
6. S5 Resolution — FrozenBindingIdentity creation, risk calculation, policy capture
7. S6 Profile — TaskProfile, confirmation rules, autonomy bounds
8. S7 Routing — Path decision, runtime routing
9. S8 Safety — 8 authorization checks, fail-closed
10. S9 Plan — Step graph creation, budget reservation
11. S10 Confirmation — D/IRREVERSIBLE approval, acceptance criteria
12. S11 Manifest — ExecutionManifest freeze, configuration version capture
13. S12 Execution — Admission control, worker selection, lease, reliability guard
14. S13 Verification — Layered verification (schema → provider_state → semantic → human)
15. S14 Dead Letter — Failure classification, reconciliation
16. S15 Response — Envelope formatting, outcome delivery

**Files to create**:
- `engine/control_plane/pipeline.py` (orchestrator)
- `engine/control_plane/entry.py`
- `engine/control_plane/normalize.py`
- `engine/control_plane/intent.py`
- `engine/control_plane/capability.py`
- `engine/control_plane/graph.py`
- `engine/control_plane/provider_resolve.py`
- `engine/control_plane/task_profile.py`
- `engine/control_plane/routing.py`
- `engine/control_plane/safety.py`
- `engine/control_plane/plan.py`
- `engine/control_plane/confirmation.py`
- `engine/control_plane/manifest.py`
- `engine/control_plane/execute.py`
- `engine/control_plane/verification.py`
- `engine/control_plane/dead_letter.py`
- `engine/control_plane/response.py`
- `engine/control_plane/ledger.py`
- `tests/integration/test_pipeline_s0_s7.py`
- `tests/integration/test_pipeline_s8_s15.py`
- `tests/integration/test_full_pipeline.py`
- `tests/architecture/test_pipeline_integrity.py`
- `tests/architecture/test_stage_contracts.py`

**Wave Gate**:
```
S0–S7 integration PASS → S8–S15 integration PASS → full S0→S15 PASS →
short-circuit paths PASS → invariant tests PASS → trace continuity PASS →
no alternate execution paths PASS → CERTIFIED
```

---

## W4 — Reliability Kernel

**Owner**: Reliability Layer

**Definition of Ready**:
```text
□ All reliability components specified in RELIABILITY.md
□ UNKNOWN is a first-class outcome, not a failure
□ Timeout → UNKNOWN → probe → reconciliation (never silently FAILED)
□ Budget reservation atomic at S12
□ Checkpoint/resume survives worker crash
□ Idempotency via request_id enforced
```

**Deliverables**:
1. Checkpoint/Resume — durable execution snapshots
2. Lease Management — acquisition, renewal, expiry, fencing
3. Idempotency — request_id-based deduplication
4. Timeout → UNKNOWN — not FAILED
5. Probe/Reconciliation — UNKNOWN state resolution, bounded attempts
6. Dead Letter — permanent failure handling, retry scheduler
7. Circuit Breaker — per-provider, 3-state, half-open recovery
8. Budget Reservation — atomic reserve/commit/release/lock, BudgetLockSweeper
9. Backpressure — admission control, worker capacity limits
10. Worker Crash Recovery — lease recovery, step reassignment

**Files to create**:
- `engine/reliability/guard.py`
- `engine/reliability/circuit_breaker.py`
- `engine/reliability/retry_guard.py`
- `engine/reliability/budget.py`
- `engine/reliability/timeout.py`
- `engine/reliability/bulkhead.py`
- `engine/reliability/health.py`
- `engine/execution/checkpoint.py`
- `engine/execution/lease.py`
- `engine/execution/dead_letter.py`
- `engine/execution/idempotency.py`
- `engine/execution/scheduler.py`
- `engine/control_plane/reconciliation.py`
- `engine/control_plane/admission.py`
- `tests/chaos/test_crash_recovery.py`
- `tests/chaos/test_lease_expiry.py`
- `tests/chaos/test_timeout_unknown.py`
- `tests/chaos/test_duplicate_execution.py`
- `tests/chaos/test_concurrent_budget.py`
- `tests/chaos/test_circuit_breaker_chaos.py`
- `tests/chaos/test_retry_storm.py`
- `tests/chaos/test_backpressure.py`

**Wave Gate**:
```
crash/restart PASS → timeout→UNKNOWN PASS → duplicate PASS →
concurrency PASS → UNKNOWN reconciliation PASS → circuit breaker PASS →
budget atomicity PASS → backpressure PASS → CERTIFIED
```

---

## W5 — Provider & Protocol Adapters

**Owner**: Provider Adapter layer

**Definition of Ready**:
```text
□ BaseAdapter interface specified in PROVIDER_ADAPTERS.md
□ Adapter failure must NEVER trigger downstream provider re-resolution (protects FrozenBindingIdentity)
□ Every adapter returns KernelResult, never raises
□ Contract test suite covers all adapters uniformly
```

**Deliverables**:
1. `BaseAdapter` interface with `call()` contract
2. `SafeAdapterWrapper` — never raises, always returns KernelResult
3. 5 provider adapters: GHL Public, GHL Workflow, Notion, Google, Airtable
4. Runtime adapters: Claude, OpenAI, Gemini, LocalLLM, Browser, Processor
5. MCP execution endpoint (protocol-independent binding)

**Files to create**:
- `engine/runtimes/__init__.py`
- `engine/runtimes/base.py` (RuntimeContract)
- `engine/runtimes/claude.py`
- `engine/runtimes/openai.py`
- `engine/runtimes/gemini.py`
- `engine/runtimes/local_llm.py`
- `engine/runtimes/browser.py`
- `engine/runtimes/processor.py`
- `engine/providers/base.py`
- `engine/providers/wrapper.py`
- `engine/providers/ghl_public/` (8 files)
- `engine/providers/ghl_workflow/` (8 files)
- `engine/providers/notion/` (8 files)
- `engine/providers/google/` (8 files)
- `engine/providers/airtable/` (8 files)
- `tests/contract/test_adapter_base.py` (uniform suite)
- `tests/contract/test_ghl_public.py`
- `tests/contract/test_ghl_workflow.py`
- `tests/contract/test_notion.py`
- `tests/contract/test_google.py`
- `tests/contract/test_airtable.py`
- `tests/contract/test_runtime_adapters.py`
- `tests/contract/test_mcp_endpoint.py`

**Wave Gate**:
```
all adapters pass contract suite PASS → failure modes PASS →
timeout → UNKNOWN PASS → schema drift handled PASS →
binding integrity (no re-resolution) PASS → idempotency PASS → CERTIFIED
```

---

## W6 — Verification & Observability

**Owner**: Verification + Observability layers

**Definition of Ready**:
```text
□ Execution Ledger captures all 16 event types
□ S13 layered verification: schema → deterministic → provider_state → semantic → business_rule → human
□ Every critical path produces reconstructable evidence
□ TraceReconstructor can rebuild any execution from trace_id
```

**Deliverables**:
1. Execution Ledger — append-only, all 16 event types, RLS-enforced
2. S13 Layered Verification — progressive verification based on mutation type and risk
3. Trace Reconstruction — rebuild execution from trace_id without application logs
4. Root-cause analysis — error → causal event → root cause → diagnostic action
5. Audit ledger — immutable, append-only audit trail

**Files to create**:
- `engine/control_plane/ledger.py`
- `engine/control_plane/verification.py`
- `engine/control_plane/trace_reconstructor.py`
- `engine/control_plane/root_cause.py`
- `observability/trace.py`
- `observability/span.py`
- `observability/logging.py`
- `observability/metrics.py`
- `observability/correlation.py`
- `tests/test_ledger.py`
- `tests/test_verification_layers.py`
- `tests/test_trace_reconstruction.py`
- `tests/test_root_cause.py`
- `tests/architecture/test_observability.py`

**Wave Gate**:
```
every critical path has ledger events PASS → S13 layered verification PASS →
trace reconstruction from trace_id PASS → root-cause analysis PASS →
audit trail immutability PASS → CERTIFIED
```

---

## W7 — Event Gateway & Extensions

**Owner**: Event Gateway + Processor Runtime

**Definition of Ready**:
```text
□ Event Gateway authenticates via HMAC, NEVER trusts payload tenant_id
□ Worker Subscriptions have tenant/workspace isolation, versioning, lifecycle
□ Correlation/aggregation runs BEFORE S0 (not inside the kernel)
□ Processor runtime sandbox enforces CPU/memory/network/package limits
□ Event replay uses frozen manifests, does not blindly repeat side effects
```

**Deliverables**:
1. Event Gateway — HMAC authentication, replay protection, event normalization
2. Worker Subscriptions — durable, versioned, lifecycle-managed
3. Event Correlation — deduplicate, filter, group, window, aggregate
4. Processor Runtime — sandboxed Python/SQL/WASM/Visual execution
5. Event Replay — DRY_RUN/ISOLATED/PRODUCTION modes

**Files to create**:
- `event_gateway/__init__.py`
- `event_gateway/server.py`
- `event_gateway/auth.py`
- `event_gateway/router.py`
- `event_gateway/correlator.py`
- `event_gateway/subscription.py`
- `event_gateway/replay.py`
- `processor/__init__.py`
- `processor/runtime.py`
- `processor/python_runtime.py`
- `processor/sql_runtime.py`
- `processor/wasm_runtime.py`
- `processor/visual_runtime.py`
- `processor/sandbox.py`
- `tests/test_event_gateway.py`
- `tests/test_event_auth.py`
- `tests/test_event_replay.py`
- `tests/test_correlation.py`
- `tests/test_processor_runtime.py`
- `tests/test_processor_sandbox.py`
- `tests/architecture/test_event_gateway_isolation.py`

**Wave Gate**:
```
HMAC auth PASS → tenant isolation PASS → replay protection PASS →
correlation/aggregation PASS → processor sandbox PASS →
event replay no duplicate effects PASS → CERTIFIED
```

---

## W8 — Certification & Production

**Owner**: All layers (integration)

**Definition of Ready**:
```text
□ All waves W0–W7 certified
□ Certification lifecycle: DESIGNED → BUILT → CONTRACT_VALIDATED → TESTED → FAILURE_TESTED → CERTIFIED → PRODUCTION_ENABLED
□ All architecture acceptance criteria met
□ Definition of Done complete
```

**Deliverables**:
1. Performance testing — worker concurrency, tenant fairness, backpressure
2. Security audit — prompt injection, cross-tenant, privilege escalation, credential leakage
3. Load testing — 10K worker capacity, P95 latency
4. Documentation — API docs, architecture docs, runbooks
5. Certification evidence package

**Files to create**:
- `tests/load/` (load test suite)
- `tests/security/` (prompt injection, cross-tenant, privilege escalation)
- `docs/api.md`
- `docs/architecture.md`
- `docs/runbooks/`
- `docs/certification/` (evidence package)

**Wave Gate**:
```
performance contract PASS → security audit PASS → load test PASS →
documentation complete PASS → certification evidence complete → CERTIFIED → PRODUCTION_ENABLED
```

---

## Wave Summary

| Wave | Focus | Owner | Key Gate |
|------|-------|-------|----------|
| W0 | Foundation & Architecture Enforcement | Identity/Shared | Architecture invariants I-001–I-028 |
| W1 | Data Layer & Tenancy | Database | Fresh install, RLS, migration reproducibility |
| W2 | Contracts & State Machines | Contracts | Property-based, illegal transitions, immutability |
| W3 | Kernel S0–S15 | Control Plane | Full pipeline, no alternate paths, trace continuity |
| W4 | Reliability Kernel | Reliability | Crash recovery, UNKNOWN→probe, budget atomicity |
| W5 | Provider & Protocol Adapters | Adapters | Contract suite, binding integrity, no re-resolution |
| W6 | Verification & Observability | Verification | Ledger completeness, trace reconstruction, root-cause |
| W7 | Event Gateway & Extensions | Event/Processor | HMAC auth, correlation, sandbox, replay safety |
| W8 | Certification & Production | All | Performance, security, load, certification evidence |

---

## Anti-Patterns

These patterns are explicitly forbidden.

| Anti-Pattern | Why It's Wrong | Correct Approach |
|--------------|---------------|------------------|
| Duplicate contract definitions | Two sources of truth drift | Import from canonical location |
| Adapter makes authorization decisions | Authorization is S8, not adapter | Adapter returns KernelResult only |
| Retry logic in adapter AND kernel | Retry storms | Single reliability layer decides |
| Worker depends on specific runtime | Cannot swap models/runtimes | Worker → Runtime Contract → Adapter |
| LLM output modifies ExecutionContext | Frozen at S0 | ExecutionContext is immutable |
| Re-resolution after S5 | Breaks FrozenBindingIdentity | S6–S12 consume frozen binding |
| Timeout → FAILED (skipping UNKNOWN) | Loses reconciliation path | Timeout → UNKNOWN → probe |
| Event payload provides tenant_id | Breaks tenant isolation | Gateway auth provides tenant_id |
| Top-level modules (no src/) | Import path ambiguity | Enforce src/ layout |
| Monolithic files (>500 LOC) | Hard to test, review, maintain | One responsibility per file |

### Code Review Checklist

Every PR must answer these questions:

| # | Question | Why |
|---|----------|-----|
| 1 | Does this logic already exist somewhere? | Anti-duplication |
| 2 | Is this component the canonical owner? | Single source of truth |
| 3 | Does this create an alternate execution path? | Canonical pipeline integrity |
| 4 | Does it preserve the canonical contract? | Contract stability |
| 5 | Can this produce an illegal state? | State machine integrity |
| 6 | What happens on timeout/crash/duplicate? | Failure safety |
| 7 | Can tenant or privilege boundaries be bypassed? | Security |
| 8 | Can we reconstruct this execution later? | Observability |
| 9 | What happens when this component changes? | Versioning |
| 10 | What evidence proves this component is safe? | Certification |

---

*End of Execution Plan.*

---

## Appendices

### Appendix A: Implementation Checklist

**Pre-Implementation**:
- [ ] All W1 decisions documented and agreed
- [ ] PostgreSQL running and accessible
- [ ] CI pipeline green on main branch
- [ ] `pyproject.toml` committed with all dependencies
- [ ] Alembic configured and first migration created

**Wave 1: Data Layer & Tenancy**:
- [ ] All tables created via migrations
- [ ] RLS enabled on all tenant-scoped tables
- [ ] Seed data loads successfully
- [ ] Budget atomicity tests pass
- [ ] Connection pool tested under load

**Wave 2: Contracts & State Machines**:
- [ ] All frozen dataclasses implemented
- [ ] Immutability enforced
- [ ] Property-based tests pass
- [ ] Illegal transitions rejected
- [ ] Serialization/version compatibility verified

**Wave 3: Kernel S0–S15**:
- [ ] All 15 stages implemented
- [ ] S8 safety gate blocks D/IRREVERSIBLE without confirmation
- [ ] Full S0→S15 integration passes
- [ ] No alternate execution paths

**Wave 4: Reliability Kernel**:
- [ ] Circuit breaker opens/closes correctly
- [ ] Timeout produces UNKNOWN, not FAILED
- [ ] Budget locked on timeout, resolved by probe
- [ ] Crash/restart recovery works
- [ ] Dead letter retry scheduler works

**Wave 5-6: Adapters + Verification**:
- [ ] All adapters wrap providers, never raise
- [ ] Contract suite passes for all adapters
- [ ] Verification catches simulated failures

**Wave 7: Event Gateway & Extensions**:
- [ ] HMAC authentication enforced
- [ ] Event correlation/aggregation works
- [ ] Processor sandbox enforces limits

**Wave 8: Certification & Production**:
- [ ] Performance tests pass
- [ ] Security audit complete
- [ ] Documentation complete
- [ ] Certification evidence recorded
- [ ] Production readiness review signed off

### Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Worker** | Isolated execution context with its own bindings, memory, and state |
| **Adapter** | Provider-specific wrapper that normalizes API calls to KernelResult |
| **Binding** | Mapping from capability to specific provider operation |
| **Budget** | Per-tenant cost limit tracked atomically via reservations |
| **RLS** | Row-Level Security — database-enforced tenant isolation |
| **Kernel Op** | Canonical operation identifier (e.g., `ghl.contact_create`) |
| **Checkpoint** | Durable snapshot of execution state for recovery |
| **Dead Letter** | Failed execution queued for manual review |
| **Envelope** | Universal response format with trace, timing, usage, decision |
| **FrozenBindingIdentity** | Immutable resolution result, produced at S5, never re-resolved |
| **ExecutionContext** | Immutable request context, frozen at S0, never from LLM |
| **ExecutionManifest** | Immutable execution configuration, frozen at S11 |
| **IntentSpecification** | Immutable user objective, frozen at S3 |
| **LedgerEvent** | Append-only execution event, forensic truth |
| **UNKNOWN** | Execution state requiring reconciliation — never silently FAILED |
| **AcceptanceCriteria** | Formal definition of success beyond "API returned 200" |
| **Runtime Contract** | Interface decoupling Workers from specific AI providers |
| **Progressive Verification** | Layered verification from schema to human confirmation |
| **AutonomyBounds** | Hard limits for autonomous execution loops |
| **CorrelationRule** | Event aggregation rule for the Event Gateway |
| **Processor** | Sandboxed computation unit (Python, SQL, WASM, Visual) |
| **EventEnvelope** | Immutable wrapper for externally-triggered events |
| **WorkerSubscription** | Worker's durable declaration of event interest |
| **ConfigurationVersion** | All versions frozen at execution start |
| **VerificationResult** | Result of a single verification layer in S13 |
| **ReplayContext** | Context for replaying an execution safely |
| **RuntimeRoutingDecision** | Determines which runtime and model to use |

### Appendix C: Architecture Invariants Reference

| ID | Invariant | Enforced At |
|----|-----------|-------------|
| I-001 | TENANT ISOLATION | PostgreSQL RLS — never bypassable at application level |
| I-002 | FROZEN BINDING IDENTITY | S5 output immutable — S6–S12 consume, never re-resolve |
| I-003 | FROZEN EXECUTION CONTEXT | S0 output immutable — never modified, never from LLM |
| I-004 | NO SILENT SUCCESS | Adapters return explicit status — never "assume success" |
| I-005 | PROBE BEFORE FAILURE | UNKNOWN requires probe attempt before terminal failure |
| I-006 | ATOMIC BUDGET | reserve/commit/release/lock are atomic — no double-spend |
| I-007 | IDEMPOTENCY | Same request_id → same effect, regardless of duplicates |
| I-008 | DETERMINISTIC AUTHORIZATION | Authorization computed from policy, never from LLM |
| I-009 | LEASE FENCING | State transitions require current lease token — zombie-proof |
| I-010 | CHECKPOINT RECOVERY | Every execution can resume from last checkpoint |
| I-011 | DEAD LETTER IMMUTABILITY | Dead letters are append-only — never modified |
| I-012 | CONTRACT PRESERVATION | All adapters implement BaseAdapter — no custom interfaces |
| I-013 | MUTATION SAFETY | IRREVERSIBLE/D mutations require explicit confirmation |
| I-014 | TRACE COMPLETENESS | Every execution has full trace_id chain |
| I-015 | TENANT BUDGET FAIRNESS | Budget reservations are per-tenant — no cross-subsidization |
| I-016 | NO CUSTOM PATHS | Every execution traverses canonical S0→S15 pipeline |
| I-017 | CONFIGURATION FREEZE | ExecutionManifest captures all versions at S11 |
| I-018 | LLM OUTPUT UNTRUSTED | LLM output is proposal only — kernel authorizes action |
| I-019 | SERVER AUTHORITATIVE TIME | No worker-local clock in distributed decisions |
| I-020 | EXECUTION LEDGER APPEND ONLY | Ledger events never updated, deleted, or soft-deleted |
| I-021 | AT-LEAST-ONCE SEMANTICS | Duplicate execution safe; missing execution is not |
| I-022 | EVENT GATEWAY TENANT ISOLATION | tenant_id from gateway auth, NEVER from event payload |
| I-023 | EVENT DRIVEN = SAME PIPELINE | Event-driven follows identical S0→S15 — no bypass |
| I-024 | KERNEL STABILITY BOUNDARY | No kernel change required for new adapter/protocol/runtime |
| I-025 | EXTERNAL EVENT SANITIZATION | Event payloads pass DataSanitizer before any processing |
| I-026 | FROZEN INTENT SPECIFICATION | IntentSpecification frozen at S3 — not modified by LLM |
| I-027 | BOUNDED AUTONOMY | Every loop has explicit bounds (iterations, budget, duration, risk) |
| I-028 | ARCHITECTURE COMPLIANCE | Every invariant has a named test in CI — build fails if violated |

### Appendix D: Certification Lifecycle

```
DESIGNED
  ↓ Requirements captured, contracts drafted
BUILT
  ↓ Code written, follows wave discipline
CONTRACT_VALIDATED
  ↓ Contract tests pass, no drift from canonical definitions
TESTED
  ↓ Unit, integration, property-based, boundary tests pass
FAILURE_TESTED
  ↓ Chaos, timeout, crash, duplicate, concurrency tests pass
CERTIFIED
  ↓ All gates pass, evidence recorded, version frozen
PRODUCTION_ENABLED
  ↓ Deployed with monitoring
  ↓
SUSPENDED / REVOKED (if issues found)
  ↓
RETIRED (when superseded)
```

**Rule**: No component reaches PRODUCTION_ENABLED without completing every stage. Certification evidence is stored in `docs/certification/`.

### Appendix E: References

| Document | Purpose |
|----------|---------|
| [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) | Source of truth for all architectural decisions |
| [DATA_CONTRACTS.md](DATA_CONTRACTS.md) | Canonical contract for all data types |
| [STATE_TRANSITIONS.md](STATE_TRANSITIONS.md) | Authoritative state machines |
| [COMPONENTS_BLUEPRINT.md](COMPONENTS_BLUEPRINT.md) | Directory structure, file ownership, module boundaries |
| [PIPELINE_STAGES.md](PIPELINE_STAGES.md) | S0–S15 stage definitions |
| [RESOLVE_LAYER.md](RESOLVE_LAYER.md) | Intent → capability → kernel_op → binding → provider → adapter |
| [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) | Worker lifecycle, S13 verification, S12 admission |
| [PROVIDER_ADAPTERS.md](PROVIDER_ADAPTERS.md) | Adapter interface, error classification |
| [SECURITY.md](SECURITY.md) | Auth, authorization, injection defense, secret handling |
| [MUTATION_SAFETY.md](MUTATION_SAFETY.md) | Read/write/delete/irreversible classification |
| [RELIABILITY.md](RELIABILITY.md) | 5-layer reliability guard, retries, circuit breakers, budgets |
| [VALIDATION.md](VALIDATION.md) | Test specifications for every contract, stage, and boundary |
| [BUILD_READINESS_MATRIX.md](BUILD_READINESS_MATRIX.md) | Closure checklist |
| [VOCABULARY_INDEX.md](VOCABULARY_INDEX.md) | Canonical term definitions |
| [IDENTITY_AND_TENANCY.md](IDENTITY_AND_TENANCY.md) | Identity vocabulary, tenant/workspace isolation |
| [DATABASE.md](DATABASE.md) | Complete PostgreSQL schema, migrations, RLS policies |
| [REFAUDIT.md](REFAUDIT.md) | State machine cross-reference audit history |