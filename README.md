# Implementation Reference

This directory contains **only the documents required to build the implementation**. Every file here is a direct implementation contract — no analysis artifacts, no historical scratch work.

## Documents

### Source of Truth

| File | Role | Authority |
|------|------|-----------|
| `FINAL_ARCHITECTURE.md` | Single source of truth for all architectural decisions | Highest authority |
| `DATA_CONTRACTS.md` | Every type, field, enum, and state machine | Canonical contract for all data |
| `STATE_TRANSITIONS.md` | All legal state transitions across every state machine | AUTHORITATIVE — state machines are defined here |

### Data Model

| File | Role |
|------|------|
| `IDENTITY_AND_TENANCY.md` | Identity vocabulary, tenant/workspace isolation, PrincipalChain |
| `DATABASE.md` | Complete PostgreSQL schema, migrations, indexes, RLS policies |

### Execution

| File | Role |
|------|------|
| `PIPELINE_STAGES.md` | S0–S15 stage definitions, input/output contracts, ordering |
| `RESOLVE_LAYER.md` | Intent → capability → kernel_op → binding → provider → adapter |
| `EVENT_GATEWAY_AND_ROUTER.md` | External event ingress, EventEnvelope contract, WorkerSubscription, EventCorrelator, security |
| `WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md` | WorkerIdentity/Version lifecycles, S12 admission control, S13 independent verification |
| `PROVIDER_ADAPTERS.md` | Adapter interface, error classification, UNKNOWN propagation |

### Safety & Reliability

| File | Role |
|------|------|
| `MUTATION_SAFETY.md` | Read/write/delete/irreversible classification, confirmation rules |
| `SECURITY.md` | Auth, authorization, injection defense, secret handling, guardrails |
| `RELIABILITY.md` | 5-layer reliability guard, retries, circuit breakers, budgets |

### Planning & Verification

| File | Role |
|------|------|
| `EXECUTION_PLAN.md` | W0–W6 implementation phases, ownership, test gates |
| `VALIDATION.md` | Test specifications for every contract, stage, and boundary |
| `BUILD_READINESS_MATRIX.md` | Closure checklist — every document must be complete before implementation |
| `COMPONENTS_BLUEPRINT.md` | Directory structure, file ownership, module boundaries |

### Traceability

| File | Role |
|------|------|
| `REFAUDIT.md` | State machine cross-reference bugs found and repaired |
| `VOCABULARY_INDEX.md` | Canonical term definitions — prevents semantic drift |

## What's NOT Here

The parent `rebuild/` folder contains historical and analytical documents that informed these contracts but are not required for implementation:

- `ARCHITECTURAL_GROUPINGS.md` — analysis artifact
- `ARCHITECTURE_AUDIT.md` — historical audit
- `COMPLETE_REBUILD_PROMPT.md` — original kick-off prompt
- `CRITICAL_FIXES.md` — superseded by EXECUTION_PLAN.md
- `CROSS_DOCUMENT_RECONCILIATION.md` — superseded by REFAUDIT.md
- `GAP_ANALYSIS.md` — historical analysis
- `HUMAN_IN_THE_LOOP.md` — absorbed into MUTATION_SAFETY.md and PIPELINE_STAGES.md
- `ISSUES_CATEGORIZED.md` — historical tracking
- `MASTER_ARCHITECTURE_FINAL.md` — predecessor to FINAL_ARCHITECTURE.md
- `MEMORY_ARCHITECTURE.md` — **now in this directory** (added 2026-09-29), status DEFERRED with repairs pending: see its `Memory repair (MR-n)` markers and blocker register Section 20
- `REPAIRS_APPLIED.md` — superseded by REFAUDIT.md
- `SKILL_FACTORY_ARCHITECTURE.md` — deferred (Skill Factory design not finalized)
- `STUDY_SUMMARY.md` — research input, not a contract
- `progress.md` — historical progress log
- `TRACING_AND_CONCURRENCY.md` — content absorbed into other documents

## Dependency Order

When reading these documents for implementation, follow this order:

1. FINAL_ARCHITECTURE.md (source of truth)
2. VOCABULARY_INDEX.md (terminology)
3. IDENTITY_AND_TENANCY.md (identity model)
4. DATA_CONTRACTS.md (all types and contracts)
5. STATE_TRANSITIONS.md (state machines)
6. DATABASE.md (schema, migrations)
7. RESOLVE_LAYER.md (resolution chain)
8. PIPELINE_STAGES.md (execution flow)
9. WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md (S12, S13)
10. PROVIDER_ADAPTERS.md (adapter interface)
11. SECURITY.md (security enforcement)
12. MUTATION_SAFETY.md (mutation rules)
13. RELIABILITY.md (reliability guards)
14. COMPONENTS_BLUEPRINT.md (directory structure)
15. EXECUTION_PLAN.md (implementation phases)
16. VALIDATION.md (tests)
17. BUILD_READINESS_MATRIX.md (closure checklist)
18. REFAUDIT.md (reconciliation history)
