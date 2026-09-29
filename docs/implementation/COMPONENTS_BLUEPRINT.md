# Components Blueprint

**Purpose**: Complete directory structure, file ownership, module dependencies, and build system for the rebuild. This tells you exactly where every file goes, what it contains, and what it can import.

---

## Table of Contents

1. [Directory Structure](#1-directory-structure)
2. [Layer 0 — Shared Foundation](#2-layer-0--shared-foundation)
3. [Layer 1 — Provider Adapters](#3-layer-1--provider-adapters)
4. [Layer 2 — Registry](#4-layer-2--registry)
5. [Layer 3 — Execution Engine](#5-layer-3--execution-engine)
6. [Layer 4 — Control Plane](#6-layer-4--control-plane)
7. [Layer 5 — Interface](#7-layer-5--interface)
8. [Registry & Code Generation](#8-registry--code-generation)
9. [Testing Structure](#9-testing-structure)
10. [Configuration](#10-configuration)
11. [Dependency Rules](#11-dependency-rules)
12. [Build System](#12-build-system)
13. [Wave Engineering Discipline](#13-wave-engineering-discipline)
14. [New Subsystem Locations](#14-new-subsystem-locations)

---

## 1. Directory Structure

```
supr/
├── pyproject.toml                 # Project config, dependencies
├── Makefile                       # Build shortcuts
├── .gitignore                     # Git ignore rules
├── README.md                      # Project readme
│
├── registry/                      # ⭐ SINGLE SOURCE OF TRUTH
│   ├── kernel_definitions.yaml    # ALL kernel operations defined here
│   ├── engine_map.yaml            # Provider prefix → module mapping
│   └── schemas/                   # JSON schemas for validation
│       ├── intent_result.json
│       └── plan.json
│
├── shared/                        # ⭐ LAYER 0 — Pure utilities
│   ├── __init__.py
│   ├── database.py                # Database class (singleton, WAL mode)
│   ├── config.py                  # Configuration loader (env vars)
│   ├── exceptions.py              # Exception hierarchy
│   ├── sanitizer.py               # DataSanitizer (injection detection)
│   ├── envelope.py                # Envelope, EnvelopeError
│   ├── circuit.py                 # CircuitBreaker
│   ├── identity.py                # Identity generation (UUIDs, trace IDs)
│   ├── isolation.py               # Isolation utilities
│   ├── undo.py                    # Undo token management
│   ├── confirm.py                 # Confirmation token management
│   ├── cache.py                   # Simple caching
│   └── retry.py                   # Retry decorators
│
├── engine/
│   ├── __init__.py
│   │
│   ├── registry/                  # LAYER 2 — Capability Registry
│   │   ├── __init__.py
│   │   ├── engine_map.py          # ENGINE_MAP dict (explicit, no fallback)
│   │   ├── resolver.py            # RegistryResolver (capability → kernel → binding)
│   │   ├── capability_spine.py    # CapabilitySpine (intent → capability mapping)
│   │   └── assertions.py          # CI assertions for registry integrity
│   │
│   ├── providers/                 # LAYER 1 — Provider Adapters
│   │   ├── __init__.py
│   │   ├── base.py                # BaseAdapter ABC
│   │   ├── ghl_public/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # GHLPublicAdapter
│   │   │   ├── kernels.py         # 15 kernel methods
│   │   │   ├── kernel_meta.py     # KERNEL_MAP (generated from YAML)
│   │   │   ├── aliases.py         # AliasRegistry
│   │   │   ├── policy.py          # Mutation, cost, scope constants
│   │   │   ├── schema.py          # Domain dataclasses
│   │   │   ├── assertions.py      # CI assertions
│   ���   │   └── policy/
│   │   │       └── execution.yaml
│   │   ├── ghl_workflow/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # GHLWorkflowAdapter
│   │   │   ├── kernels.py         # 12 kernel methods
│   │   │   ├── kernel_meta.py     # KERNEL_MAP (generated)
│   │   │   ├── aliases.py
│   │   │   ├── policy.py
│   │   │   ├── schema.py
│   │   │   ├── assertions.py
│   │   │   └── policy/
│   │   │       └── execution.yaml
│   │   ├── notion/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # NotionAdapter
│   │   │   ├── kernels.py         # 12 kernel methods
│   │   │   ├── kernel_meta.py     # KERNEL_MAP (generated)
│   │   │   ├── aliases.py
│   │   │   ├── policy.py
│   │   │   ├── schema.py
│   │   │   ├── assertions.py
│   │   │   └── policy/
│   │   │       └── execution.yaml
│   │   ├── google/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # GoogleWorkspaceAdapter
│   │   │   ├── kernels.py         # 20 kernel methods (7 services)
│   │   │   ├── kernel_meta.py     # KERNEL_MAP (generated)
│   │   │   ├── aliases.py
│   │   │   ├── policy.py
│   │   │   ├── schema.py
│   │   │   ├── assertions.py
│   │   │   └── policy/
│   │   │       └── execution.yaml
│   │   └── airtable/
│   │       ├── __init__.py
│   │       ├── adapter.py         # AirtableAdapter
│   │       ├── kernels.py         # 37 kernel methods
│   │       ├── kernel_meta.py     # KERNEL_MAP (generated) — MUST CREATE
│   │       ├── aliases.py         # — MUST CREATE
│   │       ├── policy.py          # — MUST CREATE
│   │       ├── schema.py          # — MUST CREATE
│   │       ├── assertions.py      # — MUST CREATE
│   │       └── policy/
│   │           └── execution.yaml # — MUST CREATE
│   │
│   ├── execution/                  # LAYER 3 — Execution Engine
│   │   ├── __init__.py
│   │   ├── engine.py              # ExecutionEngine
│   │   ├── plan.py                # Plan, Step, Layer dataclasses
│   │   ├── planner/
│   │   │   ├── __init__.py
│   │   │   ├── fast.py            # FastPlanner
│   │   │   ├── workflow.py        # WorkflowPlanner
│   │   │   └── agentic.py         # AgenticPlanner
│   │   ├── retry.py               # RetryPolicy (mutation-aware)
│   │   ├── consolidation.py       # Step result consolidation
│   │   ├── checkpoint.py          # CheckpointManager
│   │   ├── dead_letter.py         # DeadLetterStore
│   │   └── state.py               # StepState enum
│   │
│   ├── control_plane/             # LAYER 4 — Control Plane
│   │   ├── __init__.py
│   │   ├── pipeline.py            # Pipeline orchestrator (15 stages)
│   │   ├── entry.py               # S0: Entry
│   │   ├── normalize.py           # S1: Normalize
│   │   ├── intent.py              # S2: IntentAnalyzer (1 LLM call)
│   │   ├── capability.py          # S3: CapabilityDiscovery
│   │   ├── graph.py               # S4: GraphClassifier
│   │   ├── provider_resolve.py    # S5: ProviderResolver
│   │   ├── task_profile.py        # S6: TaskProfileBuilder
│   │   ├── routing.py             # S7: PathRouter
│   │   ├── safety.py              # S8: SafetyGate (8 checks)
│   ���   ├── plan_validate.py       # S9: PlanValidator
│   │   ├── confirmation.py        # S10: ConfirmationManager
│   │   ├── authorizer.py          # CapabilityAuthorizer (deterministic, NO LLM)
│   │   └── response.py            # S15: ResponseFormatter
│   │
│   └── reliability/               # Reliability Layer
│       ├── __init__.py
│       ├── guard.py               # ReliabilityGuard (5 layers)
│       ├── circuit_breaker.py     # CircuitBreaker (per-provider)
│       ├── retry_guard.py         # RetryStormGuard
│       ├── budget.py              # BudgetTracker
│       ├── timeout.py             # TimeoutManager
│       ├── bulkhead.py            # Bulkhead (provider isolation)
│       └── health.py              # HealthMonitor
│
├── logic/                          # Pure logic (no side effects)
│   ├── __init__.py
│   ├── retry/
│   │   ├── __init__.py
│   │   ├── backoff.py             # Exponential backoff + jitter
│   │   └── retry_policy.py        # Retry decision logic
│   └── llm/
│       ├── __init__.py
│       ├── client.py              # LLM client wrapper
│       ├── structured.py          # JSON mode / schema validation
│       └── prompts.py             # System prompts
│
├── servers/                        # Server implementations
│   ├── __init__.py
│   ├── telegram_bot.py            # Claude Code bot server
│   └── webhook_server.py          # Webhook server (future)
│
├── tools/                          # Code generation & validation tools
│   ├── __init__.py
│   ├── generate_kernel_meta.py    # YAML → kernel_meta.py
│   ├── generate_tools.py          # YAML → servers/tools/*.py
│   ├── generate_migration.py      # YAML → SQL migration
│   ├── verify_generated.py        # Verify generated files have sentinel
│   ├── check_registry.py          # Check YAML ↔ DB consistency
│   ├── check_adapter.py           # Check adapter completeness
│   ├── check_engine_map.py        # Check ENGINE_MAP completeness
│   └── scan_secrets.py            # Scan for credentials in code
│
├── tests/                          # ⭐ ALL TESTS
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures
│   │
│   ├── unit/                      # Tier 1: Unit tests
│   │   ├── __init__.py
│   │   ├── test_consolidation.py
│   │   ├── test_retry_policy.py
│   │   ├── test_retry_backoff.py
│   │   ├── test_state_transitions.py
│   │   ├── test_sanitizer.py
│   │   ├── test_idempotency.py
│   │   ├── test_budget.py
│   │   ├── test_circuit_breaker.py
│   │   ├── test_path_routing.py
│   │   ├── test_safety_gate.py
│   │   ├── test_plan_validator.py
│   │   ├── test_execution_context.py
│   │   └── test_envelope.py
│   │
│   ├── contract/                  # Tier 2: Contract tests
│   │   ├── __init__.py
│   │   ├── conftest.py            # Adapter fixtures
│   │   ├── test_ghl_public.py
│   │   ├── test_ghl_workflow.py
│   │   ├── test_notion.py
│   │   ├── test_google.py
│   │   ├── test_airtable.py
│   │   └── test_adapter_base.py   # Tests every adapter must pass
│   │
│   ├── integration/               # Tier 3: Integration tests
│   │   ├── __init__.py
│   │   ├── test_full_pipeline.py
│   │   ├── test_confirm_flow.py
│   │   ├── test_rollback.py
│   │   └── test_partial_execution.py
│   │
│   ├── chaos/                     # Tier 4: Chaos tests
│   │   ├── __init__.py
│   │   ├── test_retry_storm.py
│   │   ├── test_circuit_breaker_chaos.py
│   │   ├── test_budget_chaos.py
│   │   └── test_concurrent.py
│   │
│   └── fixtures/                  # Recorded API responses
│       ├── ghl_public_live.json
│       ├── ghl_workflow_live.json
│       ├── notion_live.json
│       ├── google_calendar_live.json
│       ├── google_sheets_live.json
│       └── airtable_live.json
│
├── db/                            # Database
│   ├── schema.sql                 # Complete schema definition
│   └── migrations/                # Versioned migrations
│       ├── 001_initial.sql
│       ├── 002_kernel_ops.sql
│       ├── 003_bindings.sql
│       ├── 004_actions.sql
│       ├── 005_executions.sql
│       ├── 006_checkpoints.sql
│       ├── 007_idempotency.sql
│       ├── 008_confirmations.sql
│       └── 009_dead_letters.sql
│
├── data/                          # Runtime data (gitignored)
│   ├── supr.db               # SQLite database
│   └── checkpoints/              # Execution checkpoints
│
├── logs/                          # Application logs (gitignored)
│
└── docs/                          # Documentation
    ├── GHL_API.md
    ├── NOTION_API.md
    ├── GOOGLE_API.md
    └── AIRTABLE_API.md
```

### 1.5. Architecture Ownership Matrix

Every architectural domain has a single canonical owner. No component is orphaned.

| Domain | Canonical File | Owner (Module) |
|--------|---------------|----------------|
| Database schema, migrations, RLS | `db/` | Data layer |
| Identity & tenancy | `shared/identity.py`, `shared/isolation.py` | Shared layer |
| Frozen contracts (ExecutionContext, FrozenBindingIdentity, etc.) | `contracts/` | Contracts layer |
| State machines (Execution, Step, Budget, Lease, etc.) | `contracts/state_validators.py` | Contracts layer |
| Pipeline stages S0–S15 | `engine/control_plane/pipeline.py` | Control Plane |
| Capability registry & resolution | `engine/registry/` | Registry |
| Provider adapters | `engine/providers/<provider>/` | Adapter layer |
| Reliability guard (circuit breaker, retry, budget, timeout) | `engine/reliability/` | Reliability layer |
| Worker identity, version, deployment | `engine/execution/worker/` | Execution Engine |
| Admission control (S12) | `engine/control_plane/admission.py` | Control Plane |
| Independent verification (S13) | `engine/control_plane/verification.py` | Control Plane |
| Reconciliation (UNKNOWN → probe) | `engine/control_plane/reconciliation.py` | Control Plane |
| Execution ledger | `engine/control_plane/ledger.py` | Control Plane |
| A2A messaging | `engine/execution/a2a/` | Execution Engine |
| Memory L0–L6 | `memory/` | Memory subsystem |
| Event gateway | `event_gateway/` | Event Gateway |
| Processor runtime | `processor/` | Processor Runtime |
| HITL confirmation flows | `engine/control_plane/confirmation.py` | Control Plane |
| Observability (traces, metrics, logs) | `observability/` | Observability |
| Configuration versioning | `contracts/configuration_version.py` | Contracts layer |
| Security (auth, injection defense, secret handling) | `shared/sanitizer.py`, `SECURITY.md` | Shared layer |
| Mutation safety rules | `MUTATION_SAFETY.md`, `engine/control_plane/safety.py` | Control Plane |
| Certification lifecycle | `docs/certification/` | All layers |

**Rule**: If a domain is not in this table, it is orphaned. Add it before implementing.

### 1.6. Module Ownership Matrix

Each Python module/file has a single owner. Cross-module logic is forbidden.

| Module | Owner | Can Import From |
|--------|-------|-----------------|
| `shared/*` | Shared layer | stdlib only |
| `engine/providers/*` | Provider layer | `shared/` only |
| `engine/registry/*` | Registry layer | `shared/` only |
| `engine/execution/*` | Execution layer | `shared/`, `engine/registry/` |
| `engine/control_plane/*` | Control Plane | `shared/`, `engine/registry/`, `engine/execution/`, `engine/reliability/` |
| `engine/reliability/*` | Reliability layer | `shared/` only |
| `memory/*` | Memory layer | `shared/` only |
| `event_gateway/*` | Event Gateway | `shared/` only |
| `processor/*` | Processor layer | `shared/` only |
| `observability/*` | Observability layer | `shared/` only |
| `logic/*` | Logic layer | `shared/` only |
| `servers/*` | Interface layer | All lower layers |
| `contracts/*` | Contracts layer | `shared/` only |
| `db/*` | Data layer | `shared/` only |

**Rule**: `servers/` (Layer 5) is the ONLY layer that imports from multiple lower layers. No other cross-layer imports are permitted.

### 1.7. Component Card Template

Every component must have a completed card before implementation begins.

```markdown
## Component Card: <ComponentName>

**Location**: `<file path>`
**Owner**: `<module from Module Ownership Matrix>`
**Dependencies**: `<list of other components>`
**Status**: DESIGN_LOCKED | IMPLEMENTATION_READY | IMPLEMENTED | CERTIFIED

### Contract
- **Inputs**: `<types and descriptions>`
- **Outputs**: `<types and descriptions>`
- **Errors**: `<error types this component can produce>`
- **Side Effects**: `<what this component modifies>`

### State Machine
- **States**: `<list of states>`
- **Transitions**: `<valid transitions>`
- **Invariants**: `<conditions that must always hold>`

### Security Boundary
- **Can access**: `<data sources this component reads>`
- **Can modify**: `<data sources this component writes>`
- **Cannot access**: `<data sources this component is forbidden from>`

### Trace Events
- **Emits**: `<event types this component produces>`
- **Consumes**: `<event types this component listens for>`

### Test Strategy
- **Unit**: `<what to test in isolation>`
- **Contract**: `<what to test against the contract>`
- **Negative**: `<failure modes to test>`
- **Security**: `<security boundaries to verify>`
- **Concurrency**: `<concurrency scenarios to test>`

### Certification Criteria
- **E0**: `<evidence needed for DESIGNED>`
- **E1**: `<evidence needed for BUILT>`
- **E2**: `<evidence needed for CONTRACT_VALIDATED>`
- **E3**: `<evidence needed for TESTED>`
- **E4**: `<evidence needed for FAILURE_TESTED>`
```

**Rule**: No component enters implementation without a completed card. The card is stored in the component's file as a docstring or adjacent `.md` file.

---

## 2. Layer 0 — Shared Foundation

**Location**: `shared/`

**Dependencies**: stdlib only. Imports NOTHING from the system.

**Rule**: Layer 0 is the leaf. Nothing below it. Everything above imports from it.

| File | Purpose | Key Exports |
|------|---------|-------------|
| `database.py` | Database class (singleton, WAL mode) | `Database` |
| `config.py` | Configuration loader | `Config`, `get_config()` |
| `exceptions.py` | Exception hierarchy | `SuprAgentsError`, `ValidationError`, `ProviderError`, etc. |
| `sanitizer.py` | Injection detection & sanitization | `DataSanitizer` |
| `envelope.py` | Envelope & EnvelopeError | `Envelope`, `EnvelopeError` |
| `circuit.py` | Circuit breaker | `CircuitBreaker`, `CircuitState` |
| `identity.py` | UUID & trace ID generation | `generate_request_id()`, `generate_correlation_id()` |
| `undo.py` | Undo token management | `UndoManager` |
| `confirm.py` | Confirmation token management | `ConfirmationLedger` |
| `cache.py` | Simple caching | `Cache` |

---

## 3. Layer 1 — Provider Adapters

**Location**: `engine/providers/<provider>/`

**Dependencies**: `shared/` only. Imports NOTHING from engine/.

**Rule**: Adapters are leaves. Nothing below them. They call external APIs and return KernelResult.

### The 7-File Pattern

Every provider adapter has exactly 8 files:

| File | Purpose | Generated? |
|------|---------|-----------|
| `__init__.py` | Public exports | No |
| `adapter.py` | ProviderAdapter implementation | No |
| `kernels.py` | Kernel classes (request/response builders) | No |
| `kernel_meta.py` | KERNEL_MAP dict (all kernel metadata) | **YES** (from YAML) |
| `aliases.py` | Capability aliases | No |
| `policy.py` | Mutation, cost, scope constants | No |
| `schema.py` | Domain dataclasses | No |
| `assertions.py` | CI assertions | No |

### Adapter Directory Structure

```
engine/providers/<provider>/
  ├── __init__.py        # from .adapter import <Provider>Adapter
  ├── adapter.py         # ProviderAdapter implementation
  ├── kernels.py         # Kernel classes (request/response builders)
  ├── kernel_meta.py     # ⚠️ AUTO-GENERATED — KERNEL_MAP dict
  ├── aliases.py         # AliasRegistry
  ├── policy.py          # Mutation, cost, scope constants
  ├── schema.py          # Domain dataclasses
  ├── assertions.py      # CI assertions
  └── policy/
      └── execution.yaml # Execution policies
```

### Provider Summary

| Provider | Directory | Kernels | Auth | Status |
|----------|-----------|---------|------|--------|
| GHL Public | `engine/providers/ghl_public/` | 15 | PIT token | Production |
| GHL Workflow | `engine/providers/ghl_workflow/` | 12 | Firebase JWT | Production |
| Notion | `engine/providers/notion/` | 12 | Bearer token | Production |
| Google | `engine/providers/google/` | 20 | OAuth 2.0 | Production |
| Airtable | `engine/providers/airtable/` | 37 | PAT | Needs completion |

---

## 4. Layer 2 — Registry

**Location**: `engine/registry/`

**Dependencies**: `shared/` only.

**Rule**: Registry resolves capabilities to kernels to adapters. It does NOT execute API calls.

| File | Purpose | Key Exports |
|------|---------|-------------|
| `engine_map.py` | ENGINE_MAP dict (explicit, no fallback) | `ENGINE_MAP` |
| `resolver.py` | RegistryResolver — resolve capability → kernel → binding → adapter | `RegistryResolver` |
| `capability_spine.py` | CapabilitySpine — intent → capability mapping | `CapabilitySpine` |
| `assertions.py` | CI assertions for registry integrity | `assert_all_kernels_have_impl()` |

---

## 5. Layer 3 — Execution Engine

**Location**: `engine/execution/`

**Dependencies**: `engine/registry/`, `engine/reliability/`, `shared/`

**Rule**: Engine creates plans and executes them. It does NOT make API calls directly — all calls go through adapters via the registry.

| File | Purpose | Key Exports |
|------|---------|-------------|
| `engine.py` | ExecutionEngine — orchestrates plan execution | `ExecutionEngine` |
| `plan.py` | Plan, Step, Layer dataclasses | `Plan`, `Step`, `Layer` |
| `planner/fast.py` | FastPlanner — single step, no LLM | `FastPlanner` |
| `planner/workflow.py` | WorkflowPlanner — DAG, no LLM | `WorkflowPlanner` |
| `planner/agentic.py` | AgenticPlanner — LLM-guided loop | `AgenticPlanner` |
| `retry.py` | RetryPolicy — mutation-aware retry decisions | `RetryPolicy` |
| `consolidation.py` | Step result consolidation | `consolidate()` |
| `checkpoint.py` | CheckpointManager — save/resume execution | `CheckpointManager` |
| `dead_letter.py` | DeadLetterStore — permanent failure handling | `DeadLetterStore` |
| `state.py` | StepState enum and transitions | `StepState` |

---

## 6. Layer 4 — Control Plane

**Location**: `engine/control_plane/`

**Dependencies**: `engine/execution/`, `engine/registry/`, `engine/reliability/`, `logic/`, `shared/`

**Rule**: Control plane processes every request through 15 stages. It does NOT make API calls.

| File | Purpose | Key Exports |
|------|---------|-------------|
| `pipeline.py` | Pipeline orchestrator — runs all 15 stages | `AgentControlPlane` |
| `entry.py` | S0: Entry — receive message, create ExecutionContext | `EntryStage` |
| `normalize.py` | S1: Normalize — clean text, extract entities, sanitize | `NormalizeStage` |
| `intent.py` | S2: IntentAnalyzer — **1 unconditional LLM call** | `IntentAnalyzer` |
| `capability.py` | S3: CapabilityDiscovery — match intent to capabilities | `CapabilityDiscovery` |
| `graph.py` | S4: GraphClassifier — determine task complexity | `GraphClassifier` |
| `provider_resolve.py` | S5: ProviderResolver — resolve providers | `ProviderResolver` |
| `task_profile.py` | S6: TaskProfileBuilder — build task characterization | `TaskProfileBuilder` |
| `routing.py` | S7: PathRouter — route to FAST/WORKFLOW/AGENTIC/CLARIFY/DENY | `PathRouter` |
| `safety.py` | S8: SafetyGate — 8 authorization checks | `SafetyGate` |
| `plan_validate.py` | S9: PlanValidator — validate plan structure | `PlanValidator` |
| `confirmation.py` | S10: ConfirmationManager — D/IRREVERSIBLE approval | `ConfirmationManager` |
| `authorizer.py` | CapabilityAuthorizer — deterministic, NO LLM | `CapabilityAuthorizer` |
| `response.py` | S15: ResponseFormatter — build Envelope, format for Claude Code | `ResponseFormatter` |

---

## 7. Layer 5 — Interface

**Location**: `servers/`

**Dependencies**: `engine/control_plane/`, `shared/`

**Rule**: Interface receives messages and formats responses. No business logic.

| File | Purpose | Key Exports |
|------|---------|-------------|
| `telegram_bot.py` | Claude Code bot server | `Claude CodeBot` |
| `webhook_server.py` | Webhook server (future) | `WebhookServer` |

---

## 8. Registry & Code Generation

**Location**: `registry/` and `tools/`

### Single Source of Truth

```
registry/kernel_definitions.yaml    ← EDIT THIS
         │
         ├─► tools/generate_kernel_meta.py  ──► engine/*/kernel_meta.py
         ├─► tools/generate_tools.py        ──► servers/tools/*.py
         └─► tools/generate_migration.py    ──► db/migrations/XXX.sql
```

### Code Generation Commands

```bash
make generate          # Run all generators
make generate-meta     # Generate kernel_meta.py files only
make generate-migration # Generate SQL migration only
make verify-generated  # Verify all generated files have sentinel header
make check-registry    # Verify YAML ↔ DB consistency
make check-adapters    # Verify all adapters have all 8 files
make check-engine-map  # Verify ENGINE_MAP is complete
```

---

## 9. Testing Structure

```
tests/
├── conftest.py                    # Shared fixtures (db, mock_binding, mock_context, mock_llm)
│
├── unit/                          # Tier 1 — Pure logic
│   ├── test_consolidation.py
│   ├── test_retry_policy.py
│   ├── test_retry_backoff.py
│   ├── test_state_transitions.py
│   ├── test_sanitizer.py
│   ├── test_idempotency.py
│   ├── test_budget.py
│   ├── test_circuit_breaker.py
│   ├── test_path_routing.py
│   ├── test_safety_gate.py
│   ├── test_plan_validator.py
│   ├── test_execution_context.py
│   └── test_envelope.py
│
├── contract/                      # Tier 2 — Adapter API contracts
│   ├── conftest.py                # Adapter fixtures
│   ├── test_ghl_public.py
│   ├── test_ghl_workflow.py
│   ├── test_notion.py
│   ├── test_google.py
│   ├── test_airtable.py
│   └── test_adapter_base.py       # Tests EVERY adapter must pass
│
├── integration/                   # Tier 3 — End-to-end pipeline
│   ├── test_full_pipeline.py
│   ├── test_confirm_flow.py
│   ├── test_rollback.py
│   └── test_partial_execution.py
│
├── chaos/                         # Tier 4 — Failure injection
│   ├── test_retry_storm.py
│   ├── test_circuit_breaker_chaos.py
│   ├── test_budget_chaos.py
│   └── test_concurrent.py
│
└── fixtures/                      # Recorded API responses
    ├── ghl_public_live.json
    ├── ghl_workflow_live.json
    ├── notion_live.json
    ├── google_calendar_live.json
    ├── google_sheets_live.json
    └── airtable_live.json
```

---

## 10. Configuration

### Configuration Hierarchy

| Priority | Source | Purpose |
|----------|--------|---------|
| 1 | Environment variables | Secrets, API keys, tokens |
| 2 | `.env` file (gitignored) | Local overrides |
| 3 | `config.yaml` | Default configuration |

### Required Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `ANTHROPIC_API_KEY` | LLM API key | Yes |
| `TELEGRAM_BOT_TOKEN` | Claude Code bot token | Yes |
| `GHL_API_KEY` | GHL Public API key | If GHL enabled |
| `GHL_FIREBASE_KEY` | GHL Workflow Firebase key | If GHL Workflow enabled |
| `NOTION_TOKEN` | Notion integration token | If Notion enabled |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Google service account JSON | If Google enabled |
| `AIRTABLE_TOKEN` | Airtable personal access token | If Airtable enabled |
| `DATABASE_PATH` | SQLite database path | No (default: `data/supr.db`) |
| `LOG_LEVEL` | Logging level | No (default: `INFO`) |

---

## 11. Dependency Rules

### Layer Import Rules (NON-NEGOTIABLE)

```
LAYER 5 (servers/)
    └── imports ──► LAYER 4 (engine/control_plane/)
                        └── imports ──► LAYER 3 (engine/execution/)
                                            └── imports ──► LAYER 2 (engine/registry/)
                                                                    └── imports ──► LAYER 1 (engine/providers/)
                                                                                            └── imports ──► LAYER 0 (shared/)

EVENT SUBSYSTEM (event_gateway/)
    └── imports ──► LAYER 0 (shared/)
    └── routes to ──► LAYER 4 (engine/control_plane/) S0 Entry

RELIABILITY (engine/reliability/)
    └── imports ──► LAYER 0 (shared/)
    └── used by ──► LAYER 1 (engine/providers/) and LAYER 3 (engine/execution/)

MEMORY (memory/)
    └── imports ──► LAYER 0 (shared/)
    └── used by ──► LAYER 4 (engine/control_plane/)

PROCESSOR (processor/)
    └── imports ──► LAYER 0 (shared/)
    └── invoked by ──► LAYER 3 (engine/execution/) via kernel operation binding
```

### Import Rules

| Rule | Description |
|------|-------------|
| Downward only | Higher layers import lower layers. Never reverse. |
| Shared is leaf | Layer 0 imports nothing from the system. Only stdlib. |
| Adapters are leaves | Layer 1 imports Layer 0 only. Nothing above imports Layer 1 directly. |
| Registry is leaf | Layer 2 imports Layer 0 only. Nothing above imports Layer 2 directly. |
| No circular imports | No circular dependencies between modules. |
| Cross-cutting via injection | Reliability, memory, and event gateway are injected, not imported by control plane. |

### Enforcement

```python
# CI check: verify no upward imports
# scripts/check_imports.py
FORBIDDEN_IMPORTS = {
    "engine/control_plane/": ["engine/providers/", "engine/execution/"],
    "engine/execution/": ["engine/providers/"],
    "engine/providers/": ["engine/", "servers/", "logic/"],
    "shared/": ["engine/", "servers/", "logic/", "tests/"],
}
```

---

## 12. Build System

### Makefile Targets

```makefile
.PHONY: generate verify ci test lint format typecheck clean

# Code generation
generate: generate-meta generate-tools generate-migrations
	@echo "All generated code is up to date."

generate-meta:
	@python -m tools.generate_kernel_meta

generate-migrations:
	@python -m tools.generate_migration

verify-generated:
	@python -m tools.verify_generated

# Verification
verify: check-registry check-adapters check-engine-map verify-generated
	@echo "All verification checks passed."

check-registry:
	@python -m tools.check_registry

check-adapters:
	@python -m tools.check_adapters

check-engine-map:
	@python -m tools.check_engine-map

# Code quality
lint:
	@ruff check engine/ logic/ servers/ shared/ event_gateway/ memory/ processor/

format:
	@ruff format engine/ logic/ servers/ shared/ event_gateway/ memory/ processor/

typecheck:
	@mypy --strict engine/ logic/ servers/ shared/ event_gateway/ memory/ processor/

# Security
scan-secrets:
	@python -m tools.scan_secrets

# Tests (by tier)
test-unit:
	@pytest tests/unit/ -v

test-contract:
	@pytest tests/contract/ -v

test-integration:
	@pytest tests/integration/ -v

test-chaos:
	@pytest tests/chaos/ -v

test-architecture:
	@pytest tests/architecture/ -v

test-all: test-unit test-contract test-integration test-chaos test-architecture
	@echo "All test tiers passed."

# Full CI gate
ci: lint typecheck verify scan-secrets test-all
	@echo "CI checks passed."

# Database
db-migrate:
	@python -m tools.run_migrations

db-seed:
	@python -m tools.seed_database

db-backup:
	@cp data/supr.db data/supr.db.backup.$(shell date +%Y%m%d)

# Cleanup
clean:
	@find . -type d -name __pycache__ -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@rm -rf .pytest_cache .mypy_cache htmlcov
```

---

## 13. Wave Engineering Discipline

> **Purpose**: Every implementation wave follows a repeatable 8-step process. This prevents "build → test" shortcuts that create technical debt and architectural drift.

### The 8-Step Wave Lifecycle

```
1. DEFINE          What are we building and why?
2. ASSIGN OWNER    Who owns this logic? (check Architecture Ownership Matrix)
3. DESIGN CONTRACT What are the inputs, outputs, errors, and side effects?
4. IMPLEMENT ONCE  Write it once in the canonical location
5. TEST            Unit, contract, boundary, property-based
6. OBSERVE/DEBUG   Trace events, reconstruction, root-cause analysis
7. FAILURE+SECURITY Chaos tests, negative tests, security tests, concurrency tests
8. CERTIFY+FREEZE  All gates pass, version frozen, ready for next wave
```

**Rule**: Do not start coding a wave until steps 1–3 are complete. Every component has a completed component card before implementation begins.

### Definition of Ready

A component cannot enter implementation until ALL of these are true:

```text
□ Owner identified (Architecture Ownership Matrix)
□ Canonical location identified (Module Ownership Matrix)
□ Existing implementation searched (prove it doesn't already exist)
□ Dependencies identified
□ Contract defined (inputs, outputs, error states)
□ State transitions defined (if stateful)
□ Security boundary defined (what can this access?)
□ Trace events defined (what does this emit?)
□ Test strategy defined (unit, contract, negative, security, concurrency)
□ Certification criteria defined (E0–E4 evidence)
□ Component card completed
□ Definition of Done agreed
```

**Rule**: If any box is unchecked, implementation does not begin. This is a CI gate.

### Wave Gate (Final Certification)

Every wave ends with this exact progression:

```
                    IMPLEMENTATION
                          ↓
                 UNIT TESTS PASS
                          ↓
                CONTRACT TESTS PASS
                          ↓
              INTEGRATION TESTS PASS
                          ↓
              NEGATIVE TESTS PASS
                          ↓
              FAILURE TESTS PASS
                          ↓
              SECURITY TESTS PASS
                          ↓
           TENANT-ISOLATION TESTS PASS
                          ↓
             CONCURRENCY TESTS PASS
                          ↓
            OBSERVABILITY VERIFIED
                          ↓
          ARCHITECTURE INVARIANTS PASS
                          ↓
            PERFORMANCE CONTRACT PASS
                          ↓
              CERTIFICATION EVIDENCE
                          ↓
                    CERTIFIED
                          ↓
                   VERSION FROZEN
```

**Rule**: No wave is complete until ALL gates pass. Partial certification is not certification.

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

## 14. New Subsystem Locations

These subsystems are referenced in the architecture but do not have locations in the current blueprint.

| Subsystem | Location | Purpose |
|-----------|----------|---------|
| Runtime Adapters | `engine/runtimes/` | Worker → Runtime Contract → Runtime Adapter → Actual Runtime |
| Event Gateway | `event_gateway/` | Webhook/API/Event → Authenticate → Normalize → Deduplicate → Correlate → S0 |
| Processor Runtime | `processor/` | Sandboxed computation (Python, SQL, WASM, Visual) |
| Verification Layer | `engine/control_plane/verification.py` | S13 layered verification (schema → deterministic → provider_state → semantic → business_rule → human) |
| Execution Ledger | `engine/control_plane/ledger.py` | Append-only execution events, forensic reconstruction |
| Memory | `memory/` | L0-L6 memory tiers, consolidation, decay, write barrier |
| Worker Identity | `engine/execution/worker/` | WorkerIdentity, WorkerVersion, WorkerDeployment, WorkerSubscription |
| A2A Messaging | `engine/execution/a2a/` | Inter-Worker communication, message bus, handoffs |
| Admission Control | `engine/control_plane/admission.py` | S12 admission gates before worker selection |
| Reconciliation | `engine/control_plane/reconciliation.py` | UNKNOWN state resolution, probe management |

---

*End of Components Blueprint.*

### Makefile Targets

```makefile
.PHONY: generate verify test lint clean

# Code generation
generate: generate-meta generate-migration
	@echo "All generators complete."

generate-meta:
	@python -m tools.generate_kernel_meta

generate-migration:
	@python -m tools.generate_migration

# Verification
verify: verify-generated check-registry check-adapters check-engine-map
	@echo "All verification checks passed."

verify-generated:
	@python -m tools.verify_generated

check-registry:
	@python -m tools.check_registry

check-adapters:
	@python -m tools.check_adapter_completeness

check-engine-map:
	@python -m tools.check_engine_map

# Testing
test: test-unit test-contract
	@echo "All tests passed."

test-unit:
	@pytest tests/unit/ -v

test-contract:
	@pytest tests/contract/ -v

test-integration:
	@pytest tests/integration/ -v

test-chaos:
	@pytest tests/chaos/ -v

test-all: test-unit test-contract test-integration test-chaos
	@echo "All test tiers passed."

# Code quality
lint:
	@ruff check engine/ logic/ servers/ shared/ tests/

format:
	@ruff format engine/ logic/ servers/ shared/ tests/

typecheck:
	@mypy --strict engine/ logic/ servers/ shared/

# CI equivalent
ci: lint typecheck test verify
	@echo "CI checks passed."

# Database
db-migrate:
	@python -m tools.run_migrations

db-seed:
	@python -m tools.seed_database

db-backup:
	@cp data/supr.db data/supr.db.backup.$(shell date +%Y%m%d)

# Cleanup
clean:
	@find . -type d -name __pycache__ -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@rm -rf .pytest_cache .mypy_cache htmlcov
```

---

*End of Components Blueprint.*
