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

### S12–S15 Phase (binding for the implementing agent)

| File | Role |
|------|------|
| `S12_S15_EXECUTION_GATE.md` (v10) | **Binding** phase-locked instruction: rulings C1–C41, normative sequence, suites, invariants I1–I18 |
| `S12_S15_IMPLEMENTATION_PLAN.md` (v3) | Milestones M0–M21 (incl. M8a), golden tests, checkpoints |
| `S12_SESSION0_PREFLIGHT_PROMPT.md` | Session 0 (preflight) prompt for gate v10 |
| `s0_s11_autopilot/` | S0–S11 certification kit and runbook rulings R-Z, **R-P** (pause at S0.1) |
| `s12_s15_golden/` | Owner-owned golden-test drafts (none at present; the vector-code guard was removed when MR-1 was decided) and the deletion-contract pattern |
| `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` | Open, decided and deferred items; §18 (v9), §19 (v10 worker management), §20 (memory / RAG) |
| `REPAIRS_APPLIED.md` | Change log of every documentation repair |
| `XS-1_REGISTER_ENTRY.md`, `LAYA_DECISION_ADAPTER.md` | Resolved entry (C22) and a deferred design note |

### Design References (not binding in S12–S15)

| File | Role |
|------|------|
| `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` (v1.2.1) | Worker-management design and roadmap; gate C39–C41 govern |
| `WORKER_MGMT_SPEC_REVIEW.md` | Review, owner rulings RD-1…RD-18, audit round 2 and propagation record |
| `MEMORY_ARCHITECTURE.md` | Worker memory (deferred; repairs pending, register §20) |
| `ADR-14_VECTOR_MEMORY_BACKEND.md` | ADR (DECIDED, owner 2026-09-29): vector backend = pgvector only, `MemoryScope` contract (memory private to its worker, RLS for the tenant boundary), tier-2 store = Amazon S3, erasure deadline 90 days; memory phase after S15 |
| `ADAPTABILITY_PRINCIPLES.md` | Rationale for FINAL_ARCHITECTURE §37a |

### Traceability

| File | Role |
|------|------|
| `REFAUDIT.md` | State machine cross-reference bugs found and repaired |
| `VOCABULARY_INDEX.md` | Canonical term definitions — prevents semantic drift |

## Code — S0–S11 pre-execution pipeline

Rebuilt from these specifications (2026-09-29). Scope: S0–S11 only; S12–S15 are not
implemented. Python 3.11+, standard library only; tests need `pytest`.

```
src/supragents/
  contracts/      frozen data: vocabulary, entry request, context, registry records,
                  stage outputs, write-once PipelineState, plan hash
  ports/          interfaces to the outside world (activation state, LLM, registry,
                  authorization, policy, confirmation store, clock, event sink)
  policy/         pure rules: sanitizer, effective risk, confirmation rules
  stages/         one module per stage (s00_entry … s11_validation; s08_safety/)
  pipeline/       deps bundle, stage sequence, the one PipelineRunner, RunResult
  observability/  one structured log line per stage
tests/
  unit/ contracts/ journeys/ architecture/   fakes/ (test doubles live only here)
```

Run: `pip install pytest && python -m pytest`, or the one-file check
`python verify_s0_s11.py --sabotage` (all test groups plus 14 sabotage patches, one verdict).
Run the service: `python -m supragents migrate`, `create-api-key`, `serve` (details and the
offline installer in [WORK_PACKAGES.md](WORK_PACKAGES.md)); `.env` holds only secrets
(see `.env.example`).
**Full installation and operation guide:** [INSTALLATION.md](INSTALLATION.md).

**How a run works.** `PipelineRunner.run(entry)` executes S0→S11. After every stage it
logs one line and writes one ledger event; any halt (DENY, CLARIFY, ERROR) stops the run,
and an unexpected exception becomes an ERROR halt. When S10 needs the user's approval
the run returns `AWAITING_CONFIRMATION`; `runner.resume(result, reply)` continues from
S10. Only a completed run carries an `ExecutionManifest` for S12.

**Not included yet:** production adapters for the ports (PostgreSQL stores and registry,
the LLM client, the ledger writer). The tests use fakes from `tests/fakes/`.

**Specification conflicts — owner decisions (2026-09-29):**

| # | Topic | Documents say | Decision |
|---|---|---|---|
| 1 | D confirmation | DATA_CONTRACTS §7: D only above cost 5; PIPELINE_STAGES §12: never run D/IRREVERSIBLE unconfirmed | **Every D and IRREVERSIBLE plan is confirmed** (§12 wins). **Resolved:** the §7 tables in DATA_CONTRACTS, FINAL_ARCHITECTURE, MUTATION_SAFETY and PIPELINE_STAGES, runbook R-V and the S6 golden test (`delete_cost_5_confirmed`) now say so |
| 2 | WORKFLOW route | PIPELINE_STAGES §9: chain, confidence ≥ 0.7, risk ≤ 0.5 | **Keep**: simple or chain, confidence ≥ 0.7, risk below the deny threshold (runbook R-Q row 8); risky plans are confirmed, not refused |
| 3 | Where confirmation is used up | DATA_CONTRACTS §13: S11; PIPELINE_STAGES §12 and gate: S10 | **Keep**: S10 consumes on the user's confirmed reply; S11 requires it consumed. Resolved conflict |
| 4 | Policy version ids | DATA_CONTRACTS §2 lists them on ExecutionContext | **Restored**: `tenant_policy_version_id`, `workspace_policy_version_id`, `policy_version_id` on ExecutionContext; S5 sets them from an injected `PolicyVersionSource` (R-M whitelist) and fails closed if they are missing; the manifest's `policy_version` is `ExecutionContext.policy_version_id` |
| 5 | Pause check id | "R-P" in the S12 documents | **Keep** "S0.1 activation check" in code; the S12 documents get a new ruling id (R-P stays the vocabulary ruling) |

**Line of work:** this branch is a rebuild with its own module layout and tests; it is
not certified and is not merged anywhere. Certification runs only against the owner's
pinned certifier and golden tests in the local repository (`owner_verify.ps1`). Until the
owner picks one line of work, do not merge this branch.

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
19. S12_S15_EXECUTION_GATE.md, S12_S15_IMPLEMENTATION_PLAN.md (the phase in progress)
20. SUPERSESSION_AWARE_BLOCKER_REGISTER.md (open items)
21. Design references above, when working on their area

> **Repair (audit round 2 D2):** the document tables and this order did not list the phase gate, the plan, the register, the spec, the review, ADR-14, MEMORY_ARCHITECTURE or the golden-test drafts.
