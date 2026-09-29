# SUPERSESSION-AWARE BLOCKER REGISTER
# SuprAgents — Enterprise-Grade Cross-Document Consistency Audit

**Date**: 2026-09-26
**Status**: RECONCILIATION_INCOMPLETE — CERTIFICATION_BLOCKED
**Basis**: All 18 documents in dependency order + CROSS_DOCUMENT_RECONCILIATION.md + REFAUDIT.md + EXECUTION_PLAN.md

---

## CLOSURE EQUATION

```text
CLOSED_WITH_EVIDENCE
  = Authoritative Decision (recorded)
  + Owning Document Updated (change committed)
  + Affected Documents Propagated (contradictions removed, references added)
  + Named Validation Test (test exists in VALIDATION.md)
  + CI Enforcement (test runs in CI gate)
  + Evidence (test passes, commit hash)
```

A finding is **not** closed merely because a decision was reached or a document was edited. All six criteria must be satisfied.

---

## STATUS TAXONOMY

```
OPEN                        — Contradiction/gap exists; no decision recorded
DECISION_REQUIRED           — Human architectural/security decision required
DECIDED                     — ADR/authoritative decision exists
PROPAGATION_REQUIRED        — Decision not yet propagated to affected documents
IMPLEMENTATION_REQUIRED     — Contract exists; implementation incomplete
TEST_REQUIRED               — Implementation exists; required evidence missing
CI_ENFORCEMENT_REQUIRED     — Test exists but merge gate absent
VERIFIED                    — Required evidence exists and passes
SUPERSEDED                  — Historical finding replaced by authoritative finding
CLOSED_WITH_EVIDENCE        — All six closure-equation criteria met
BLOCKED                     — Cannot progress because prerequisite is missing
CERTIFICATION_BLOCKED       — Overall register status
```

---

## SECTION 1: MC FINDING COUNTS BY WORKSTREAM

Canonical count table derived from EXECUTION_PLAN.md. All executive-summary numbers derive from this table.

| Workstream | Total MC | OPEN | CLOSED | DECIDED | Superseded |
|-----------|---------:|-----:|-------:|--------:|-----------:|
| W0 | 10 | 0 | 10 | 0 | 0 |
| W1 | 7 | 0 | 7 | 0 | 0 |
| W2 | 7 | 7 | 0 | 0 | 0 |
| W3 | 7 | 7 | 0 | 0 | 0 |
| W4 | 7 | 0 | 7 | 0 | 0 |
| W5 | 20 | 20 | 0 | 0 | 0 |
| W6 | 14 | 14 | 0 | 0 | 0 |
| **Total** | **72** | **48** | **24** | **0** | **0** |

**OPEN implementation items**: 48 (not 39 — the earlier count excluded W2 and W3 items).
**Documentation/contract items**: 33 (from CROSS_DOCUMENT_RECONCILIATION, REFAUDIT, and new P0 findings).
**Total OPEN findings**: 81 (48 implementation + 33 documentation/contract).

These three measures are independent:
- **Finding count**: Unique unresolved architectural/contract/runtime problems after supersession
- **Implementation-task count**: Concrete engineering actions required to close findings
- **Test count**: Validation tests required to produce evidence

One finding can produce multiple implementation tasks. One implementation task can require multiple tests. These counts must not be substituted for one another.

---

## SECTION 2: HISTORICAL FINDINGS — SUPERSESSION MATRIX

Every historical P0/P1/ADR finding with full lineage.

### CROSS_DOCUMENT_RECONCILIATION Findings

| Historical ID | Original Finding | Original Source | Current Authoritative Source | Current Statement | Status | Superseded By | Supersedes | Conflict Residue | Owning Document | Affected Documents | Required Propagation | Validation Test | CI Gate | Evidence |
|---------------|-----------------|-----------------|------------------------------|-------------------|--------|---------------|------------|------------------|-----------------|--------------------|---------------------|-----------------|---------|----------|
| P0-A | ExecutionContext, ExecutionManifest, FrozenBindingIdentity, Plan are competing concepts | CROSS_DOCUMENT_RECONCILIATION | DATA_CONTRACTS §2/§6/§27/§4 + IDENTITY_AND_TENANCY §7 | Artifacts documented. Ownership table not yet written. ExecutionManifest not propagated. Multi-step data flow undefined. | PARTIALLY_SUPERSEDED | P0-B, P1-A | — | Ownership table; ExecutionManifest propagation; multi-step data flow | FINAL_ARCHITECTURE | DATA_CONTRACTS, PIPELINE, IDENTITY, RELIABILITY | Ownership table in FINAL_ARCHITECTURE §13 | — | — | Partial |
| P0-B | S4 produces dependency_graph but S9 never defines step-2 consuming step-1's output | CROSS_DOCUMENT_RECONCILIATION | PIPELINE_STAGES.md S4/S9 + DATA_CONTRACTS | No StepOutputReference, StepParameterBinding, or data-flow validation exists | OPEN | — | P0-A | Multi-step data flow undefined; affects PlanStep, step input contracts, persistence, checkpointing, retries, provenance, serialization, worker handoff, partial execution, recovery, validation, idempotency | PIPELINE_STAGES.md | DATA_CONTRACTS, RESOLVE_LAYER | Complete StepOutputReference/StepParameterBinding contract + data-flow validation | test_step_output_binding(), test_dependency_graph_resolution() | Required | None |
| P0-C | S10 "wait for user" but no durable PendingConfirmation; multiple pending confirmations; worker disappears | CROSS_DOCUMENT_RECONCILIATION | PIPELINE_STAGES.md S10 + DATABASE.md | Confirmations table exists; re-entry protocol partially defined; MC-066 (S10/CLARIFY re-entry) OPEN; MC-007 (S8→S11 propagation) OPEN | PARTIALLY_SUPERSEDED | MC-066, MC-007 | — | Multiple pending confirmations; re-entry routing for CLARIFY; confirmation propagation S8→S10→S11 | PIPELINE_STAGES.md | DATABASE.md, DATA_CONTRACTS | Complete re-entry protocol with routing + confirmation propagation | test_confirmation_persistence_reentry(), test_multiple_pending_confirmations() | Required | None |
| P0-D | DATABASE.md contains SQLite production-path backup/restore | CROSS_DOCUMENT_RECONCILIATION | DATABASE.md | PostgreSQL is canonical; SQLite confined to tests/; production-path backup at line 910+ still present | PARTIALLY_SUPERSEDED | — | — | SQLite backup/restore in production-path section | DATABASE.md | — | Remove SQLite production-path artifacts | — | — | Partial |
| P1-A | ExecutionManifest, outbox/inbox, event ordering, configuration versioning not propagated | CROSS_DOCUMENT_RECONCILIATION | DATA_CONTRACTS §27-§30 | ExecutionManifest referenced only in PIPELINE_STAGES S11 and EXECUTION_PLAN; outbox/inbox/event ordering/config versioning unreferenced outside DATA_CONTRACTS | OPEN | — | P0-A | Contract isolation: four contracts exist in DATA_CONTRACTS but are invisible to consuming documents | DATA_CONTRACTS | FINAL_ARCHITECTURE, RELIABILITY, IDENTITY_AND_TENANCY, SECURITY, PIPELINE_STAGES | Cross-references in each affected document | test_execution_manifest_propagation() | Required | None |
| P1-B | Circuit breaker process-local; no fleet coordination | CROSS_DOCUMENT_RECONCILIATION | RELIABILITY.md | In-memory CircuitBreaker; half-open stuck forever (MC-017) | OPEN | — | — | Fleet-safety gap | RELIABILITY.md | DATABASE.md | Fleet persistence + half-open recovery contract | test_circuit_breaker_persistence(), test_circuit_breaker_fleet_consistency() | Required | None |
| P1-C | Scheduler needs bounded queue + admission policy + fairness policy | CROSS_DOCUMENT_RECONCILIATION | RELIABILITY.md + WORKER_LIFECYCLE | Bulkhead defined (semaphore); no scheduler backpressure or fairness policy | OPEN | — | — | Backpressure/fairness gap | RELIABILITY.md | WORKER_LIFECYCLE_VERIFICATION_ADMISSION | Scheduler contract | test_scheduler_backpressure(), test_tenant_fairness() | Required | None |
| P1-D | S5 computes from TaskProfile produced by S6 (temporal impossibility) | CROSS_DOCUMENT_RECONCILIATION | PIPELINE_STAGES.md | Explicitly marked FIXED at line 397 | CLOSED_WITH_EVIDENCE | — | — | None | PIPELINE_STAGES.md | — | None | test_s5_risk_independent() | Required | PIPELINE_STAGES.md line 397 |
| P1-E | Effective authorization intersection formula undefined | CROSS_DOCUMENT_RECONCILIATION + EXECUTION_PLAN MC-060 | IDENTITY_AND_TENANCY.md §8.3 | 8 authorization checks defined; no intersection formula; no type/semantics for operands | OPEN | — | — | authorization algebra: how user_scope ∩ worker_scope ∩ tenant_policy ∩ capability_grant ∩ execution_mode is computed and typed | IDENTITY_AND_TENANCY.md | SECURITY.md, DATA_CONTRACTS | Complete authorization algebra with operand types | test_authorization_algebra() | Required | None |
| P1-F | Business vs Technical capability boundary | CROSS_DOCUMENT_RECONCILIATION | RESOLVE_LAYER.md | CapabilitySpine defined; no Business/Technical split | SUPERSEDED_BY: ADR-13 | ADR-13 | — | Two-layer capability model not contracted | RESOLVE_LAYER.md | VOCABULARY_INDEX | Business/Technical boundary definition | — | — | None |
| P1-G | Kill-switch hierarchy semantics for running executions | CROSS_DOCUMENT_RECONCILIATION + EXECUTION_PLAN MC-059 | IDENTITY_AND_TENANCY.md | effective_authorization includes kill_switch; no hierarchy or in-flight semantics | OPEN | — | — | Kill-switch hierarchy and in-flight behavior undefined | SECURITY.md | IDENTITY_AND_TENANCY, MUTATION_SAFETY | Kill-switch hierarchy contract | test_kill_switch_hierarchy() | Required | None |
| P1-H | Database cascading rules for audit retention | CROSS_DOCUMENT_RECONCILIATION + EXECUTION_PLAN MC-057 | DATABASE.md | Cascading behavior for audit_log → execution deletion not explicitly defined | OPEN | — | — | execution_runs → execution_steps cascading conflict with audit retention | DATABASE.md | — | Cascading rules in §13 | test_cascade_rules() | Required | None |

### EXECUTION_PLAN Findings

| ID | Workstream | Issue | Owner Doc | Status |
|----|-----------|-------|-----------|--------|
| MC-005 | W3 | RECONCILING lifecycle undefined | DATA_CONTRACTS | OPEN |
| MC-006 | W2 | Full schema pass | DATABASE.md | OPEN |
| MC-007 | W6 | Confirmation moved S8→S11 without propagation | PIPELINE_STAGES.md | OPEN |
| MC-008 | W5 | SafeAdapterWrapper maps leaked exceptions to error; timeout string-match retries writes | PROVIDER_ADAPTERS.md | OPEN |
| MC-009 | W5 | Connect-phase failures become UNKNOWN instead of NOT_EXECUTED | PIPELINE_STAGES.md | OPEN |
| MC-010 | W5 | Lease acquisition not atomic | RELIABILITY.md | OPEN |
| MC-011 | W5 | State transition lacks fencing | DATA_CONTRACTS.md | OPEN |
| MC-012 | W3 | FrozenBindingIdentity field list unified | DATA_CONTRACTS.md | OPEN |
| MC-013 | W5 | ENGINE_MAP keys don't match providers | RESOLVE_LAYER.md | OPEN |
| MC-015 | W2 | RLS policy gaps | DATABASE.md | OPEN |
| MC-016 | W5 | ConcurrencyAdmissionController syntax error | RELIABILITY.md | OPEN |
| MC-017 | W5 | Half-open breaker stuck forever | RELIABILITY.md | OPEN |
| MC-018 | W5 | WriteConflictDetector reads tenant_id from LLM-derived params | SECURITY.md | OPEN |
| MC-019 | W5 | ScopedQuery returns unfiltered when user has no scopes | SECURITY.md | OPEN |
| MC-021 | W2 | 32-bit step_id used as global PK | DATABASE.md | OPEN |
| MC-022 | W2 | REAL timestamps throughout | DATABASE.md | OPEN |
| MC-024 | W2 | execution_steps has no reservation_id FK | DATABASE.md | OPEN |
| MC-026 | W2 | Budget reservation atomic reserve/commit not defined in DB | DATABASE.md | OPEN |
| MC-027 | W3 | DL scheduler doesn't block non-idempotent W mutations | MUTATION_SAFETY.md | OPEN |
| MC-037 | W3 | TIMEOUT/UNKNOWN/RECONCILING state definitions unified | DATA_CONTRACTS.md | OPEN |
| MC-038 | W5 | "Never raises" — no CI check that every adapter is wrapped | PROVIDER_ADAPTERS.md | OPEN |
| MC-039 | W5 | Provider health in S5 tiebreak makes resolution time-variant | RESOLVE_LAYER.md | OPEN |
| MC-040 | W5 | Pagination cursor not bound to query/connection | PROVIDER_ADAPTERS.md | OPEN |
| MC-041 | W5 | Generated registry artifacts lack immutable build manifest | COMPONENTS_BLUEPRINT.md | OPEN |
| MC-042 | W3 | Correlation IDs canonical | DATA_CONTRACTS.md | OPEN |
| MC-043 | W5 | Tenant/workspace identity not revalidated at execution/recovery boundary | IDENTITY_AND_TENANCY.md | OPEN |
| MC-045 | W2 | Missing tables: plans, workers, memberships, policies, kill_switches, feature_flags | DATABASE.md | OPEN |
| MC-047 | W5 | No multi-step decomposition design | PIPELINE_STAGES.md | OPEN |
| MC-048 | W5 | No per-kernel probe design | PROVIDER_ADAPTERS.md | OPEN |
| MC-049 | W5 | Rollback unsafe/won't run | MUTATION_SAFETY.md | OPEN |
| MC-052 | W5 | Timeout ordering invariant only in code comment | DATA_CONTRACTS.md | OPEN |
| MC-053 | W2 | Billing absent end-to-end | DATA_CONTRACTS.md | OPEN |
| MC-054 | W3 | Guard return status fix | PIPELINE_STAGES.md | OPEN |
| MC-057 | W3 | Checkpoint has two storage models | DATABASE.md | OPEN |
| MC-058 | W2 | Credentials break tenancy | SECURITY.md | OPEN |
| MC-059 | W3 | Two different "8 SafetyGate checks" | MUTATION_SAFETY.md | OPEN |
| MC-060 | W3 | MutationSafetyGate won't run (swapped args, undefined vars) | MUTATION_SAFETY.md | OPEN |
| MC-061 | W3 | Confirmation trigger has four definitions; max retries three; routing taxonomy three | DATA_CONTRACTS.md | OPEN |
| MC-062 | W5 | Bulkhead semaphore held across backoff sleeps | RELIABILITY.md | OPEN |
| MC-066 | W5 | S10/CLARIFY re-entry undefined | PIPELINE_STAGES.md | OPEN |

---

## SECTION 3: P0 FINDINGS — EXECUTION SAFETY / ARCHITECTURAL CONTRADICTION

### P0-CRASH — Recovery Binding Semantics Violates Frozen-Binding Invariant

| | |
|---|---|
| **Severity** | P0 |
| **Documents in conflict** | DATABASE.md §10 (says re-resolve) vs RESOLVE_LAYER.md §6 + PIPELINE_STAGES.md S12 (say never re-resolve) |
| **Current DATABASE.md §10** | `5. Re-resolve bindings (bindings may have changed)` |
| **Required** | Recovery MUST use frozen FrozenBindingIdentity from checkpoint. If binding is invalid at recovery → FAILED, do NOT re-resolve. |
| **Recovery Binding Validity States** | ```
IDENTITY_MISMATCH       → FAILED (binding_id maps to different capability)
BINDING_RETIRED         → FAILED (capability retired after checkpoint)
BINDING_DISABLED        → FAILED (binding deactivated)
CREDENTIAL_INVALID      → FAILED (provider auth changed)
ADAPTER_UNAVAILABLE     → FAILED (adapter module missing)
PROVIDER_UNAVAILABLE    → UNKNOWN (transient; probe at S13)
POLICY_INVALID          → FAILED (security policy changed)
SECURITY_CONTEXT_INVALID → FAILED (tenant/workspace deactivated)
``` |
| **Frozen identity ≠ frozen runtime availability** | The frozen binding's identity (binding_id, provider, adapter_class, kernel_op_id) is immutable. Runtime availability (provider reachable, adapter loaded, credential valid) is stateful. Recovery must distinguish these. |
| **FrozenBindingIdentity authority during recovery** | The checkpoint's FrozenBindingIdentity is the authoritative source. ExecutionManifest is a secondary reference. No re-resolution is permitted. |
| **Budget recovery wording** | Do NOT say "re-reserve budget." Say: "Validate or recover the existing reservation associated with this execution using the frozen reservation_id. Create a new reservation only if the authoritative budget contract explicitly permits reservation replacement." |
| **UNKNOWN vs NOT_EXECUTED boundary** | PROVIDER_UNAVAILABLE → UNKNOWN is appropriate only when the external side effect MAY have occurred. If the execution boundary proves the external call was never dispatched, the correct state is NOT_EXECUTED, not UNKNOWN. Recovery state must depend on whether the external side effect could have occurred, not merely whether the provider is currently unavailable. |
| **Status** | OPEN |
| **Affected documents** | DATABASE.md, RESOLVE_LAYER.md, PIPELINE_STAGES.md, RELIABILITY.md, DATA_CONTRACTS.md |
| **Validation tests** | `test_recovery_does_not_reresolve_frozen_binding()`, `test_recovery_binding_validity_states()`, `test_recovery_unknown_vs_not_executed()` |

### P0-B — Execution Data-Flow Contract

| | |
|---|---|
| **Severity** | P0 |
| **Problem** | S4 produces dependency_graph with chain/complex graph support. S9 defines Plan/PlanStep. No mechanism for Step N to consume Step N-1's output. |
| **Impact scope** | PlanStep, step input contracts, persistence, checkpointing, retries, provenance, serialization, worker handoff, partial execution, recovery, validation, idempotency |
| **Required contract** | StepOutputReference (step output reference), StepParameterBinding (step input parameter binding), data-flow validation at S9 |
| **Step output lifecycle** | ```
RUNNING
  ↓
SUCCEEDED
  ↓
output durably persisted
  ↓
output hash/version recorded
  ↓
dependent step may consume
``` |
| **Required definitions** | Step output retention policy, large payload handling, sensitive output handling, retry semantics, output versioning, partial/fan-out execution, skipped dependencies, failed dependency behavior, conditional branches |
| **Current** | DATA_CONTRACTS.md: No StepOutputReference or StepParameterBinding type. PIPELINE_STAGES.md S4: GraphType defined. S9: Plan defined. No connection between graph topology and data flow. |
| **Status** | OPEN |
| **Affected documents** | PIPELINE_STAGES.md, DATA_CONTRACTS.md |
| **Validation tests** | `test_step_output_binding()`, `test_dependency_graph_resolution()` |

### P0-C-PART — Confirmation Re-Entry Protocol Incomplete

| | |
|---|---|
| **Severity** | P0 |
| **Problem** | Confirmation persistence exists. Re-entry protocol partially defined. MC-066 (S10/CLARIFY re-entry) OPEN. MC-007 (S8→S11 propagation) OPEN. |
| **Required identity fields** | confirmation_id, execution_id, plan_hash, principal/user, tenant_id, workspace_id, requested_at, expires_at, decision, decision_at, status, consumed_at |
| **Required semantics** | Replay: same confirmation consumed twice → rejected. Concurrent: two workers processing same confirmation → one wins, other rejected. Plan mutation: confirmation arrives but plan hash no longer matches → rejected. CLARIFY re-entry: defines whether this is same execution, new execution, same plan, regenerated plan, new plan hash, new confirmation. |
| **Remaining gaps** | Multiple pending confirmations per plan_hash. Re-entry routing for CLARIFY path. Confirmation S8→S11 not fully propagated. |
| **Status** | PARTIALLY_SUPERSEDED |
| **Affected documents** | PIPELINE_STAGES.md, DATA_CONTRACTS.md |
| **Validation tests** | `test_confirmation_persistence_reentry()`, `test_multiple_pending_confirmations()`, `test_confirmation_replay_rejected()`, `test_confirmation_concurrency_safe()` |

### P0-D — EXECUTION_PLAN.md W2-W6 Implementation Backlog

| | |
|---|---|
| **Severity** | P0 |
| **Problem** | 48 OPEN items across W2-W6. These are implementation-correctness defects, not documentation gaps. Cannot be resolved by document edits. |
| **W2 items (7)** | MC-006, MC-045, MC-015, MC-021, MC-022, MC-058, MC-053 |
| **W3 items (7)** | MC-005, MC-037, MC-012, MC-059, MC-061, MC-042, MC-054 |
| **W5 items (20)** | MC-008 through MC-019, MC-038 through MC-043, MC-047 through MC-049, MC-052 through MC-053, MC-062, MC-066 |
| **W6 items (14)** | MC-010 through MC-011, MC-016 through MC-019, MC-027, MC-038 through MC-041, MC-043, MC-060 through MC-062 |
| **Count stability** | Count derived from canonical table in Section 1. Not manually asserted. |
| **Status** | OPEN — all 48 items remain OPEN |
| **Note** | These items block implementation gate but are addressed during W2-W6 implementation, not by documentation repair. |

---

## SECTION 4: SECURITY/TENANT-ISOLATION GAPS

### ADR-2 — Cross-Tenant Audit Reads Decision Required

| | |
|---|---|
| **Finding** | DATABASE.md audit_reader policy uses `USING (true)` — allows cross-tenant reads |
| **Current contract** | `USING (true)` on audit_log for audit_reader role (DATABASE.md line 1268) |
| **Decision required** | Cross-tenant (current) or tenant-scoped (proposed)? |
| **If tenant-scoped** | Must define tenant context mechanism for audit_reader role (it does not use application_role session variable). Define who may assume audit_reader, why, how tenant context is established, whether access is logged. |
| **If cross-tenant** | Document explicitly that audit_reader is intentionally cross-tenant for compliance. |
| **Tests** | `test_audit_reader_access_policy()` — verifies audit_reader access matches declared scope regardless of decision |
| **Status** | DECISION_REQUIRED |
| **Affected** | DATABASE.md, SECURITY.md |

### SEC-1 — ScopedQuery Returns Unfiltered When User Has No Scopes

| | |
|---|---|
| **Severity** | P0 |
| **Current** | EXECUTION_PLAN MC-019 OPEN |
| **Problem** | When user has no scopes, query returns unfiltered results — authorization bypass |
| **Status** | OPEN |
| **Affected** | SECURITY.md |
| **Test** | `test_scoped_query_enforces_empty_scope()` |

### SEC-2 — WriteConflictDetector Reads tenant_id from LLM-Derived Parameters

| | |
|---|---|
| **Severity** | P0 |
| **Current** | EXECUTION_PLAN MC-018 OPEN |
| **Problem** | tenant_id sourced from LLM output instead of ExecutionContext — authorization bypass |
| **Status** | OPEN |
| **Affected** | SECURITY.md, PIPELINE_STAGES.md |
| **Test** | `test_write_conflict_detector_uses_execution_context()` |

### SEC-3 — Authorization Algebra Not Defined

| | |
|---|---|
| **Severity** | P1 |
| **Problem** | IDENTITY_AND_TENANCY.md §8.3 defines 8 authorization checks but no intersection formula. Operand types and semantics undefined. |
| **Required** | Define authorization algebra with explicit type/semantics for each operand before inserting formula. Authorization is not always simple set intersection — may involve explicit deny, conditional grants, resource scopes, capability restrictions, tenant policy, execution mode, kill switch, delegation constraints. |
| **Status** | OPEN |
| **Affected** | IDENTITY_AND_TENANCY.md, SECURITY.md, DATA_CONTRACTS.md |
| **Test** | `test_authorization_algebra()` |

### SEC-4 — Kill-Switch Hierarchy Semantics for In-Flight Executions

| | |
|---|---|
| **Severity** | P1 |
| **Current** | effective_authorization includes kill_switch value; no hierarchy or in-flight behavior defined |
| **Required** | Hierarchy: Global → Tenant → Workspace → Worker → Execution → Step. In-flight semantics: higher-level switch propagates downward. Must define execution boundary: before external call → terminate; external call already dispatched → cannot safely terminate, transition according to UNKNOWN contract; after verified completion → record result. Must be linked to UNKNOWN and mutation-safety contracts. |
| **Status** | OPEN |
| **Affected** | SECURITY.md, IDENTITY_AND_TENANCY.md, MUTATION_SAFETY.md |
| **Test** | `test_kill_switch_hierarchy()` |

### SEC-5 — Credentials Break Tenancy

| | |
|---|---|
| **Severity** | P1 |
| **Current** | EXECUTION_PLAN MC-058 OPEN. provider_tokens table exists; no per-connection keying; global PAT still referenced |
| **Problem** | Token keying by tenant+connection, not global |
| **Status** | OPEN |
| **Affected** | DATABASE.md, SECURITY.md |
| **Test** | `test_credential_tenancy()` |

### SEC-6 — MutationSafetyGate Non-Functional

| | |
|---|---|
| **Severity** | P1 |
| **Current** | EXECUTION_PLAN MC-060 OPEN |
| **Problem** | Swapped args, undefined variables, dead code |
| **Status** | OPEN |
| **Affected** | MUTATION_SAFETY.md, PIPELINE_STAGES.md, SECURITY.md |
| **Test** | `test_safety_gate_functional()` |

---

## SECTION 5: RESOLUTION/PROVIDER-ROUTING GAPS

### RES-1 — ENGINE_MAP Provider Name Mismatch

| | |
|---|---|
| **Severity** | P0 |
| **Problem** | ENGINE_MAP keys don't match provider table names: `ghl` vs `ghl_public`/`ghl_workflow` |
| **Current** | RESOLVE_LAYER.md ENGINE_MAP uses `ghl` as key; DATABASE.md provider_tokens uses `ghl_public` |
| **Status** | OPEN (MC-013) |
| **Affected** | RESOLVE_LAYER.md, DATABASE.md, COMPONENTS_BLUEPRINT.md |
| **Test** | `test_engine_map_keys_match_providers()` |

### RES-2 — FrozenBindingIdentity Field List: Construct vs Define Mismatch

| | |
|---|---|
| **Severity** | P1 |
| **Problem** | RESOLVE_LAYER.md constructs FrozenBindingIdentity with trace_id, request_id, task_id, account_id, capability/kernel/binding/adapter versions, registry version, authorization state, eligibility information, timestamps, resolver identity — materially larger than DATA_CONTRACTS §6 definition (11 fields). |
| **Forensic ADR-3** | Proposed field list conflicts with canonical definition (errors: selection_rank listed as optional, tenant_id included, resolved_at_stage omitted). |
| **Current status** | ADR-3 is SUPERSEDED_PENDING_PROPAGATION. Canonical definition exists and is consistent in RESOLVE_LAYER.md §2 and DATA_CONTRACTS §6 (IDENTICAL 11-field definitions). But RESOLVE_LAYER.md constructs FrozenBindingIdentity with a materially larger field set. |
| **Required** | Unify field list. Identify authoritative owner per field. Propagate to all affected documents. |
| **Status** | OPEN |
| **Affected** | DATA_CONTRACTS.md, RESOLVE_LAYER.md, PIPELINE_STAGES.md |
| **Test** | `test_frozen_binding_identity_consistency()` |

### RES-3 — Provider Health in S5 Tiebreak Violates Determinism

| | |
|---|---|
| **Severity** | P1 |
| **Problem** | S5 tiebreak includes provider health, so same request can produce different FrozenBindingIdentity |
| **Violates** | Determinism: same inputs must produce same FrozenBindingIdentity |
| **Status** | OPEN (MC-039) |
| **Affected** | RESOLVE_LAYER.md |
| **Test** | `test_s5_deterministic_tiebreak()` |

### RES-4 — Pagination Cursor Not Bound to Query/Connection

| | |
|---|---|
| **Severity** | P1 |
| **Problem** | Pagination cursor not bound to query/connection context |
| **Status** | OPEN (MC-040) |
| **Affected** | PROVIDER_ADAPTERS.md |
| **Test** | `test_cursor_binding()` |

### RES-5 — No Per-Kernel Probe Design

| | |
|---|---|
| **Severity** | P0 |
| **Problem** | S13 verification requires observation methods per kernel_op, but no registry exists |
| **Status** | OPEN (MC-048) |
| **Affected** | PROVIDER_ADAPTERS.md, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md |
| **Test** | `test_per_kernel_observation_methods()` |

---

## SECTION 6: PIPELINE ORDERING/BYPASS GAPS

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| PIPE-CRASH | Recovery re-resolves bindings (P0-CRASH) | P0 | OPEN |
| PIPE-007 | Confirmation S8→S11 not fully propagated (MC-007) | P0 | OPEN |
| PIPE-066 | S10/CLARIFY re-entry undefined (MC-066) | P0 | OPEN |
| PIPE-DATA | Multi-step data flow undefined (P0-B) | P0 | OPEN |
| PIPE-UNKNOWN | UNKNOWN→PROBE→CONFIRMED flow enforced | — | CLOSED_WITH_EVIDENCE |

---

## SECTION 7: DATABASE/MIGRATION GAPS

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| DB-SQLITE | SQLite backup/restore in production-path section (P0-E) | P1 | PARTIALLY_SUPERSEDED |
| DB-RLS | No RLS on confirmations, dead_letters, idempotency, retry_log (MC-015) | P0 | OPEN |
| DB-STEPID | 32-bit step_id as global PK (MC-021) | P0 | OPEN |
| DB-TS | REAL timestamps throughout (MC-022) | P0 | OPEN |
| DB-RESERVE | Budget reservation atomic reserve/commit not in DB (MC-026) | P0 | OPEN |
| DB-FK | execution_steps has no reservation_id FK (MC-024) | P0 | OPEN |
| DB-MISSING | Missing tables: plans, workers, memberships, policies, kill_switches, feature_flags (MC-045) | P0 | OPEN |
| DB-CASCADE | Cascading rules undefined (MC-057) | P1 | OPEN |
| DB-CKPT | Checkpoint has two storage models (MC-057) | P1 | OPEN |
| DB-BILLING | Billing tables missing from execution pipeline (MC-053) | P0 | OPEN |

---

## SECTION 8: RELIABILITY/CONCURRENCY GAPS

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| REL-CB | Circuit breaker process-local; half-open stuck forever (MC-017) | P0 | OPEN |
| REL-LEASE | Lease acquisition not atomic (MC-010) | P0 | OPEN |
| REL-FENCE | State transition lacks fencing (MC-011) | P0 | OPEN |
| REL-TIMEOUT | Timeout ordering invariant only in code comment (MC-052) | P0 | OPEN |
| REL-BULK | Bulkhead semaphore held across backoff (MC-062) | P1 | OPEN |

---

## SECTION 9: STATE TRANSITION AUDIT

| State Machine | Status | Open Items |
|---------------|--------|------------|
| ExecutionRun | DESIGN-CONSISTENT | RECONCILING lifecycle (MC-005, MC-037) |
| Step | DESIGN-CONSISTENT | TIMEOUT/UNKNOWN/RECONCILING definitions (MC-037) |
| BudgetReservation | CLOSED_WITH_EVIDENCE | — |
| WorkerIdentity | CLOSED_WITH_EVIDENCE | — |
| WorkerVersion | CLOSED_WITH_EVIDENCE | — |
| Lease | DESIGN-CONSISTENT | Atomic acquisition (MC-010) |
| Capability | CLOSED_WITH_EVIDENCE | — |
| Binding | CLOSED_WITH_EVIDENCE | — |
| Confirmation | DESIGN-CONSISTENT | Re-entry protocol (MC-066), contract inconsistencies (MC-061) |
| DeadLetter | DESIGN-CONSISTENT | DL scheduler mutation safety (MC-027, MC-060) |
| Reconciliation | DESIGN-CONSISTENT | State machine incomplete |
| CircuitBreaker | DESIGN-CONSISTENT | Persistence + half-open (MC-017, ADR-5) |

**DESIGN-CONSISTENT** means the transition rules are directionally coherent across documents but have not been proven via validation tests. The transition rules are a design decision, not evidence of implementation correctness.

**CLOSED_WITH_EVIDENCE** means the closure-equation criteria are satisfied: design decision recorded, document updated, affected documents propagated, validation test exists, CI gate enforced, evidence collected.

No state machine is CLOSED_WITH_EVIDENCE by both criteria (design AND implementation evidence) except BudgetReservation, WorkerIdentity, WorkerVersion, Capability, and Binding — where REFAUDIT confirmed the repairs and state machine tests exist.

---

## SECTION 10: VALIDATION/TEST GAPS

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| VAL-AAG | Architecture Acceptance Gate test not implemented | P0 | OPEN |
| VAL-FBI | No test for FrozenBindingIdentity field consistency | P0 | OPEN |
| VAL-REC | No test for crash recovery NOT re-resolving bindings | P0 | OPEN |
| VAL-REC-VAL | No test for recovery binding validity state machine | P0 | OPEN |
| VAL-DATA | No test for multi-step output binding | P0 | OPEN |
| VAL-CB | No test for circuit breaker fleet consistency | P1 | OPEN |
| VAL-AUD | No test for audit_reader access policy | P1 | OPEN |
| VAL-DEL | No test for delegation depth persistence | P1 | OPEN |
| VAL-MAN | No test for ExecutionManifest propagation | P1 | OPEN |
| VAL-MC | MC-046: Every F-row and MC-row needs named test | P1 | OPEN |

---

## SECTION 11: ITEMS DESIGN-CLOSED

These items have a design decision recorded. They are NOT evidence-closed (no implementation, no tests, no CI enforcement).

**Design closure ≠ implementation closure ≠ evidence closure.**

1. Budget reservation only at S12
2. Risk/mutation computed once at S5
3. UNKNOWN cannot become SUCCESS without verification
4. Frozen binding cannot change during failover
5. Authorization never delegated to LLM
6. RLS is the tenant isolation enforcement mechanism
7. PostgreSQL is the system of record
8. Three canonical DB roles
9. S2 is the only unconditional LLM call
10. Plan is frozen after S10
11. S5/S6 temporal dependency (P1-D) — FIXED
12. All 8 REFAUDIT bugs repaired
13. W0: All 10 decisions resolved
14. W1: All 7 decisions resolved
15. W4: All 7 fixes applied

---

## SECTION 12: ITEMS CLOSED WITH EVIDENCE

| Item | Evidence | Test |
|------|----------|------|
| S5/S6 temporal dependency (P1-D) | PIPELINE_STAGES.md line 397 | test_s5_risk_independent() |
| REFAUDIT BUG-1 through BUG-8 | STATE_TRANSITIONS.md | test_worker_state_transitions(), test_worker_version_state_transitions() |

---

## SECTION 13: ADR REGISTER

### ADR-1 — Token Storage: Separate Tables vs provider_tokens Subtypes

| | |
|---|---|
| **Finding** | SECURITY.md references `notion_accounts`/`oauth_tokens` tables not present in DATABASE.md |
| **Current state** | DATABASE.md has `provider_tokens` table; SECURITY.md references separate tables |
| **Proposed** | Use `provider_tokens` with `provider_type` discriminator + JSONB `token_metadata` |
| **Status** | DECIDED — implementation required |
| **Affected** | DATABASE.md, SECURITY.md |
| **Test** | test_provider_tokens_provider_type() |

### ADR-2 — Cross-Tenant Audit Reads

| | |
|---|---|
| **Finding** | DATABASE.md audit_reader policy uses `USING (true)` — allows cross-tenant reads |
| **Current contract** | `USING (true)` on audit_log for audit_reader role |
| **Options** | Cross-tenant (current, for compliance audit) or tenant-scoped (proposed, for strict isolation) |
| **Status** | DECISION_REQUIRED |
| **Affected** | DATABASE.md, SECURITY.md |
| **Tests** | test_audit_reader_access_policy() (conditional on decision) |

### ADR-3 — FrozenBindingIdentity Exact Schema

| | |
|---|---|
| **Historical finding** | Forensic ADR-3 proposed field list for FrozenBindingIdentity |
| **Canonical source** | DATA_CONTRACTS §6 + RESOLVE_LAYER.md §2 — IDENTICAL 11-field definition |
| **Canonical fields** | binding_id, capability_id, kernel_op_id, provider, engine_module, adapter_class, effective_risk, effective_mutation, resolved_at_stage, selection_rank |
| **Not in FrozenBindingIdentity** | tenant_id (comes from ExecutionContext) |
| **Forensic ADR-3 errors** | 1) selection_rank listed as optional (it's required in canonical) 2) tenant_id included (NOT in FrozenBindingIdentity) 3) resolved_at_stage omitted |
| **Current status** | SUPERSEDED — canonical definition exists and is consistent in DATA_CONTRACTS §6 and RESOLVE_LAYER.md §2. Residual implementation finding P1-012 tracks the `resolve()` construction payload mismatch. |
| **Remaining gap** | P1-012: `resolve()` construction payload differs from canonical FrozenBindingIdentity type definition |

### ADR-4 — Task/Execution Identity

| | |
|---|---|
| **Finding** | task_id ↔ conversation_id relationship undefined |
| **Current state** | task_id already in ExecutionContext (IDENTITY_AND_TENANCY.md §7) |
| **Gap** | Relationship documentation missing |
| **Status** | OPEN |
| **Affected** | IDENTITY_AND_TENANCY.md, DATA_CONTRACTS.md, PIPELINE_STAGES.md |

### ADR-5 — Circuit Breaker State Persistence

| | |
|---|---|
| **Finding** | CircuitBreaker is process-local; half-open stuck forever (MC-017) |
| **Required scope** | 1) Persistence table 2) Atomic transitions (advisory locks) 3) Half-open recovery behavior 4) Fleet consistency 5) Provider-level scope |
| **Status** | DECIDED — implementation required |
| **Affected** | RELIABILITY.md, DATABASE.md |
| **Tests** | test_circuit_breaker_persistence(), test_circuit_breaker_fleet_consistency(), test_circuit_breaker_half_open_recovery() |

### ADR-6 — Delegation Depth Default and Config

| | |
|---|---|
| **Finding** | SECURITY.md says "configurable maximum (default: 3)" but no persistence location defined |
| **Current state** | Default value present; persistence location absent |
| **Status** | DECIDED — persistence location required |
| **Affected** | SECURITY.md, IDENTITY_AND_TENANCY.md |
| **Test** | test_delegation_depth_persistence() |

### ADR-7 — Recovery Binding Semantics

| | |
|---|---|
| **Finding** | DATABASE.md §10 says "Re-resolve bindings" but RESOLVE_LAYER.md §6 and PIPELINE_STAGES.md S12 say "never re-resolve" |
| **Decision** | Recovery MUST use frozen FrozenBindingIdentity from checkpoint. If binding invalid → FAILED. |
| **Recovery validity states** | IDENTITY_MISMATCH, BINDING_RETIRED, BINDING_DISABLED, CREDENTIAL_INVALID, ADAPTER_UNAVAILABLE, PROVIDER_UNAVAILABLE, POLICY_INVALID, SECURITY_CONTEXT_INVALID |
| **Budget recovery** | Validate or recover existing reservation using frozen reservation_id. Do NOT create new reservation unless budget contract explicitly permits. |
| **UNKNOWN vs NOT_EXECUTED** | PROVIDER_UNAVAILABLE → UNKNOWN only when external side effect MAY have occurred. If execution boundary proves external call never dispatched → NOT_EXECUTED. |
| **Status** | DECIDED — documentation repair required |
| **Affected** | DATABASE.md, RESOLVE_LAYER.md, PIPELINE_STAGES.md, RELIABILITY.md, DATA_CONTRACTS.md |
| **Test** | test_recovery_does_not_reresolve_frozen_binding(), test_recovery_binding_validity_states(), test_recovery_unknown_vs_not_executed() |

### ADR-13 — Authorization Unit: Capability vs Business Action

| | |
|---|---|
| **Finding** | P1-F (Business vs Technical capability boundary) is OPEN. RESOLVE_LAYER defines CapabilitySpine with no business/technical split. FINAL_ARCHITECTURE extension points 5–7 assume a business layer that is not contracted. |
| **Question** | Is the unit that carries authorization grants, certification evidence and audit keying `capability_id`, or a business-action/responsibility layer above it? |
| **Why it blocks** | The answer keys `capability_grants`, certification evidence records and `audit_log`. Changing it after schema is written requires re-keying grants, re-issuing certification evidence and migrating audit. |
| **Status** | DECISION_REQUIRED |
| **Affected** | RESOLVE_LAYER.md, DATABASE.md, IDENTITY_AND_TENANCY.md, VOCABULARY_INDEX.md |
| **Test** | test_authorization_unit_keying() |

### ADR-11 — Checkpoint Storage Model

| | |
|---|---|
| **Finding** | Checkpoint has two storage models (file + table) (MC-057) |
| **Current** | DATABASE.md references both file and table storage |
| **Options** | PostgreSQL-only or PostgreSQL + external payload |
| **Required decision** | Which store is authoritative for checkpoint state? What atomicity/consistency guarantees exist between DB state and external payload? |
| **Critical invariant** | No execution state may reference a checkpoint payload whose integrity, identity, and availability cannot be deterministically established. |
| **Status** | DECISION_REQUIRED |
| **Affected** | DATABASE.md, RELIABILITY.md, DATA_CONTRACTS |

### ADR-14 — Vector Memory Backend and Tenant Isolation

| | |
|---|---|
| **Finding** | FINAL_ARCHITECTURE §36 `MemoryBackend.search(vector, limit)` has no tenant/workspace/worker scope; LanceDB (§20, §29) is embedded and file-based with no RLS, so vector isolation would rest on callers (I-001). Also: no atomic write with ledger/outbox (I-020), no sharing across nodes, no PITR (DATABASE §5) |
| **Draft** | `ADR-14_VECTOR_MEMORY_BACKEND.md` — Part 1: mandatory `MemoryScope` on every async backend call, enforced by the backend, scope from context only; Part 2: recommended Option C — pgvector default (RLS, partition per tenant, HNSW per partition), LanceDB optional per deployment with per-tenant datasets and a recorded I-001 exception |
| **Status** | DECISION_REQUIRED — **blocks all vector code** (register Section 20, MR-1/MR-2) |
| **Target phase** | Post-S15 (memory / LLM layer) |
| **Affected** | FINAL_ARCHITECTURE §20, §21, §29, §36; DATABASE.md; DATA_CONTRACTS.md; SECURITY.md; IDENTITY_AND_TENANCY.md; VALIDATION.md |
| **Tests** | test_memory_calls_require_scope(), test_cross_tenant_vector_search_impossible(), test_scope_from_context_not_llm(), test_memory_write_and_event_atomic() (full list in the ADR §6) |

---

## SECTION 14: W0-W6 READINESS STATUS

### W0 — Architectural Decisions

| | |
|---|---|
| **Status** | CLOSED_WITH_EVIDENCE |
| **Evidence** | EXECUTION_PLAN.md W0, REFAUDIT.md |
| **Gate** | PASS |

### W1 — Implementation Foundations

| | |
|---|---|
| **Status** | DECIDED — propagation verification pending |
| **Evidence** | EXECUTION_PLAN.md W1 |
| **Remaining** | P1-A contract propagation must be verified before W2 |
| **Gate** | CONDITIONAL PASS |

### W2 — Schema & Data Layer

| | |
|---|---|
| **Status** | OPEN — 7 items |
| **Open items** | MC-006, MC-045, MC-015, MC-021, MC-022, MC-058, MC-053 |
| **Required** | Complete schema design, RLS policies, credential tenancy, billing tables |
| **Gate** | FAIL |

### W3 — State Machines

| | |
|---|---|
| **Status** | OPEN — 7 items |
| **Open items** | MC-005, MC-037, MC-012, MC-059, MC-061, MC-042, MC-054 |
| **Required** | Unified TIMEOUT/UNKNOWN/RECONCILING definitions; RECONCILING lifecycle; FrozenBindingIdentity field unification |
| **Gate** | FAIL |

### W4 — Contracts & Data Types

| | |
|---|---|
| **Status** | CLOSED_WITH_EVIDENCE |
| **Evidence** | EXECUTION_PLAN.md W4 |
| **Gate** | PASS |

### W5 — Runtime Correctness

| | |
|---|---|
| **Status** | OPEN — 20 items |
| **Open items** | MC-008 through MC-019, MC-038 through MC-043, MC-047 through MC-049, MC-052 through MC-053, MC-062, MC-066 |
| **Required** | All 20 items addressed during W5 implementation |
| **Gate** | FAIL |

### W6 — Design Holes

| | |
|---|---|
| **Status** | OPEN — 14 items |
| **Open items** | MC-010 through MC-011, MC-016 through MC-019, MC-027, MC-038 through MC-041, MC-043, MC-060 through MC-062 |
| **Required** | All 14 items addressed during W6 implementation |
| **Gate** | FAIL |

---

## SECTION 15: CERTIFICATION GATE STATUS

VALIDATION.md Architecture Acceptance Gate criteria:

**A. STRUCTURAL**
- [ ] no duplicate source of truth — 🔴 FrozenBindingIdentity field lists differ (RESOLVE_LAYER construct vs DATA_CONTRACTS define)
- [ ] no unresolved document contradiction — 🔴 P0-CRASH, ADR-7
- [ ] no undefined contract — 🔴 P0-B, P0-C, P1-A through P1-H
- [ ] no circular dependency — ✅

**B. SECURITY**
- [ ] RLS defined — 🔴 SEC-1 cross-tenant reads, MC-015 RLS gaps
- [ ] identity chain defined — 🟡 Directionally complete (P1-E formula missing)
- [ ] authorization boundaries defined — 🔴 P1-E, P1-G, SEC-1, SEC-2
- [ ] worker delegation defined — 🟡 Partial (ADR-6 persistence missing)

**C. EXECUTION**
- [ ] pipeline stages S0-S15 defined — 🟡 Defined but P0-B, P0-C gaps
- [ ] S12 admission control sequenced before worker selection — ✅
- [ ] S13 independent verification for mutations — ✅
- [ ] state locality scoring defined — ✅
- [ ] UNKNOWN → PROBE → CONFIRMED flow enforced — ✅
- [ ] verification built at S11, executed at S13 — ✅

**D. WORKER LIFECYCLE**
- [ ] WorkerIdentity state machine — ✅
- [ ] WorkerVersion state machine — ✅
- [ ] Exactly one CURRENT version — ✅
- [ ] Fencing token monotonicity — ✅
- [ ] Execution ownership tracking table — ✅

**E. DATA**
- [ ] PostgreSQL 16 canonical — 🟡 SQLite remnants in DATABASE.md §10
- [ ] Alembic canonical — ✅
- [ ] schema manifest reconciled — 🔴 7 missing tables, RLS gaps, identifiers, timestamps
- [ ] indexes/constraints defined — 🟡
- [ ] migration/rollback strategy — 🟡

**F. RELIABILITY**
- [ ] timeout contract — 🟡 Defined but MC-052 OPEN
- [ ] circuit breaker contract — 🔴 Persistence + fleet (ADR-5)
- [ ] bulkhead contract — 🟡 Semaphore defined; MC-062 OPEN
- [ ] budget contract — 🟡 Atomic ops defined; DB integration OPEN
- [ ] recovery contract — 🔴 P0-CRASH: re-resolution contradicts frozen binding
- [ ] dead-letter contract — 🟡 Defined; DL scheduler mutation safety OPEN

**G. SCALE**
- [ ] queue model — 🟡 Admitted but not contracted
- [ ] scheduler model — 🟡 Admitted but backpressure undefined
- [ ] worker capacity — ✅ 10K-worker design defined
- [ ] tenant fairness — 🔴 Not defined
- [ ] backpressure — 🔴 Not defined
- [ ] 10k-worker test strategy — 🟡 Concurrency tests defined

**H. EVIDENCE**
- [ ] E0 design complete for all components — 🔴 W5/W6 have 34 OPEN design items
- [ ] E1 build complete for M0 components — 🔴 Not started
- [ ] E2 test complete for M0 components — 🔴 Not started
- [ ] E3 failure test complete for M0 components — 🔴 Not started

**Verdict**: `ARCHITECTURE_READY = FALSE`

| Result | Count | Criteria |
|--------|------:|----------|
| PASS | 15 | — |
| FAIL | 10 | — |
| PARTIAL | 3 | — |

---

## SECTION 16: FILES TO MODIFY

| File | Phases | Changes |
|------|--------|---------|
| DATABASE.md | 1, 2, 4 | Fix crash recovery (P0-CRASH); audit_reader RLS (ADR-2); cascading rules (P1-H); checkpoint model (ADR-11); remove SQLite remnants |
| PIPELINE_STAGES.md | 1 | Complete re-entry protocol (P0-C); add data-flow contract (P0-B) |
| DATA_CONTRACTS.md | 1 | Add StepOutputReference/StepParameterBinding (P0-B); unify FrozenBindingIdentity field list (P1-012) |
| RESOLVE_LAYER.md | 2 | Reconcile `resolve()` construction with canonical FrozenBindingIdentity field definition; no independent alternative schema permitted |
| RELIABILITY.md | 3, 4 | Add circuit breaker fleet contract (P1-B/ADR-5); checkpoint model (ADR-11); backpressure/fairness (P1-C) |
| SECURITY.md | 2, 4 | Tenant context for audit_reader (ADR-2); kill-switch hierarchy (P1-G); authorization algebra (P1-E); credential tenancy (MC-058); SafetyGate functional (MC-060) |
| IDENTITY_AND_TENANCY.md | 3, 4 | Authorization algebra (P1-E); ExecutionManifest ref (P1-A); identity revalidation (MC-043) |
| FINAL_ARCHITECTURE.md | 3 | ExecutionManifest cross-reference (P1-A); artifact ownership table |
| MUTATION_SAFETY.md | — | DL scheduler mutation safety (MC-027); SafetyGate functional (MC-060); confirmation contract (MC-061) |
| PROVIDER_ADAPTERS.md | — | Per-kernel probe design (MC-048); ENGINE_MAP keys (MC-013); adapter wrapper CI (MC-038); cursor binding (MC-040) |
| COMPONENTS_BLUEPRINT.md | — | Registry manifest (MC-041) |
| VALIDATION.md | 6 | Add missing tests; implement architecture acceptance gate test |
| EXECUTION_PLAN.md | 5 | Acknowledge W2/W3/W5/W6 remain OPEN; track findings from register |
| CROSS_DOCUMENT_RECONCILIATION.md | — | Update with supersession status for all P0/P1 findings |

---

## SECTION 17: APPROVAL REQUIRED

Before proceeding, the following decisions require human approval:

1. **ADR-2**: Should audit_reader be tenant-scoped or cross-tenant? (Changes existing DATABASE.md contract)
2. **ADR-7**: Confirm crash recovery uses frozen binding, does NOT re-resolve
3. **ADR-5**: Confirm circuit breaker persistence approach (PostgreSQL + advisory locks + fleet coordination)
4. **ADR-11**: Checkpoint storage model — PostgreSQL-only or PostgreSQL + external payload?
5. **Scope**: Should the 48 OPEN implementation items be tracked in a separate implementation tracker, or remain in EXECUTION_PLAN.md?

---

## SECTION 18: S12–S15 GATE v9 — RULINGS, PROPAGATION AND RESOLVED ITEMS

**Date**: 2026-09-28. **Source**: S12_S15_EXECUTION_GATE.md v9.
**Rule for all entries below**: the ruling is DECIDED and PROPAGATED (every affected
passage carries a `S12–S15 gate v9 repair (Cn)` marker). Implementation, tests, CI and
evidence are still required (closure equation, Section 1): status
`IMPLEMENTATION_REQUIRED` until the S12–S15 certification report cites the passing tests.

### 18.1 Gate rulings

| ID | Subject | Owning document(s) repaired | Resolves / refines | Tests (gate §16) |
|---|---|---|---|---|
| C1 | In-process dispatch; PostgreSQL is the claim authority | FINAL_ARCHITECTURE §12, §20; RELIABILITY §2 | FA §37 vs tech table | 2, 17 |
| C2 | Term "Worker Runtime" (not "runner") | VOCABULARY_INDEX; PIPELINE_STAGES §19; FINAL_ARCHITECTURE §15 | Terms to Avoid vs v8 "Runner" | — |
| C3 | Budget reserved per step; `tenants.budget_pool` | FINAL_ARCHITECTURE §12; PIPELINE_STAGES §14; RELIABILITY §4; DATABASE budget_reservations | MC-026, DB-RESERVE | 4 |
| C4 | Guard components by name | FINAL_ARCHITECTURE §17; RELIABILITY §1; PIPELINE_STAGES §14, §19 | Layer numbering conflict | 2, 7 |
| C5 | Renewable leases; capacity-bounded acquisition | PIPELINE_STAGES §19; DATABASE worker_leases, execution_leases | MC-010, REL-LEASE | 5 |
| C6 | Step machine corrections; retries inside RUNNING | STATE_TRANSITIONS §2; DATA_CONTRACTS §19; MUTATION_SAFETY §3, §7; FINAL_ARCHITECTURE §19 | MC-037 (partly) | 1, 7, 8 |
| C7 | Run states exactly eight | STATE_TRANSITIONS §1; DATABASE execution_runs | — | 1 |
| C8 | UNKNOWN resolved to success counts as COMPLETED | PIPELINE_STAGES §15 | — | 10 |
| C9 | Step idempotency key `request_id:plan_step_id` | MUTATION_SAFETY §5; FINAL_ARCHITECTURE I-021 | — | 6 |
| C10 | Checkpoints are rows only | MUTATION_SAFETY §7; DATABASE checkpoints | ADR-11 (for this phase: PostgreSQL-only), DB-CKPT | 2 |
| C11 | Topological order; no silent skip | WORKER_LIFECYCLE §12 | — | 15 |
| C12 | Verification and reconciliation code in S13, called from S12 | FINAL_ARCHITECTURE §12 | — | 9 |
| C13 | RECONCILING only when all else terminal | STATE_TRANSITIONS §1; PIPELINE_STAGES §15 | MC-005 | 8 |
| C14 | LOCKED resolved only by probe | PIPELINE_STAGES §14 | — | 4, 14 |
| C15 | Budget exhaustion mid-run → CANCELLED | — (gate-internal) | — | 16a |
| C16 | User cancellation | DATABASE execution_runs (`cancel_requested_at`) | — | 16a |
| C17 | Idempotency hit path | MUTATION_SAFETY §5 | — | 6 |
| C18 | Per-step reconciliation episodes | STATE_TRANSITIONS §10; DATABASE §3 (`step_reconciliations`) | MC-005, Reconciliation "state machine incomplete" (§9) | 8 |
| C19 | Execution vs verification uncertainty | DATA_CONTRACTS VerificationResult; WORKER_LIFECYCLE §8 | — | 9 |
| C20 | `pending_confirmations` vs `Confirmation` | DATABASE pending_confirmations; FINAL_ARCHITECTURE §24 | MC-061 (contract inconsistency); depends on S0–S11 runbook R-Z | 13 |
| C21 | Dead-letter storage | DATABASE dead_letters; DATA_CONTRACTS §23 | — | 11 |
| C22 | Step terminal reasons | STATE_TRANSITIONS §2, I-1; DATA_CONTRACTS §19; DATABASE execution_steps | **XS-1 — RESOLVED BY C22** | 16 |
| C23 | Live authorization revalidation | WORKER_LIFECYCLE §10 (Re-entry Revalidation) | P1-G in-flight kill-switch semantics (for S12–S15) | 16b |
| C24 | One canonical transition table set (gate Appendix A) | STATE_TRANSITIONS §1–§2; DATA_CONTRACTS §19.2, §19.3 | MC-037 | 1, 19 |
| C25 | Fence tokens from one sequence, checked per execution | FINAL_ARCHITECTURE §10, §12, I-004; WORKER_LIFECYCLE §3, §14; DATABASE execution_ownership | MC-011, REL-FENCE | 5, 17, 19 |
| C26 | Lease status stored | STATE_TRANSITIONS §5; DATABASE worker_leases | — | 5, 19 |
| C27 | Cross-state invariants I-1, I-3, I-4, I-8 amended | STATE_TRANSITIONS §12 | — | 11, 16, 19 |
| C28 | Persisted enum values lowercase; CHECKs from enums | DATABASE (status comments); STATE_TRANSITIONS §13 | — | 19 |
| C29 | DeadLetter contract uses `status` | DATA_CONTRACTS §23, VerificationResult | — | 11 |
| C30 | Admission vs revalidation vs budget | WORKER_LIFECYCLE §10 | — | 19 |
| C31 | Budget writes only in BudgetReserver | RELIABILITY §1, §4; PIPELINE_STAGES §14 | — | 19 |
| C32 | Adapter `call_meta`, `probe`, `observe` (additive) | PROVIDER_ADAPTERS §1; FINAL_ARCHITECTURE §37a; RELIABILITY §5, App. A | **RES-5 / MC-048** (interface defined; per-kernel methods per adapter), MC-008, MC-038 (wrapper) | 19 |
| C33 | Budget period, timestamps, step-id uniqueness, schema defects | DATABASE (several); FINAL_ARCHITECTURE §26 | MC-021 / DB-STEPID, MC-022 / DB-TS (new columns), MC-024, DB-SQLITE (for tests), **PIPE-CRASH / ADR-7** (recovery flow superseded) | 19 |
| C34 | `tenant_id` on every S12–S15 row, RLS where enabled | DATABASE | MC-015 / DB-RLS (for S12–S15 tables), P1-H (no cascades) | 18 |
| C35 | Dispatch marker; recovery validity; NOT_EXECUTED | DATABASE execution_steps; WORKER_LIFECYCLE §10 | **ADR-7** (UNKNOWN vs NOT_EXECUTED, validity states, budget reuse), MC-009, VAL-REC | 14, 19 |
| C36 | Static step data flow (interim) | — (gate) | **P0-B stays OPEN**; interim contract: params bound at S9, cross-step references denied at S12 entry | 3, 19 |
| C37 | Half-open breaker, bulkhead during backoff, timeout ordering, no 24h auto-release | RELIABILITY §2, §4, §5, §6 | MC-017 (single node), MC-062, MC-052, ADR-5 (interface ready; persistence deferred to fleet phase) | 7, 19 |
| C38 | FINAL_ARCHITECTURE aligned with later documents | FINAL_ARCHITECTURE (v4.4.0) | I-015 kept true | — |

### 18.2 Laya design note — blocker entries (target phase: LLM layer)

Filed from LAYA_DECISION_ADAPTER.md §15 (the note is DEFERRED; nothing is implemented,
migrated or tested in S0–S11 or S12–S15). IDs are stable.

| ID | Gap | Status |
|---|---|---|
| LB1 | REFLEX calls `provider.decide()`; `RuntimeContract` has no `decide` | DECISION_REQUIRED |
| LB2 | Strategy authority S7 vs S9 (`Step.reflex_choice`) | DECISION_REQUIRED |
| LB3 | Event `dropped` reason codes | PROPAGATION_REQUIRED |
| LB4 | REFLEX "safety-critical tasks" use case contradicts LR1 | DECISION_REQUIRED |
| LB5 | Spec confidence thresholds vs provider scores | DECIDED (pending propagation) |
| LB6 | Choosing among kernel ops needs several FrozenBindingIdentities | OPEN |
| LB7 | Step has no field for a frozen choice set | DECISION_REQUIRED |
| LB8 | Manifest lacks decision-contract / calibration versions | DECISION_REQUIRED |
| LB9 | Step-loop decision position (gate §8 step 4 stays empty in S12–S15) | DECISION_REQUIRED |
| LB10 | S10 confirmation of a candidate set (certified S10) | DECISION_REQUIRED |
| LB11 | Promotion lifecycle state machine and owner | DECISION_REQUIRED |

### 18.3 Deferred by the S12–S15 gate (target phases per gate §21 "Deferred register")

Multi-node fleet and notification channel; distributed circuit breaker persistence
(ADR-5); worker version/deployment lifecycle and worker drain on lease loss; HITL channel
for human verification; automatic rollback triggers; `any`/`threshold` join modes;
parallel step execution; real provider adapters and their per-kernel probe/observe
methods (RES-5); step-to-step data flow (P0-B); alert delivery; circuit-breaker fleet
consistency (P1-B); scheduler fairness (P1-C). Open question: no post-execution
human-approval run state (D4).

---

## SECTION 19: S12–S15 GATE v10 — WORKER-MANAGEMENT RULINGS

**Date**: 2026-09-29. **Source**: S12_S15_EXECUTION_GATE.md v10 C39–C41; `WORKER_MGMT_SPEC_REVIEW.md` Part E (RD-1…RD-18, owner-confirmed).
**Rule**: as Section 18 — rulings DECIDED and PROPAGATED (markers `Worker-management repair (RD-n)`); status `IMPLEMENTATION_REQUIRED` until the certification report cites the passing tests.

### 19.1 Gate rulings

| ID | Subject | Owning document(s) repaired | Resolves / refines | Tests (gate §16) |
|---|---|---|---|---|
| C39 | Worker management: two-phase admission (12a, 13a, 16) + eligibility filters (12b, 13b, 14, 17); pause = new work only; quota consumed once per run at durable admission; `TEXT` worker keys | WORKER_LIFECYCLE §3, §10, §11, §13, §15, §16; DATABASE workers, tenants, workspaces, worker_leases, worker_assignments, `operation_quotas`, RLS, migration 018; DATA_CONTRACTS §50–§52; IDENTITY §5–§8.4; PIPELINE_STAGES §14, §19; STATE_TRANSITIONS §4, I-9, I-10; SECURITY §12a; MUTATION_SAFETY §3; EVENT_GATEWAY §14.7; VALIDATION; VOCABULARY_INDEX | Spec v1.1.0 §3 (worker gates before selection), §2 DDL (UUID FKs to TEXT keys, missing tenant_id), quota overshoot | 20; I17, I18 |
| C40 | Batch processing out of phase; model = BATCH-strategy PlanSteps | FINAL_ARCHITECTURE §15; STATE_TRANSITIONS §16, §17; DATA_CONTRACTS §53 note | Spec v1.1.0 §4 (blind re-execution, shared idempotency key, parallelism, data flow) | — (architecture test: no batch tables) |
| C41 | Replanning out of phase; model = child execution; `parent_execution_id` deferred | FINAL_ARCHITECTURE §29; PIPELINE_STAGES §14 | Spec v1.1.0 §6.1 (I-006, I-017, I9 conflicts) | — |

### 19.2 Other rulings and repairs

| ID | Subject | Documents |
|---|---|---|
| RD-8, RD-9 / I-029 | One execution path for every runtime type; `runtime_type` never selects an adapter in S12; browser providers are bindings | FINAL_ARCHITECTURE §37a, §50; PIPELINE_STAGES §21; PROVIDER_ADAPTERS §9; MUTATION_SAFETY §1 |
| RD-10 | `runtime_type` the only worker-type enum | DATA_CONTRACTS §50; VOCABULARY_INDEX; EVENT_GATEWAY §14.8 |
| RD-14 | `AutonomyLevel` the only autonomy enum | DATA_CONTRACTS §38; IDENTITY §5 |
| RD-15 | Stability Tiers T1–T7 (not "layers") | FINAL_ARCHITECTURE §30; VOCABULARY_INDEX |
| RD-16 | FINAL_ARCHITECTURE numbering: §37b, §37c, §37d, §50, §51; duplicate I-022…I-025 removed; unclosed fence closed | FINAL_ARCHITECTURE; gate C38 table; plan §2; REPAIRS_APPLIED |
| RD-18 | Session 0 prompt on gate v10; items 3–16; P1–P6 | S12_SESSION0_PREFLIGHT_PROMPT |
| E5 | Stale fencing text (per-worker max token) | WORKER_LIFECYCLE §15 Rule 7; DATA_CONTRACTS §37 |
| — | IDENTITY §7 worker lifecycle (STOPPED/DELETED) aligned with STATE_TRANSITIONS §4 | IDENTITY_AND_TENANCY §7 |

### 19.3 Deferred by gate v10 (target phase: worker management II, after S15)

Sub-agent spawning and `worker_spawn_audit`; batch processing (C40); replanning and `parent_execution_id` (C41); worker groups; config versioning; state-change webhooks; L2 session memory and memory classification (needs `MemoryWriteBarrier`); progressive autonomy (S0–S11 change control); PolicyEngine (S8 change control); browser/RPA adapters and skill compositions; templates, plans, entitlements, marketplace listing; `skills_prompt` and `llm_model` consumption (S2, S0–S11 change control); tenant model allow-list in `TenantPolicy`.

### 19.4 Open items

| ID | Item | Status |
|---|---|---|
| WM-O1 | DATA_CONTRACTS has two §31 headings; not renumbered because other documents cite §31–§37 | RECORDED |
| WM-O2 | FINAL_ARCHITECTURE TOC listed "§42 Schema and API Compatibility During Rolling Upgrades", which has no section | RECORDED (covered by §48) |
| WM-O3 | Skill Factory "Skill" vs data-defined skill composition: compile path when the Skill Factory lands | OPEN (post-S15) |

---

## SECTION 20: MEMORY / RAG GROUP (target phase: post-S15, memory / LLM layer)

**Date**: 2026-09-29. **Source**: review of the vector/RAG proposal against FINAL_ARCHITECTURE §20, §21, §36, §37a, §38 and invariants I-001, I-011, I-014, I-020, I-029.

**Blocking rule (owner, 2026-09-29):** no vector code — no `lancedb`/`pgvector` dependency, no `VectorMemoryBackend`, no vector migration, no embedding adapter, no vector capability — is written until **MR-1 is DECIDED and propagated**. MR-2…MR-4 may be discussed in parallel but are `BLOCKED` for implementation until then.

**Enforcement:** S12_S15_EXECUTION_GATE.md v10 §1 (MUST NOT), §14 (deferred list) and suite 2; owner golden guard `tests/golden/s12/test_arch_no_vector_code.py` (draft in `s12_s15_golden/`), run at every milestone exit per plan v3 §4.

| ID | Item | Why | Status | Depends on |
|---|---|---|---|---|
| **MR-1** | **Memory scope contract and physical layout.** Every `MemoryBackend` call takes a mandatory `MemoryScope` (tenant, workspace, worker, user, layer) derived from `ExecutionContext` / `PrincipalChain`, never from LLM output; the backend enforces it (no caller filter strings, no cross-tenant API); async methods; `purge(scope)`; physical layout per store (pgvector: RLS + tenant partitions; LanceDB: one dataset per tenant, path built only by the backend). | §36 `search(vector, limit)` has no scope; LanceDB has no RLS (I-001); memory must be isolated by worker, tenant and user (§21). Retrofitting isolation onto an embedded store is harder than choosing the store with it. | DECISION_REQUIRED — **BLOCKING** | — (decided together with MR-2's store choice) |
| **MR-2** | **Vector backend ADR** — ADR-14 (`ADR-14_VECTOR_MEMORY_BACKEND.md`): recommended Option C, pgvector default, LanceDB optional per deployment with an owner-recorded I-001 exception. | LanceDB (§20, §29) predates the fleet plan; pgvector gives RLS, atomic writes with events (I-020), multi-node sharing and existing PITR. | DECISION_REQUIRED | MR-1 |
| **MR-3** | **Embedding contract.** Either an additive `RuntimeContract.embed()` (§38 has only `generate`, `stream`, `capabilities`, `cost_model`) or an `embed` kernel operation on a Layer 1 provider adapter, with its binding (frozen at S5), cost model, budget reservation, credentials via `CredentialProvider` (I-018) and mutation level `R`. The memory backend (Layer 0) never calls it; callers embed and pass vectors. Vector capabilities (`memory.embed`, `memory.vector_search`, `memory.nearest_neighbors`) are registered in the Provider Package and run through S0→S15 with S8 authorization (I-029), not directly over A2A. | Runtime Contract has no embedding method (same shape as Laya LB1); Layer 0 may not import Layer 1; A2A carries requests into S0, it is not a bypass. | DECISION_REQUIRED — BLOCKED for implementation by MR-1 | MR-1, MR-2 |
| **MR-4** | **Pipeline rulings.** (a) Does an embedding call count toward I-011 ("one LLM call per request, max 2 with retry")? (b) Vector-similarity capability discovery at S3 changes certified S0–S11 code: S0–S11 change control (gate §19.3) and re-certification. | I-011 is written for LLM generation; S3 is certified. | DECISION_REQUIRED — BLOCKED for implementation by MR-1 | MR-1; MR-3 for (a) |

**Also required before vector writes (existing items):** `MemoryWriteBarrier` implementation (I-014; deferred in gate §14 and blocker register §19.3). **Not in S12–S15:** the gate forbids real provider APIs and defers memory, so none of MR-1…MR-4 is implemented in this phase.
