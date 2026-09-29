# Build Readiness Matrix

**Purpose**: Pre-implementation closure checklist. Every item must be complete before writing implementation code.

**Version**: 1.1.1 | **Last Updated**: 2026-09-29

**1.1.1 (2026-09-29, audit round 2 D3)**: duplicate row numbers 9 and 10 in Tier 2 renumbered 27 and 28; absent documents (13, 15, 16) marked ABSENT instead of COMPLETE.
**1.1.0 (2026-09-29)**: worker-management propagation (gate v10 C39–C41, rulings RD-1…RD-18 in `WORKER_MGMT_SPEC_REVIEW.md` Part E). Tier 1 rows note the worker-management content; new rows 25–26.

---

## Legend

| Status | Description |
|--------|-------------|
| **COMPLETE** | Document exists and is authoritative |
| **PARTIAL** | Document exists but needs updates |
| **MISSING** | Document does not exist |
| **PENDING** | Identified but not yet started |
| **DEPENDENCY** | Required before this item can be completed |

---

## Tier 1 — Mandatory (Cannot start implementation without these)

| # | Document | Status | Last Verified | Notes |
|---|----------|--------|---------------|-------|
| 1 | `FINAL_ARCHITECTURE.md` | COMPLETE | 2026-09-25 | Authoritative system overview |
| 2 | `COMPONENTS_BLUEPRINT.md` | COMPLETE | 2026-09-25 | Directory structure, file ownership |
| 3 | `DATA_CONTRACTS.md` | COMPLETE | 2026-09-26 | All data structures, schemas, state machines (+ WorkerIdentity, WorkerVersion, WorkerDeployment, Verifier, VerificationResult, AdmissionDecision, ExecutionOwnership) |
| 4 | `PIPELINE_STAGES.md` | COMPLETE | 2026-09-26 | 15-stage pipeline (+ admission control, independent verification, state locality) |
| 5 | `STATE_TRANSITIONS.md` | COMPLETE | 2026-09-26 | All state machines (ExecutionRun, Step, Budget, Worker, Lease, Capability, Binding, Confirmation, DeadLetter, Reconciliation, CircuitBreaker) |
| 6 | `EXECUTION_PLAN.md` | COMPLETE | 2026-09-25 | Execution correctness plan, W0-W6 |
| 7 | `RELIABILITY.md` | COMPLETE | 2026-09-26 | 5-layer reliability guard (+ billing ownership, HealthMonitor) |
| 8 | `SECURITY.md` | COMPLETE | 2026-09-26 | Security model, prompt injection defense (+ injection patterns, severity-action mapping) |
| 9 | `DATABASE.md` | COMPLETE | 2026-09-29 | Database schema, migrations (+ memberships, worker_versions, worker_deployments, execution_ownership, provider_tokens, retry_log, outbox; + worker `TEXT` keys, management columns, `operation_quotas`, migration 018) |
| 10 | `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md` | COMPLETE | 2026-09-29 | Worker identity/version lifecycle, independent verification, admission control, state locality (+ §16 worker management, eligibility filters, operation quota) |
| 25 | `S12_S15_EXECUTION_GATE.md` v10 | COMPLETE | 2026-09-29 | Binding S12–S15 rulings C1–C41 (C39 worker management; C40/C41 batch and replanning out of phase) |
| 26 | `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` v1.2.1 | REFERENCE | 2026-09-29 | Worker-management design and roadmap; gate C39–C41 govern |

## Tier 2 — Required Before M0 Complete

| # | Document | Status | Last Verified | Notes |
|---|----------|--------|---------------|-------|
| 27 | `PROVIDER_ADAPTERS.md` | COMPLETE | 2026-09-25 | Provider adapter specifications |
| 28 | `IDENTITY_AND_TENANCY.md` | COMPLETE | 2026-09-25 | Multi-tenant identity, RLS, isolation |
| 11 | `RESOLVE_LAYER.md` | COMPLETE | 2026-09-25 | Capability → Kernel → Binding → Adapter |
| 12 | `MUTATION_SAFETY.md` | COMPLETE | 2026-09-25 | Mutation taxonomy, retry, confirmation |
| 13 | `SKILL_FACTORY_ARCHITECTURE.md` | ABSENT | 2026-09-29 | Not in this directory (README "What's NOT Here": deferred); gate preflight item 8 checks it. Not needed for S12–S15 |
| 14 | `MEMORY_ARCHITECTURE.md` | REPAIRS PENDING | 2026-09-29 | Worker memory, context lifecycle, cross-session state. Present since 2026-09-29; findings MR-5…MR-10 (register Section 20); vector parts blocked by MR-1. Deferred to the memory phase, not needed for S12–S15 |

## Tier 3 — Required Before M1 Complete

| # | Document | Status | Last Verified | Notes |
|---|----------|--------|---------------|-------|
| 15 | `HUMAN_IN_THE_LOOP.md` | ABSENT | 2026-09-29 | Not in this directory (absorbed into MUTATION_SAFETY.md and PIPELINE_STAGES.md); gate preflight item 8 checks it |
| 16 | `TRACING_AND_CONCURRENCY.md` | ABSENT | 2026-09-29 | Not in this directory (content absorbed into other documents); gate preflight item 8 checks it |
| 17 | `CONCURRENCY_MODEL.md` | MISSING | — | Step-level parallelism, shared-state rules |
| 18 | `OBSERVABILITY_AND_DEBUGGING.md` | MISSING | — | Metrics, dashboards, alerting, runbooks |
| 19 | `VALIDATION.md` | COMPLETE | 2026-09-25 | Testing strategy, contract tests |

## Tier 4 — Required Before M2+

| # | Document | Status | Last Verified | Notes |
|---|----------|--------|---------------|-------|
| 20 | `MULTI_AGENT_COORDINATION.md` | MISSING | — | Agent-to-agent, handoff, swarm contracts |
| 21 | `OPERATIONS_RUNBOOK.md` | MISSING | — | Startup, shutdown, disaster recovery |
| 22 | `TESTING_STRATEGY.md` | MISSING | — | Contract, integration, chaos, load tests |
| 23 | `MIGRATION_GUIDE.md` | MISSING | — | Schema migrations, feature flags |
| 24 | `DEVELOPER_ONBOARDING.md` | MISSING | — | Adding providers, capabilities, debugging |

## Dependency Graph

```
MASTER_ARCHITECTURE_FINAL.md
    ├── COMPONENTS_BLUEPRINT.md
    ├── DATA_CONTRACTS.md
    │   └── PIPELINE_STAGES.md
    │       └── EXECUTION_PLAN.md
    ├── RELIABILITY.md
    │   └── MUTATION_SAFETY.md
    ├── SECURITY.md
    ├── IDENTITY_AND_TENANCY.md
    ├── RESOLVE_LAYER.md
    │   └── PROVIDER_ADAPTERS.md
    ├── SKILL_FACTORY_ARCHITECTURE.md
    ├── MEMORY_ARCHITECTURE.md
    ├── HUMAN_IN_THE_LOOP.md
    ├── TRACING_AND_CONCURRENCY.md
    └── DATABASE.md
        ├── CONCURRENCY_MODEL.md (PENDING)
        ├── OBSERVABILITY_AND_DEBUGGING.md (PENDING)
        └── MULTI_AGENT_COORDINATION.md (PENDING)
```

**DAG Rules**:
1. Arrows point from producer to consumer. A document cannot be authored before all its dependencies are stable.
2. No cycles are permitted. If document A depends on B and B depends on A, the cycle must be broken by extracting a shared dependency C.
3. All Tier 1–2 documents must be finalized before Tier 3–4 documents are touched.
4. Build order is topological: `MASTER_ARCHITECTURE_FINAL.md` → `DATA_CONTRACTS.md` → `PIPELINE_STAGES.md` → `EXECUTION_PLAN.md` → implementation.
5. Any document that blocks implementation is a P0. Any document that blocks integration testing is P1.
6. The DAG above is the canonical build order. Changes to the DAG require explicit approval.

---

## Document Relationships

| Document | Depends On | Enables |
|----------|------------|---------|
| MASTER_ARCHITECTURE_FINAL.md | None | All others |
| COMPONENTS_BLUEPRINT.md | MASTER_ARCHITECTURE_FINAL.md | Implementation |
| DATA_CONTRACTS.md | MASTER_ARCHITECTURE_FINAL.md | Implementation |
| PIPELINE_STAGES.md | DATA_CONTRACTS.md | Implementation |
| EXECUTION_PLAN.md | PIPELINE_STAGES.md | Implementation |
| RELIABILITY.md | DATA_CONTRACTS.md | Implementation |
| SECURITY.md | DATA_CONTRACTS.md | Implementation |
| MUTATION_SAFETY.md | RELIABILITY.md, PIPELINE_STAGES.md | Implementation |
| IDENTITY_AND_TENANCY.md | DATA_CONTRACTS.md | Implementation |
| RESOLVE_LAYER.md | DATA_CONTRACTS.md, MASTER_ARCHITECTURE_FINAL.md | Implementation |
| PROVIDER_ADAPTERS.md | RESOLVE_LAYER.md, MASTER_ARCHITECTURE_FINAL.md | Implementation |
| SKILL_FACTORY_ARCHITECTURE.md | MASTER_ARCHITECTURE_FINAL.md, RESOLVE_LAYER.md | Implementation |
| MEMORY_ARCHITECTURE.md | MASTER_ARCHITECTURE_FINAL.md, DATA_CONTRACTS.md | M1 implementation |
| HUMAN_IN_THE_LOOP.md | PIPELINE_STAGES.md, DATA_CONTRACTS.md | M1 implementation |
| TRACING_AND_CONCURRENCY.md | DATA_CONTRACTS.md, EXECUTION_PLAN.md | M1 implementation |
| CONCURRENCY_MODEL.md | TRACING_AND_CONCURRENCY.md, EXECUTION_PLAN.md | M2 implementation |
| OBSERVABILITY_AND_DEBUGGING.md | DATA_CONTRACTS.md, EXECUTION_PLAN.md | M1 implementation |
| MULTI_AGENT_COORDINATION.md | MEMORY_ARCHITECTURE.md, HUMAN_IN_THE_LOOP.md | M3 implementation |
| OPERATIONS_RUNBOOK.md | All Tier 1-3 docs | M2 implementation |
| TESTING_STRATEGY.md | All Tier 1-2 docs | M0 implementation |
| MIGRATION_GUIDE.md | DATABASE.md | M1 implementation |
| DEVELOPER_ONBOARDING.md | All Tier 1-2 docs | Ongoing |

## Completion Criteria

### M0 Complete When
- [ ] All Tier 1 documents are COMPLETE
- [ ] All Tier 2 documents (9-14) are COMPLETE
- [ ] Implementation passes all contract tests
- [ ] CI pipeline green

### M1 Complete When
- [ ] All Tier 1 and Tier 2 documents are COMPLETE
- [ ] Tier 3 documents (15-19) are COMPLETE
- [ ] Durable execution kernel implemented
- [ ] Worker identity system implemented
- [ ] Multi-tenant RLS verified

### M2+ Complete When
- [ ] All Tier 1-3 documents are COMPLETE
- [ ] Tier 4 documents (20-24) are COMPLETE
- [ ] Worker pools implemented
- [ ] Horizontal scaling verified
- [ ] Observability dashboard operational

## Review Checklist

Before implementation starts, verify:

- [ ] No document references a missing or unimplemented component
- [ ] No component is referenced in implementation but not documented
- [ ] All data structures in DATA_CONTRACTS.md are implemented in DATABASE.md
- [ ] All pipeline stages in PIPELINE_STAGES.md have implementation in EXECUTION_PLAN.md
- [ ] All reliability patterns in RELIABILITY.md have tests in VALIDATION.md
- [ ] All security controls in SECURITY.md are enforced in implementation
- [ ] All provider adapters in PROVIDER_ADAPTERS.md have contract tests
- [ ] All memory operations in MEMORY_ARCHITECTURE.md have implementations
- [ ] All HITL flows in HUMAN_IN_THE_LOOP.md have implementations
- [ ] Cross-document references are consistent (no conflicting definitions)
- [ ] No legacy references to OpenFlow/CRX remain in any document
- [ ] No semantic capability layer references remain in executable code paths
