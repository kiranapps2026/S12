# SuprAgents — Final Architecture Document

**Version**: 4.5.2 | **Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY
**4.4.0 (2026-09-28)**: absorbs the decisions of the later documents (WORKER_LIFECYCLE_VERIFICATION_ADMISSION, SUPERSESSION_AWARE_BLOCKER_REGISTER, XS-1) and the S12–S15 gate v9 rulings, so no document contradicts this one (I-015). Each changed passage carries a `S12–S15 gate v9 repair` marker; the full list is gate C38.
**4.5.2 (2026-09-29, ADR-14 DECIDED)**: the vector backend is pgvector in PostgreSQL (§20, §21, §29, §37); §36 replaces the scope-less synchronous `MemoryBackend` with the scoped async interface of ADR-14 (register MR-1, MR-2, MR-7). Memory remains a post-S15 phase.
**4.5.1 (2026-09-29, audit round 2)**: §26 `workers` DDL uses `TEXT` keys and shows the management columns; §50 acceptance gate and harness cover I-001…I-029 and a note maps the four invariant numbering schemes; §51 row 16 follows the revised gate C39 (pause at S0.1 by S0–S11 ruling R-P; no per-step pause or quota check).
**4.5.0 (2026-09-29)**: worker-management propagation from `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md`, per the owner-confirmed rulings RD-1…RD-18 in `WORKER_MGMT_SPEC_REVIEW.md` Part E and gate v10 C39–C41. Section numbering cleaned up (RD-16): the orphaned duplicate sections are renumbered §37b, §37c, §37d, §50 and §51; every number cited by another document (§38 Runtime Contract, §39, §40, §41 Event Correlation, §43, §45, §46) is unchanged. Each changed passage carries a `Worker-management repair (RD-n)` marker.
**Date**: 2026-09-26 | **Source**: `rebuild/` design documents + 10-repo gap analysis + P0+P1 audit
**Purpose**: Single, authoritative architecture document that absorbs best patterns from 10 studied repositories, resolves all known conflicts, and serves as the single source of truth for implementation.

---

## Table of Contents

1. [System Identity](#1-system-identity)
2. [What This System Is and Is Not](#2-what-this-system-is-and-is-not)
3. [Architectural Principles](#3-architectural-principles)
4. [Certification Lifecycle — Build to Production](#4-certification-lifecycle--build-to-production)
5. [Evidence Maturity — E0 to E4](#5-evidence-maturity--e0-to-e4)
6. [Overall Architecture — 7 Layers + Execution Kernel](#6-overall-architecture--7-layers--execution-kernel)
6a. [Event Gateway & External Event Routing](#6a-event-gateway--external-event-routing)
7. [Three-Plane Model](#7-three-plane-model)
8. [Request Lifecycle — End-to-End Flow](#8-request-lifecycle--end-to-end-flow)
9. [Dependency DAG](#9-dependency-dag)
10. [Layer Communication Rules](#10-layer-communication-rules)
11. [The 15-Stage Pipeline](#11-the-15-stage-pipeline)
12. [Durable Execution Kernel](#12-durable-execution-kernel)
13. [Execution Manifest](#13-execution-manifest)
14. [Capability Model — The Contract Layer](#14-capability-model--the-contract-layer)
15. [Execution Engine — The Worker Runtime](#15-execution-engine--the-worker-runtime)
16. [Registry — The Single Source of Truth](#16-registry--the-single-source-of-truth)
17. [Reliability Layer — Guards, Breakers, Budgets](#17-reliability-layer--guards-breakers-budgets)
18. [Safety Model — Cordon Points & Authorization](#18-safety-model--cordon-points--authorization)
19. [Error Handling Philosophy](#19-error-handling-philosophy)
20. [Technology Stack](#20-technology-stack)
21. [Memory Architecture](#21-memory-architecture)
22. [Scheduler](#22-scheduler)
23. [Multi-Agent Communication](#23-multi-agent-communication)
24. [Human-in-the-Loop](#24-human-in-the-loop)
25. [Security Model](#25-security-model)
26. [Identity & Tenancy](#26-identity--tenancy)
27. [Observability & Tracing](#27-observability--tracing)
28. [Validation & Testing](#28-validation--testing)
29. [Key Decisions & Rationale](#29-key-decisions--rationale)
30. [Architectural Evolution Path](#30-architectural-evolution-path)
31. [Implementation Roadmap](#31-implementation-roadmap)
32. [Definition of Done](#32-definition-of-done)
33. [Worker Capacity & Scale](#33-worker-capacity--scale--10000-worker-contract)
34. [Terminology](#34-terminology)
35. [No Silent Success](#35-no-silent-success)
36. [Pluggable Memory Backends](#36-pluggable-memory-backends)
37. [PostgreSQL Not Message Bus](#37-postgresql-not-message-bus)
37a. [Adaptability Principles](#37a-adaptability-principles)
37b. [Execution Manifest as Frozen Artifact](#37b-execution-manifest-as-frozen-artifact)
37c. [Conflict Resolution Log](#37c-conflict-resolution-log)
37d. [Patterns Adopted from Studied Repos](#37d-patterns-adopted-from-studied-repos)
38. [Runtime Contract](#38-runtime-contract)
39. [Immutable Intent Specification](#39-immutable-intent-specification)
40. [Execution Ledger](#40-execution-ledger)
41. [Event Correlation and Aggregation](#41-event-correlation-and-aggregation)
42. [Sandboxed Processor Runtime](#42-sandboxed-processor-runtime)
43. [Progressive Verification](#43-progressive-verification)
44. [Explicit Acceptance Criteria](#44-explicit-acceptance-criteria)
45. [Bounded Autonomous Loops](#45-bounded-autonomous-loops)
46. [Runtime/Model Routing](#46-runtimemodel-routing)
47. [Event Replay and Recovery](#47-event-replay-and-recovery)
48. [Capability/Schema Evolution](#48-capabilityschema-evolution)
49. [Formal Architecture Compliance Testing](#49-formal-architecture-compliance-testing)
50. [Architecture Invariants](#50-architecture-invariants)
51. [Future Worker Platform Compatibility — Architecture Extension Points](#51-future-worker-platform-compatibility--architecture-extension-points)

> **Worker-management repair (RD-16):** this table of contents was rebuilt to match the body. The former entries "38. Conflict Resolution Log", "39. Patterns Adopted", "40. Architecture Invariants", "41. Future Worker Platform Compatibility" and "42. Schema and API Compatibility During Rolling Upgrades" did not match the body; the last one had no section at all (recorded as a documentation gap; rolling-upgrade compatibility is covered by §48).

## 1. System Identity

### Name
SuprAgents — The Durable Execution Kernel for AI Workers

### Tagline
"Thousands of AI workers. One execution kernel. Safe by default."

### What This Document Supersedes
This document supersedes all prior architecture documents in `rebuild/`. It resolves all identified conflicts, closes all documented gaps, and serves as the single source of truth for implementation.

### Document Lineage
- **Source**: `rebuild/MASTER_ARCHITECTURE_FINAL.md` v3.0.0 (base)
- **Conflicts resolved**: 20 (see CRITICAL_FIXES.md and ARCHITECTURE_AUDIT.md)
- **Gaps closed**: 18 capabilities from gap analysis
- **Patterns adopted**: 10 proven patterns from 10 repositories

---

## 2. What This System Is and Is Not

### What SuprAgents Is
- A **multi-tenant execution orchestrator** for external APIs
- A **safety layer** between users and destructive operations
- A **durable execution kernel** with checkpoint, resume, lease, and fence
- A **capability-driven platform** where intent maps to immutable bindings
- The **execution infrastructure** for AI workers performing CRM, sales, marketing, finance, research, support, document processing, data analysis, software engineering, scheduling, enterprise operations, browser/computer-use tasks, RAG, multi-step workflows, autonomous agentic tasks, and human-in-the-loop operations

### What SuprAgents Is NOT
- NOT a chatbot framework
- NOT a voice-agent product (voice is one interface channel among many)
- NOT an API wrapper library
- NOT a workflow automation tool like Zapier
- NOT a cron/scheduler
- NOT dependent on any specific LLM provider
- NOT a global knowledge base or vector store (those are separate systems)

---

## 3. Architectural Principles

| # | Principle | Implementation |
|---|-----------|----------------|
| 1 | **Workers are first-class citizens** | Each worker has identity, lifecycle, memory, and execution context |
| 2 | **Execution is durable** | Checkpoint, resume, lease, fence for every operation |
| 3 | **Safety is deterministic** | Authorization never delegates to LLM; all safety checks are pure logic |
| 4 | **Tenancy is non-negotiable** | RLS at database level, isolation at every layer |
| 5 | **Model independence** | Adapters abstract providers; workers don't care which model runs them |
| 6 | **Progressive autonomy** | Workers gain trust through performance, not configuration |
| 7 | **Capabilities are contracts** | Intent maps to capabilities, capabilities map to immutable bindings |
| 8 | **Verification is mandatory** | Post-execution outcome validation before state commit |
| 9 | **Fail-closed by default** | When in doubt, deny; never guess |
| 10 | **Observability is built-in** | Every execution has a trace_id; every action is auditable |
| 11 | **Event-driven activation is first-class** | External events enter through S0 via the Event Gateway. No parallel execution path exists — event-driven executions follow the identical S1–S15 pipeline. See EVENT_GATEWAY_AND_ROUTER.md |
| 12 | **Execution contracts are runtime-independent** | Workers operate against stable contracts. New runtimes, protocols, and adapters integrate through extension points without modifying the kernel. See ADAPTABILITY_PRINCIPLES.md |

---

## 4. Certification Lifecycle — Build to Production

### Canonical Promotion Pipeline

Every component, adapter, capability, and policy follows one unified lifecycle:

```text
DESIGNED
   ↓
BUILT
   ↓
CONTRACT_VALIDATED
   ↓
TESTED
   ↓
FAILURE_TESTED
   ↓
CERTIFIED
   ↓
PRODUCTION_ENABLED
   ↓
SUSPENDED / REVOKED
```

### Transition Evidence Requirements

| From | To | Required Evidence |
|------|----|-------------------|
| DESIGNED | BUILT | Code review passed, compiles, imports clean |
| BUILT | CONTRACT_VALIDATED | Contract tests pass (serialization round-trip) |
| CONTRACT_VALIDATED | TESTED | Unit + integration tests pass |
| TESTED | FAILURE_TESTED | Chaos/failure/load tests pass |
| FAILURE_TESTED | CERTIFIED | Security review + load test passed |
| CERTIFIED | PRODUCTION_ENABLED | Staging validation passed |
| PRODUCTION_ENABLED | SUSPENDED | Critical invariant failed |
| SUSPENDED | REVOKED | Security incident / policy change |

### Certification Expiration

Certification is not permanent. It expires when:

- Provider API version changes
- Adapter code changes
- Policy rule changes
- Capability definition changes
- 90 days pass without re-verification

**Expiration flow:**

```text
CERTIFIED
    ↓ [API change / adapter change / policy change / 90 days]
CERTIFICATION_EXPIRED
    ↓
RE-VERIFY
    ↓
CERTIFIED
```

```text
PRODUCTION_ENABLED
    ↓ [critical invariant fails]
SUSPENDED
    ↓ [incident resolved]
CERTIFIED (re-verify)
    ↓
PRODUCTION_ENABLED
```

**Validation test**: `test_lifecycle_transitions()` — verifies every transition has defined evidence.

---

## 5. Evidence Maturity — E0 to E4

The study defines E0–E4 evidence maturity. This architecture uses that framework to attach evidence requirements to every architectural component.

| Level | Name | Evidence Required |
|-------|------|-------------------|
| **E0** | Designed | Document exists, reviewed, no open contradictions |
| **E1** | Built | Code implemented, compiles, imports clean |
| **E2** | Tested | Automated tests pass (unit + contract + integration) |
| **E3** | Failure-Tested | Chaos/failure/load tests pass |
| **E4** | Production-Evidenced | Telemetry proves durability in production |

**Rule**: Implementation of a dependent component cannot begin until its dependencies reach at least E1.

### Evidence Matrix

| Component | Design (E0) | Build (E1) | Test (E2) | Failure Test (E3) | Production (E4) |
|-----------|-------------|------------|-----------|-------------------|-----------------|
| Worker lifecycle | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Budget reservation | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| GHL adapter | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| RLS policies | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Circuit breaker | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Scheduler | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| MemoryWriteBarrier | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Lease/fencing | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| ExecutionManifest | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Outcome state machine | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Worker identity & leasing | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Budget state machine | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Execution kernel (state machine) | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| UNKNOWN/PROBE/CONFIRMED flow | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Dead Letter Store | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Reconciliation logic | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| ConfirmationToken | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| A2A messaging (12 types) | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Execution strategies (7 types) | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| State transition validator | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Partial success consolidation | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Tenant fairness | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Idempotency ledger | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |

**Rule**: No component is "done" until all applicable E levels are checked.

**Validation test**: `test_evidence_matrix_complete()` — verifies every component has evidence levels defined.

---

## 6. Overall Architecture — 7 Layers + Execution Kernel

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — Interface Layer                                              │
│  Claude CodeBot, MessageParser, ResponseFormatter, Voice Channel, API   │
│  "How users and workers talk to the system"                              │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 4 — Control Plane                                                │
│  IntentAnalyzer → CapabilityDiscovery → GraphClassifier                 │
│  → ProviderResolver → TaskProfileBuilder → PathRouter                   │
│  → SafetyGate → PlanValidator → ConfirmationManager                     │
│  → ResponseFormatter                                                     │
│  "What does the user want, is it safe?"                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 3 — Execution Engine                                             │
│  FastPlanner, WorkflowPlanner, AgenticPlanner                            │
│  StepExecutor, Consolidation, CheckpointManager, DeadLetterStore         │
│  "How to execute the plan"                                               │
├─────────────────────────────────────────────────────────────────────────┤
│  EXECUTION KERNEL — Durable Execution Spine                              │
│  Scheduler → Worker Pool → Leasing → Fencing → Checkpoint → Resume      │
│  "How to execute durably at scale"                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 2 — Capability Registry                                          │
│  CapabilityRegistry, RegistryResolver, BindingRow                        │
│  "What capabilities exist and how to bind them"                          │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 1 — Provider Adapters                                            │
│  GHLPublicAdapter, GHLWorkflowAdapter, NotionAdapter,                   │
│  GoogleWorkspaceAdapter, AirtableAdapter                                │
│  "How to talk to external APIs"                                          │
├─────────────────────────────────────────────────────────────────────────┤
│  LAYER 0 — Shared Foundation                                            │
│  Database, Config, Events, Envelope, CircuitBreaker,                    │
│  Identity, Isolation, Undo, Confirm, Cache, Sanitizer                    │
│  "Pure utilities — no dependencies on higher layers"                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Event Gateway (Control Plane Ingress)

The Event Gateway sits between the Interface Layer and the Control Plane. It is the single ingress point for all external events (webhooks, schedules, MCP, API).

```
Layer 5 (Interface)
    ↓
Layer 0 — Event Gateway ← Single ingress for all external events
    ↓
Layer 4 (Control Plane) — S0 Entry receives EventEnvelope
    ↓
Layer 3 → Layer 2 → Layer 1 (unchanged)
```

The Event Gateway authenticates, validates, deduplicates, and normalizes events into `EventEnvelope` objects. It does NOT execute business logic, select providers, or call LLMs. After creating an `EventEnvelope`, execution enters S0 and follows the identical S1–S15 pipeline.

**Contracts**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md), [ADAPTABILITY_PRINCIPLES.md](ADAPTABILITY_PRINCIPLES.md) §1, §3, §8.

### Layer Communication Rules

| Rule | Description |
|------|-------------|
| **Downward only** | Higher layers import lower layers. Layer 4 imports Layer 3. Never reverse. |
| **Shared is leaf** | Layer 0 imports nothing from the system. Only stdlib. |
| **Adapters are leaves** | Layer 1 imports Layer 0. Nothing above imports Layer 1 directly — all calls go through Layer 2 → Layer 1. |
| **Registry is leaf** | Layer 2 imports Layer 0. Nothing above imports Layer 2 directly — all calls go through Layer 3 → Layer 2. |
| **Execution Kernel is independent** | The kernel can be reached from Layer 3 and Layer 4. It does not import from either. |
| **Interface is leaf for data** | Layer 5 imports Layer 0. It never imports Layers 1-4 directly. |

---

## 6a. Event Gateway & External Event Routing

The Event Gateway is the single ingress point for all external events. It sits between Layer 5 (Interface) and Layer 4 (Control Plane).

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  EXTERNAL EVENT SOURCES                                      │
│  Webhooks (GHL, Notion, Google, Airtable)                    │
│  Cron schedules                                              │
│  MCP (Model Context Protocol)                                │
│  REST API calls                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / WebSocket / gRPC
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  EVENT GATEWAY (L0 — EventRouter, EventCorrelator)           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Auth        │→│ Validate    │→│ Deduplicate &        │  │
│  │ (HMAC/JWT)  │  │ (schema)    │  │ Normalize            │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  EventEnvelope (immutable)                               ││
│  │  { event_id, correlation_id, source, type,              ││
│  │    payload_ref, tenant_id, timestamp, metadata }         ││
│  └─────────────────────────────────────────────────────────┘│
│                           │                                  │
│                           ▼                                  │
│                  S0 Entry (activation_mode = "event_driven")  │
└───────────────────────────────────────────────────────────��─┘
```

### EventEnvelope Contract

EventEnvelope is the immutable wrapper for all externally-triggered events. It is the inbound counterpart to OutboxEvent.

```python
@dataclass(frozen=True)
class EventEnvelope:
    event_id: str                    # UUID v4
    correlation_id: str              # Maps to trace_id at S0
    source: str                      # "ghl_webhook" | "notion_webhook" | "cron" | "mcp" | "api"
    type: str                        # Event type enum
    payload_ref: str                 # Reference to payload (S3 store)
    payload_checksum: str            # SHA-256 for integrity
    tenant_id: str                   # From gateway auth, NEVER from payload
    workspace_id: str                # From gateway auth
    timestamp: str                   # ISO 8601 UTC
    metadata: dict                   # Routing hints, priority, retry count
```

**CRITICAL**: `tenant_id` and `workspace_id` come from the Event Gateway authentication context (HMAC credential → connection → tenant lookup). They are NEVER extracted from the event payload.

### Event Types

| Type | Description | Example Sources |
|------|-------------|-----------------|
| `workflow.completed` | A workflow step finished | GHL webhook |
| `contact.created` | New contact created | GHL webhook |
| `note.added` | Note added to record | Notion webhook |
| `calendar.event` | Calendar event triggered | Google Calendar |
| `record.updated` | Record state changed | Airtable webhook |
| `cron.trigger` | Scheduled trigger | Internal cron |
| `mcp.tool_result` | MCP tool returned result | MCP server |
| `system.alert` | System-generated event | Monitoring |

### Subscription Model (Worker Declares Interest)

Workers declare which event types can activate them via subscriptions. This is the event-driven equivalent of "I can do X" for human requests.

```python
@dataclass(frozen=True)
class WorkerSubscription:
    subscription_id: str             # UUID v4
    worker_id: str                   # Which worker
    event_types: list[str]           # ["workflow.completed", "contact.created"]
    source_systems: list[str]        # ["ghl", "notion", "google"]
    filter_expression: str | None    # JSONPath / JMESPath filter
    priority: int                    # Lower = higher priority
    is_active: bool                  # Subscription can be paused
    matched_count: int               # How many events matched
    last_matched_at: str | None      # Last match timestamp
```

Subscriptions are stored in `event_subscriptions` table and are durable (survive restarts).

### Event Routing

1. Event arrives at Event Gateway
2. Gateway authenticates → resolves tenant_id from credential
3. Gateway validates event schema against `EventEnvelope` contract
4. Gateway deduplicates (idempotency_key, nonce, sequence)
5. Gateway normalizes into `EventEnvelope`
6. Gateway looks up matching subscriptions in `event_subscriptions`
7. For each matching subscription: creates S0 execution with `activation_mode = "event_driven"`
8. S0 creates `ExecutionContext` from `EventEnvelope` → follows identical S1–S15 pipeline

### Event Correlation

Multiple events may need to be correlated before triggering execution (e.g., "contact.created" + "deal.updated" → trigger workflow).

```python
class EventCorrelator:
    """Correlates events within a time window before routing."""

    def correlate(self, envelope: EventEnvelope, window_seconds: int) -> list[EventEnvelope]:
        # Look up pending events for same tenant/workspace within window
        # Apply correlation rules
        # Return correlated set or [envelope] if no correlation needed
```

### Circuit Breaker Integration

The Event Gateway integrates with the existing circuit breaker (RELIABILITY.md §2):

- If the Execution Engine is overloaded → events queue in `event_log` with status `QUEUED`
- If a specific worker's adapter is down → events for that worker are deferred
- Circuit breaker state persists in `circuit_breaker_states` table

**See**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) for complete Event Gateway design. [ADAPTABILITY_PRINCIPLES.md](ADAPTABILITY_PRINCIPLES.md) §3 for event-sourced execution design.


---

---

## 7. Three-Plane Model

```
CONTROL PLANE (S0-S11)
Decides what to do, authorizes, plans, confirms.
Output: Frozen Execution Manifest.
Never modifies Execution Manifest after S11.

EXECUTION PLANE (S12)
Performs the plan with reliability guard.
Output: Step results + outcome.
Never modifies plan after S9.

VERIFICATION PLANE (S13-S14)
Establishes truth about what actually happened.
Output: Verified outcome.
Never modifies execution results after S13.

RESPONSE PLANE (S15)
Formats execution outcomes for the user.
Output: Claude Code message (ok, partial, error, clarify, confirm).
Never mutates execution state.
```

**Rule**: No cross-plane mutations. Control plane cannot modify Execution Manifest after S11. Execution plane cannot modify plan after S9. Verification plane cannot modify execution results after S13.

**Validation test**: `test_plane_boundaries()` — verifies no cross-plane mutations.

### Event-Driven Request Lifecycle

```
External Event (webhook, schedule, MCP, API)
    │
    ▼
Event Gateway (authenticate, validate, deduplicate, normalize)
    │
    ▼
EventEnvelope (immutable)
    │
    ▼
S0 Entry (activation_mode = "event_driven")
    │
    ▼
S1 → S2 → ... → S15 (IDENTICAL to human-driven path)
```

Events are a fifth activation mode alongside human request, schedule, API, and internal trigger. The only difference at S0 is the source of the input: an `EventEnvelope` instead of a raw message. All downstream processing is identical.

**Contracts**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) §2, §12. [ADAPTABILITY_PRINCIPLES.md](ADAPTABILITY_PRINCIPLES.md) §3.

---

## 8. Request Lifecycle — End-to-End Flow

### Dependency Direction
```
Layer 5 (Interface)
    ↓ imports
Layer 4 (Control Plane)
    ↓ imports
Layer 3 (Execution Engine)
    ↓ imports
Layer 2 (Registry) + Layer 1 (Adapters) + Layer 0 (Shared)
```

### Prohibited Imports
- Layer 0 cannot import any project module
- Layer 1 cannot import Layers 2-5
- Layer 2 cannot import Layers 3-5
- Layer 3 cannot import Layers 4-5
- Layer 4 cannot import Layer 5
- Adapters cannot call other adapters (complete isolation)
- Adapters cannot make authorization decisions (SafetyGate's job)
- Control plane cannot modify ExecutionContext after creation

---

## 9. Dependency DAG

```
Database (schema, RLS, migrations)
   |
   v
Identity (worker, user, tenant)
   |
   v
Data Contracts (frozen dataclasses)
   |
   v
Worker Identity (state machine, lease management)
   |
   v
Lease/Fencing (distributed lock, fence token)
   |
   v
Pipeline S0-S7 (entry through path routing)
   |
   v
Pipeline S8-S11 (safety, planning, confirmation)
   |
   v
Reliability (circuit breaker, retry, budget, timeout)
   |
   v
Adapters (GHL, Notion, Google)
   |
   v
Registry (capability lookup, binding resolution)
   |
   v
Pipeline S12-S15 (execution, verification, response)
   |
   v
A2A Messaging (agent-to-agent communication)
   |
   v
Memory Architecture (L0-L3 persistence)
   |
   v
Scale (worker pools, horizontal scaling)
```

**Rule**: No component can be implemented before all its DAG ancestors are at E1.

**Validation test**: `test_dependency_dag()` — verifies no circular dependencies and all dependencies are met.

---
## 10. Layer Communication Rules

### Purpose
The execution kernel ensures that every operation is traceable, reversible (where possible), and resumable after failure.

### Core Mechanisms

| Mechanism | Purpose | Implementation |
|-----------|---------|----------------|
| **Checkpoint** | Save execution state after each step | Database-backed, atomic |
| **Resume** | Restart from last checkpoint | Deterministic replay |
| **Lease** | Bound a worker's concurrent executions to `workers.capacity`; give one Worker Runtime the right to execute a step | `worker_leases` row with TTL and stored status |
| **Fence** | Prevent a stale owner from writing after it lost the lease | Monotonic token from one database sequence, checked per execution |
| **Scheduler** | Distribute work across worker pool | Priority-aware, fairness-guaranteed |

### Worker State Machine

```
REGISTERED → ACTIVE → DRAINING → DRAINED → TERMINATED
                ↑         │          │
                └─────────┴──────────┘   (drain cancelled / restart)
```

> **S12–S15 gate v9 repair (C38):** The earlier diagram (PENDING, PAUSED, RESUMING) predates WORKER_LIFECYCLE_VERIFICATION_ADMISSION §1. The canonical worker states and transitions are STATE_TRANSITIONS §4.


### Lease Management
- Leases are acquired before execution begins
- Leases are renewed automatically during execution
- Lease expiry ends that execution's ownership; the new owner resolves the in-flight step by probing (S12–S15 gate §13). Worker draining on lease loss belongs to the fleet phase.
- Stale leases are detected and reclaimed by the sweeper

---

## 11. The 15-Stage Pipeline

The pipeline has 16 stages (S0 through S15). S0-S11 form the Control Plane, S12 is the Execution Plane, S13-S14 are the Verification Plane, and S15 is the Response Plane.

```
CONTROL PLANE (S0-S11) — Decides what to do, authorizes, plans, confirms.
  S0   Entry/Parse — Receive request, generate trace_id, create ExecutionContext
       Activation modes: HUMAN (terminal message), SCHEDULE (cron), API (direct call),
       EVENT_DRIVEN (external event via Event Gateway), INTERNAL (system event)
  S1   Normalize — Clean input, resolve references, detect injection
  S2   Intent Analysis — LLM call to understand user intent (task_id generated)
  S3   Capability Discovery — Map intent to system capabilities
  S4   Graph Classification — Determine task complexity (simple/chain/complex)
  S5   Provider Resolution — Select providers, compute effective_risk/effective_mutation
  S6   Task Profile Assembly — Build complete task profile (consumes risk/mutation from S5)
  S7   Path Routing — Select execution strategy (FAST/WORKFLOW/CLARIFY/DENY)
  S8   Safety Gate — Security boundary, budget precheck, mutation safety
  S9   Plan Creation — Build executable plan (execution_id, plan_id generated)
  S10  Confirmation — Human approval for irreversible/high-risk operations
  S11  Plan Validation — Final validation, create frozen ExecutionManifest

EXECUTION PLANE (S12) — Performs the plan with reliability guard.
  S12  Execute with Reliability Guard — Atomic budget reservation, step execution

VERIFICATION PLANE (S13-S14) — Establishes truth about what happened.
  S13  Validate Result — Verify adapter results, run reconciliation
  S14  Dead Letter — Classify failures, handle UNKNOWN outcomes

RESPONSE PLANE (S15) — Formats outcomes for the user.
  S15  Response Formatting — Map execution outcomes to Claude Code responses
```

**Pipeline Invariants**:
1. S5 computes effective_risk and effective_mutation once. All downstream stages (S6-S15) consume these frozen values. No stage after S5 recomputes risk or mutation.
2. Only S12 performs actual budget reservation. S8 performs affordability precheck only. S9 does not reserve budget.
3. S2 is the ONE unconditional LLM call. All other LLM calls are conditional (AGENTIC path only).
4. Every stage returns the next `PipelineState`, writing only its own output through `with_stage_output()`; short-circuits use `StageStatus` (DENY, CLARIFY, ...).

> **S12–S15 gate v9 repair (C38):** The earlier wording ("every stage produces a StageResult") described a contract that the certified S0–S11 implementation removed; `StageResult` is forbidden by the S0–S11 certifier.

5. UNKNOWN outcomes cannot become SUCCESS without verification through S13 PROBE -> CONFIRMED.

**Short-Circuit Paths**:
| Decision | Source | Target | User Sees |
|----------|--------|--------|-----------|
| CLARIFY | S7, S8, S10, S11 | S15 | "Can you tell me more about...?" |
| DENY | S7, S8 | S15 | "I can't do that because..." |
| INVALID | S11 | S15 | "The plan could not be validated." |

### Activation Modes

| Mode | Source | S0 Input | context_snapshot |
|------|--------|----------|-----------------|
| HUMAN | Terminal chat | Raw text | User message text |
| SCHEDULE | Cron trigger | Schedule context | Cron definition |
| API | Direct API call | API payload | Request body |
| EVENT_DRIVEN | External event via Event Gateway | `EventEnvelope` | `payload_ref` |
| INTERNAL | System event | Internal context | Event data |

**Event-driven mode**: The Event Gateway creates an `EventEnvelope` (immutable) and passes it to S0. S0 creates `ExecutionContext` with `activation_mode = "event_driven"`. All downstream stages (S1–S15) are identical regardless of activation mode. `EventEnvelope.event_id` becomes `task_id`. `EventEnvelope.correlation_id` becomes `trace_id`. Tenant identity comes from the Event Gateway authentication context, never from the event payload.

**See**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) §2, §12.

---
## 12. Durable Execution Kernel

The execution kernel guarantees that every execution is traceable, reversible where possible, and resumable from any failure. It connects S11 (freeze manifest), S12 (execute), S13 (validate), and S14 (dead letter) into a single atomic unit.

### State Transition Contract

Every execution is described by three canonical state machines — the run
(`ExecutionStatus`), each step (`StepState`) and each step's budget reservation
(`ReservationState`) — defined in STATE_TRANSITIONS §1–§3 and tabulated, with reason
codes, in S12_S15_EXECUTION_GATE Appendix A. Transitions are atomic — no intermediate
states. Budget is reserved **per step**:

```
reserved → locked → committed   (step verified COMPLETED)
                  → released    (step FAILED, or probe confirms NOT_EXECUTED)
                  (stays locked while the outcome is UNKNOWN; resolved by probe,
                   verification or dead-letter resolution — never by a timer)
```

> **S12–S15 gate v9 repair (C3, C38):** The earlier single per-execution machine (PENDING → RESERVED → COMMITTED/RELEASED/LOCKED) conflicted with the per-step schema (`budget_reservations.step_id`) and with §15 "reserve budget" per step. `ExecutionState` below is a descriptive summary only.


```python
@dataclass(frozen=True)
class ExecutionState:
    execution_id: str
    state: str  # PENDING | RESERVED | COMMITTED | RELEASED | LOCKED
    reservation_id: str | None
    budget_reserved: int
    current_step: int
    total_steps: int
    outcome: str | None  # SUCCESS | FAILURE | PARTIAL | UNKNOWN
    probe_attempts: int
    fence_token: int
    lease_epoch: int
    updated_at: float
```

### Core Mechanisms

| Mechanism | Purpose | Implementation |
|-----------|---------|----------------|
| **Checkpoint** | Save execution state after each step | Database-backed, atomic transaction per step |
| **Resume** | Restart from last checkpoint | Deterministic replay from frozen manifest |
| **Lease** | Prevent concurrent execution of same worker | worker_leases table with fence_token |
| **Fence** | Prevent stale execution after restart | Monotonic fence_token from one sequence; every durable write checks the execution's `execution_ownership.fencing_token` (gate C25) |
| **Scheduler** | Distribute work across worker pool | Priority-aware, tenant-fair, backpressure-controlled |

### Atomic State Transitions

No state transition is partial. Each transition either commits fully or rolls back.

1. **S11 → S12 entry**: the frozen ExecutionManifest and plan are verified and persisted with the run in one admission transaction. No budget is reserved at entry.
2. **S12 step start**: after admission, worker lease and a per-step budget reservation, the step moves PENDING → RUNNING and its reservation RESERVED → LOCKED in one transaction. Side effects happen only after that.
3. **S12 step result**: an adapter result is verified before COMPLETED (§35). An uncertain result moves the step to PENDING_PROBE and opens a reconciliation episode; transient errors are retried while the step stays RUNNING.
4. **S13 reconcile** (code in the S13 package, called from the S12 loop): the probe or verification resolves the episode → CONFIRMED_SUCCESS or CONFIRMED_FAILURE; if still inconclusive after the bounded attempts, the step goes to DEAD_LETTER and its budget stays LOCKED.
5. **S14 dead letter**: records failures and unresolved uncertainty with evidence. A dead letter never re-executes a step; its retry only re-probes or re-verifies (gate D5). Permanent errors and unresolved outcomes escalate to human review.

> **S12–S15 gate v9 repair (C3, C6, C12, D5, C38):** Aligned with the per-step budget, the retry-inside-RUNNING rule and the dead-letter retry modes decided after this document was written.


### MemoryWriteBarrier

All memory writes (L0-L3) pass through MemoryWriteBarrier before persisting. This ensures:
- Writes are ordered relative to execution steps
- Rollback can undo writes from failed steps
- Verification can inspect intermediate state without race conditions

### Scheduler Integration

The scheduler is a first-class subsystem that:
- Dispatches PENDING executions in-process in the single-node phase (PostgreSQL is the claim authority, not a queue — §37; gate C1)
- Selects workers based on capacity, capability_profile, and tenant fairness
- Acquires worker lease with fence_token before assigning execution
- Releases lease on completion or timeout
- Triggers backpressure when system load exceeds threshold

---
## 13. Execution Manifest

The ExecutionManifest is a frozen artifact created at the end of S11 and consumed by S12. It captures the complete decision context at the moment of authorization.

```python
@dataclass(frozen=True)
class ExecutionManifest:
    execution_id: str
    trace_id: str
    plan_id: str
    plan_hash: str
    step_count: int
    capability_version: str
    binding_version: str
    policy_version: str
    risk_policy_version: str
    authorization_version: str
    worker_runtime_version: str
    model_version: str
    total_cost: int
    total_risk: float
    mutations: list[str]
    confirmation_token_id: str | None
    reconciliation_state: str  # NONE | PENDING | COMPLETE
    dead_letter_records: list[str] | None
    created_at: float
```


> **S12–S15 gate v9 repair (C38):** The field list above predates the canonical contract. The canonical ExecutionManifest is DATA_CONTRACTS `ExecutionManifest` (identical to §37b below) plus the certified `auth_result_id`. Runtime values (`reconciliation_state`, dead-letter records, costs) are not manifest fields: the manifest is immutable, and runtime state lives in the execution tables.

### Canonical Ownership: Execution Truth

> **Rule**: ExecutionContext = request identity. ExecutionManifest = complete immutable execution truth.

| Artifact | Owns | Does NOT own |
|----------|------|--------------|
| `ExecutionContext` | Request identity/context (trace_id, tenant_id, user_id, conversation_id) | Provider resolution, plan, authorization result |
| `ExecutionManifest` | Complete immutable execution truth at S11 boundary | Dynamic values, mid-execution state |
| `FrozenBindingIdentity` | Provider/binding/risk/mutation at S5 | Plan steps, authorization, budget |
| `Plan` | Step graph with parameter bindings | Runtime results, provider state |

**Storage**: Frozen at S11 completion; persisted to `execution_manifests` at S12 entry, in the same transaction that creates the run row, byte-identical to the S11 manifest (the table references `execution_runs`, which does not exist at S11). Read-only for S12 and all subsequent stages. Never updated after creation.

---
## 14. Capability Model — The Contract Layer

### Purpose
Capabilities are the contract between user intent and provider execution. They are immutable, versioned, and discoverable.

### Capability Definition

```python
@dataclass(frozen=True)
class CapabilityMetadata:
    id: str                           # Unique capability ID
    name: str                         # Human-readable name
    description: str                  # What this capability does
    mutation: str                     # R | W | D | IRREVERSIBLE
    risk_floor: float                 # Base risk (0.0-1.0)
    risk_rule: float                  # Rule-based risk
    risk_implied: float               # Implied risk from context
    cost: int                         # Budget cost units
    scopes: list[str]                 # Required scopes
    providers: list[str]              # Supported providers
    truth_state: str                  # DRAFT | REVIEW | PRODUCTION_ENABLED | DEPRECATED
    version: str                      # Semver
    schema: dict                      # Input/output schema
```

### Binding Definition

```python
@dataclass(frozen=True)
class BindingRow:
    id: str                           # Binding ID
    capability_id: str                # Linked capability
    provider: str                     # Provider prefix
    engine_module: str                # Python module path
    adapter_class: str                # Adapter class name
    priority: int                     # Selection priority (lower = preferred)
    created_at: float                 # Creation timestamp
    is_active: bool                   # Active flag
```

### Frozen Binding Identity (CRITICAL)

Once S5 completes, the resolved binding is **immutable** for the rest of this execution. S12 receives `FrozenBindingIdentity` and does NOT re-resolve.

### Protocol Independence

Capabilities are not tied to a specific protocol. MCP, browser automation, Python processing, and future protocols implement the `BaseAdapter` interface (PROVIDER_ADAPTERS.md §1). The resolution layer (S5) selects the adapter; the capability contract defines the interface.

New protocols integrate as adapters, not as new execution engines. They follow the same S0–S15 pipeline, the same S8 Safety Gate, the same S13 verification.

**See**: ADAPTABILITY_PRINCIPLES.md §8 for the bidirectional MCP design.

---

## 15. Execution Engine — The Worker Runtime

### Execution Strategies (Selected at S7 Path Routing)

| Strategy | Trigger | Planner | Description |
|----------|---------|---------|-------------|
| **REFLEX** | Single capability, confidence >= 0.95 | FastPlanner | Direct execution, no planning overhead |
| **REACT** | Simple task, sequential reasoning | FastPlanner | Observe-reason-act loop |
| **FAST** | Single capability, confidence >= 0.9 | FastPlanner | Single-step execution |
| **WORKFLOW** | Linear dependency chain | WorkflowPlanner | Sequential multi-step |
| **BATCH** | Multiple independent tasks | WorkflowPlanner | Parallel execution |
| **PLAN_EXECUTE** | Complex task with dependencies | AgenticPlanner | Plan then execute |
| **AGENTIC** | Complex DAG, branching exploration | AgenticPlanner | Branch, verify, converge |
| **HUMAN_ASSISTED** | High-risk or unclear intent | — | Pause for confirmation |
| **EVENT_DRIVEN** | Triggered by external event via Event Gateway | WorkflowPlanner | Reactive execution. Events enter through S0 with activation_mode = "event_driven". |

**M0 Scope**: FAST, WORKFLOW, REFLEX, and EVENT_DRIVEN strategies are active. AGENTIC, BATCH, PLAN_EXECUTE, and HUMAN_ASSISTED are stubbed — they route to CLARIFY.

> **Worker-management repair (RD-12):** large-payload batch processing is the BATCH strategy, not a separate mechanism. When activated (post-S15), S7 selects BATCH and S9 produces N ordinary PlanSteps, one per slice, each with its own `plan_step_id` — so each slice has its own idempotency key (I-021), its own step state machine, probe and recovery path, and §10 consolidation (PARTIAL already exists). No new state machine and no batch table with its own states are added. Until then BATCH stays stubbed (gate v10 C40).

### Planners

| Planner | Path | Use Case |
|---------|------|----------|
| **FastPlanner** | FAST | Single-step, low-risk, no dependencies |
| **WorkflowPlanner** | WORKFLOW | Multi-step, linear or branching dependencies |
| **AgenticPlanner** | AGENTIC | Complex, adaptive planning with LLM (M2+) |

### Step Execution

Each step in a plan is executed by the StepExecutor:

1. Acquire lease for worker
2. Reserve budget atomically
3. Execute via adapter with reliability guard
4. Consolidate result
5. Checkpoint state
6. Release lease

### Consolidation Rules

| Step States | Consolidated Result | Condition |
|-------------|---------------------|-----------|
| All completed | `ok` | Every step returned COMPLETED |
| All failed | `failed` | Every step returned FAILED |
| Mixed (some succeeded, some failed) | `partial` | Only after ALL steps are terminal |
| Any UNKNOWN | `unknown` | Must go through PROBE → CONFIRMED before consolidation |
| All skipped | — | Unreachable: a step is SKIPPED only after a predecessor failed (gate C22), so the "mixed" or "all failed" row applies |
| Partial completion | `partial` | Some steps completed, some failed, all terminal |

**Rules**:
1. UNKNOWN is NEVER consolidated into partial or failed. UNKNOWN requires S13 PROBE → CONFIRMED first.
2. Partial is only produced when some steps succeeded AND some failed, AND all steps are terminal.
3. No silent success: if any step is UNKNOWN, the overall result cannot be SUCCESS until verified.

---

## 16. Registry — The Single Source of Truth

### Purpose
The registry is the single source of truth for all capabilities, bindings, and provider mappings.

### Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `kernel_definitions.yaml` | ALL kernel operations defined here | `registry/` |
| `engine_map.yaml` | Provider prefix → module mapping | `registry/` |
| `CapabilityRegistry` | Capability discovery and lookup | Layer 2 |
| `RegistryResolver` | Capability → kernel → binding resolution | Layer 2 |
| `CapabilitySpine` | Intent → capability mapping | Layer 2 |

### Code Generation

Registry files are source-of-truth; code is generated from them:

```bash
tools/generate_kernel_meta.py  # YAML → kernel_meta.py
tools/generate_tools.py        # YAML → servers/tools/*.py
tools/generate_migration.py    # YAML → SQL migration
```

Generated files have sentinel comments for verification:

```python
# === GENERATED FROM kernel_definitions.yaml — DO NOT EDIT ===
# === REGENERATE WITH: python tools/generate_kernel_meta.py ===
```

---

## 17. Reliability Layer — Guards, Breakers, Budgets

### 5-Layer Reliability Guard

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 5 — Dead Letter Store                                    │
│  Permanent failures → record → notify → no retry                │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 4 — Safety Guard                                         │
│  Mutation safety, idempotency, reversibility                    │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 3 — Budget Guard                                         │
│  Atomic reserve/commit/release, budget locks                    │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2 — Retry Guard                                          │
│  Retry policy per mutation type, exponential backoff + jitter   │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 1 — Timeout Guard                                        │
│  Per-step timeout, per-provider timeout, circuit breaker        │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 0 — Circuit Breaker                                      │
│  Per-provider circuit breaker, health monitoring                │
└─────────────────────────────────────────────────────────────────┘
```


> **S12–S15 gate v9 repair (C4, C38):** These are conceptual layers. The runtime guard is implemented as the five named components of RELIABILITY §1/§8 (CircuitBreaker, RetryStormGuard, BudgetTracker, TimeoutManager, Bulkhead). The "Safety Guard" layer here corresponds to the idempotency lookup and mutation-aware retry ceiling applied immediately before each adapter call; the "Dead Letter Store" layer is S14.

### Retry Decision Matrix

| Mutation Type | Retry Safety | 4xx | 5xx | Timeout | Network |
|---------------|--------------|-----|-----|---------|---------|
| R (Read) | safe | No | Yes | Yes | Yes |
| W (Write) | safe | No | Yes | Yes | Yes |
| W | idempotent | No | Yes | Yes | Yes |
| D (Delete) | idempotent | No | Yes | Yes | Yes |
| D | never | No | No | No | No |
| IRREVERSIBLE | any | No | No | No | No |

"Timeout: Yes" means the step may be retried **after** a probe confirms NOT_EXECUTED; a timeout is never blindly retried (§19, gate §9).

### Retry Budget (Per-Step)

Retry count is **per-step**, not per-execution. Each step in a plan has an independent retry budget.

```python
@dataclass(frozen=True)
class RetryBudget:
    step_id: str
    execution_id: str
    max_attempts: int  # Per-step, default 3
    attempts_used: int
    backoff_strategy: str
    circuit_breaker_ref: str
```

**Rule**: A step fails only when its own retry budget is exhausted. Other steps' retries are independent.

### Circuit Breaker States

| State | Meaning | Next State On |
|-------|---------|---------------|
| CLOSED | Normal operation | Failure count ≥ threshold → OPEN |
| OPEN | Failing, reject calls | Timeout elapsed → HALF_OPEN |
| HALF_OPEN | Testing recovery | Success → CLOSED, Failure → OPEN |

---

## 18. Safety Model — Cordon Points & Authorization

### Deterministic Authorization (CRITICAL)

**Authorization is NEVER delegated to the LLM.** The `CapabilityAuthorizer` is pure logic:

```python
class CapabilityAuthorizer:
    def authorize(self, user: User, capability: Capability,
                  resource: Resource) -> AuthResult:
        # Rule 1: Account active?
        if not user.is_active or not user.tenant.is_active:
            return AuthResult.DENY("Account not active")

        # Rule 2: Capability granted?
        if capability.id not in user.granted_capabilities:
            return AuthResult.DENY("Capability not granted")

        # Rule 3: Scope matches?
        if not resource.scope in user.scopes:
            return AuthResult.DENY("Scope mismatch")

        return AuthResult.ALLOW()
```

### Delegation and Impersonation Boundaries (Worker-to-Worker)

**Rule**: Worker B cannot pretend to be Worker A. The `PrincipalChain` preserves the full chain from the original human user through every delegation.

```python
@dataclass(frozen=True)
class PrincipalChain:
    original_principal: str        # Human user or service account that initiated
    delegating_worker: str         # Worker that initiated delegation
    executing_worker: str          # Worker currently executing
    target_connection: str         # Which connection is being used
    created_at: float
```

**Boundaries**:
1. A worker can only delegate using its own `worker_id`.
2. The `PrincipalChain` is immutable after creation at S0.
3. LLM output can never modify the `PrincipalChain`.
4. Every execution carries its full `PrincipalChain` from root user to current worker.
5. Each delegation step is logged with the full `PrincipalChain`.
6. Impersonation without a valid chain is rejected at the authorization layer.

### Mutation Safety Classification

| Mutation | Meaning | Reversibility | Confirmation Required | Retry Allowed |
|----------|---------|---------------|----------------------|---------------|
| R | Read | N/A | No | Yes |
| W | Write | Yes (with undo token) | Conditional | Yes |
| D | Delete | Yes (with undo token) | Yes | Conditional |
| IRREVERSIBLE | Destructive | No | Always | No |

### Confirmation Rules

| Condition | Requires Confirmation |
|-----------|----------------------|
| Any IRREVERSIBLE mutation | YES |
| Any D mutation with cost > 5 | YES |
| Total cost > 20 | YES |
| Total risk > 0.7 | YES |
| Cross-provider (3+ providers) | YES |

---

## 19. Error Handling Philosophy

### Error Hierarchy

```
ExecutionError (base)
├── ValidationError — Input doesn't match schema
├── SafetyError — Authorization failed
├── ProviderError — External API error
│   ├── TimeoutError
│   ├── NetworkError
│   └── RateLimitError
├── BudgetError — Budget exceeded
├── StateError — Invalid state transition
└── SystemError — Internal failure
```

### Error Handling Rules

| Rule | Implementation |
|------|----------------|
| **Fail-closed** | When in doubt, deny — never guess |
| **NEVER raise from adapters** | Always return `KernelResult(status="error", ...)` |
| **UNKNOWN for uncertain outcomes** | Timeout/Network → `status="UNKNOWN"` with `requires_probe=True` |
| **Structured errors** | Every error has type, message, recoverable flag, suggested_action |
| **Probe for UNKNOWN** | Separate probe step determines actual outcome |
| **Dead letter after N retries** | Permanent failures go to dead letter store |

### Probe Pattern (from gap analysis)

When adapter returns `status="UNKNOWN"` (timeout, network error):
1. Record the uncertainty (step → PENDING_PROBE, reconciliation episode opened)
2. Execute the probe to determine the actual outcome
3. If confirmed executed and successful → verify, then mark the step completed
4. If confirmed NOT executed → apply the retry policy (retry within the step's ceiling; never for IRREVERSIBLE or non-idempotent D)
5. If confirmed executed but failed → the step fails (no retry after an uncertainty episode unless NOT_EXECUTED is proven)
6. If probe inconclusive after the bounded attempts → dead letter

> **S12–S15 gate v9 repair (C6, C38):** Step 4 previously read "If confirmed failure → apply retry policy". A probe cannot report the error class, so retrying is limited to the one outcome proven free of side effects.


---

## 20. Technology Stack

### Backend
| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.11+ | Type safety, async/await, ecosystem |
| Framework | FastAPI | Async, OpenAPI, dependency injection |
| Database | PostgreSQL 16+ | ACID, RLS, JSONB, proven at scale |
| Migrations | Alembic | Versioned schema changes |
| ORM | SQLAlchemy 2.0 | Async support, type safety |
| Vector Search | pgvector (PostgreSQL extension) | Tenant isolation by RLS, same transactions and backups as the rest of the data (ADR-14) |
| Cache | Redis | Session cache, rate limiting |
| Queue | In-process dispatch (single node); PostgreSQL is the claim authority; notification channel deferred to the fleet phase | PostgreSQL is not a message bus (§37); gate C1 |
| Observability | OpenTelemetry + Jaeger | Distributed tracing |
| Testing | pytest + httpx | Async support, fixture ecosystem |

### Infrastructure
| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Container | Docker | Consistent deployment |
| Orchestration | Docker Compose (dev), Kubernetes (prod) | Flexibility |
| CI/CD | GitHub Actions | Native integration |
| Secrets | HashiCorp Vault | Centralized secrets management |

---

## 21. Memory Architecture

### Four Memory Layers (Unified Taxonomy)

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — Long-Term Knowledge                               │
│  Domain knowledge, learned preferences, historical patterns  │
│  Persists across worker restarts                              │
│  Curated, summarized, confidence-scored                       │
│  Storage: PostgreSQL (JSONB) + pgvector (vector)             │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2 — Session Memory                                    │
│  Conversation history, decisions made, results obtained      │
│  Persists within a worker session                            │
│  Compacted when session ends                                 │
│  Storage: PostgreSQL (checkpoint store)                      │
├─────────────────────────────────────────────────────────────┤
│  LAYER 1 — Working Memory                                    │
│  Current execution context, intermediate results             │
│  Persists during a single execution                          │
│  Checkpointed at every step                                  │
│  Storage: In-memory (checkpointed)                           │
├─────────────────────────────────────────────────────────────┤
│  LAYER 0 — Episodic Buffer                                   │
│  Immediate context window, attention focus                    │
│  Persists during a single LLM call                           │
│  Scoped to current step/iteration                            │
│  Storage: In-memory (LLM context)                            │
└────────────────────────────────��────────────────────────────┘
```

### Memory Principles

| Principle | Description |
|-----------|-------------|
| **Explicit over implicit** | Every memory entry has a source, timestamp, and confidence score |
| **Ephemeral by default** | Working memory expires; long-term memory is curated |
| **Bounded** | Every memory layer has size limits and TTLs |
| **Isolated** | Memory is partitioned by worker, tenant, and user |
| **Auditable** | Every memory mutation is logged |
| **Reversible** | Memories can be deleted, corrected, or superseded |
| **Bias-aware** | Memory confidence decays over time; stale memories are deprioritized |

### Memory Classification (orthogonal to layers L0–L3)

> **Worker-management repair (RD-14 family; spec F21):** status DEFERRED (post-S15). Classification describes *what kind* of knowledge an entry is; the layer (L0–L3) describes *where and how long* it lives. The two axes are independent.

| Class | What it holds | Typical layer | Example |
|-------|---------------|---------------|---------|
| Historical | What happened (renamed from the spec's "Episodic" to avoid collision with L0 "Episodic Buffer") | L1 → L3 | "On Sep 28, created contact John Doe" |
| Semantic | What the worker knows | L3 | "John Doe is VP of Sales at Acme Corp" |
| Procedural | How to perform something | L2 → L3 | "When qualifying leads, check company size first" |
| Organizational | Informational copy of what the company permits | L3 (tenant-wide) | "This tenant allows CRM writes but not deletions" |
| Execution | What happened during this execution | L1 | "Step 3 returned 247 contacts" |
| Relationship | What is known about a customer or entity | L3 (per entity) | "John prefers email, responds in mornings" |
| Policy | Informational copy of a rule | L3 (read-only) | "Finance transfers require two-person approval" |

**Invariant — memory is never authorization.** No authorization, admission or policy decision reads memory. "Organizational" and "Policy" entries are informational copies for the LLM; the authoritative rules live in policy tables and are evaluated by the kernel (I-007). Every write goes through `MemoryWriteBarrier` (I-014).

### Memory Write Barriers (from Ruflo pattern)

All memory writes go through a write barrier:

```python
class MemoryWriteBarrier:
    """Enforce write rules before any memory mutation."""

    def write(self, memory_entry: MemoryEntry) -> bool:
        # 1. Validate entry schema
        # 2. Check write permissions (tenant isolation)
        # 3. Check memory layer capacity
        # 4. Apply confidence decay to existing entries
        # 5. Log write operation
        # 6. Write atomically
        pass
```

### Memory Quality Scoring

| Score | Meaning | Action |
|-------|---------|--------|
| 0.9-1.0 | High confidence | Use freely |
| 0.7-0.9 | Good confidence | Use with minor weighting |
| 0.5-0.7 | Moderate confidence | Verify before use |
| 0.3-0.5 | Low confidence | Deprioritize |
| 0.0-0.3 | Stale | Expire and remove |

---

## 22. Scheduler

The scheduler assigns work to workers based on capability, load, and tenant fairness.

```python
@dataclass(frozen=True)
class SchedulerState:
    pending: list[ExecutionRequest]
    running: dict[str, ExecutionSlot]
    completed: list[ExecutionResult]
    failed: list[ExecutionResult]
    worker_pool: WorkerPoolState
    next_worker_id: str
```

**Responsibilities**:
1. Assign work to workers based on capability, load, and tenant fairness
2. Enforce per-tenant concurrency limits
3. Implement noisy-neighbor protection
4. Drain workers gracefully
5. Rebalance on worker changes

**Validation test**: `test_scheduler_fairness()` — verifies tenant isolation under load.

---
## 23. Multi-Agent Communication

### A2A Communication Model (from AgentsMesh + CrewMeld patterns)

### Message Types

| Semantic | Purpose | Delivery Guarantee | Persistence | TTL |
|----------|---------|-------------------|-------------|-----|
| **COMMAND** | Direct instruction to worker | At-least-once | Yes | None |
| **EVENT** | State change notification | At-least-once | Yes | 24h |
| **QUERY** | Request for information | At-least-once | No | 5m |
| **RESPONSE** | Answer to a query | Exactly-once | No | 5m |
| **DELEGATION** | Transfer task to another worker | Exactly-once | Yes | None |
| **HANDOFF** | Transfer execution responsibility | Exactly-once | Yes | None |
| **APPROVAL** | Request human authorization | At-least-once | Yes | 1h |
| **CANCELLATION** | Stop in-flight execution | At-least-once | Yes | None |
| **PROGRESS** | Execution progress update | At-least-once | No | 5m |
| **HEARTBEAT** | Liveness signal | At-least-once | No | 2m |
| **RESULT** | Final execution result | At-least-once | Yes | 24h |
| **FAILURE** | Execution failure notification | At-least-once | Yes | 24h |
| **WILDCARD** | Subscription match-all — `**` in routing expressions | At-least-once | No | TTL of matching subscription |

### Durable Event IDs (from gap analysis)

Every A2A message has a durable event ID:

```python
@dataclass(frozen=True)
class A2AEnvelope:
    message_id: str                 # UUID v4 — unique message identifier
    semantic: str                   # COMMAND | EVENT | QUERY | RESPONSE | DELEGATION | ...
    source_worker_id: str           # Sending worker
    target_worker_id: str | None    # Receiving worker (None for broadcast)
    channel_id: str | None          # Team/channel ID
    payload: dict                   # Message content
    metadata: dict                  # Routing hints, priority, retry count
    idempotency_key: str            # Deduplication key
    ttl_seconds: int                # Message TTL (0 = no expiry)
    correlation_id: str             # Links to execution trace
    created_at: float               # Timestamp
```

### Circuit Breakers for A2A (from gap analysis)

Agent-to-agent communication has its own circuit breaker:

```python
class A2ACircuitBreaker:
    """Prevent cascading failures in agent communication."""

    def __init__(self, agent_id: str, threshold: int = 5, window: int = 60):
        self.agent_id = agent_id
        self.threshold = threshold
        self.window = window
        self.failures: list[float] = []

    def record_failure(self) -> None:
        self.failures.append(time.time())
        if len(self.failures) >= self.threshold:
            self.open()  # Stop sending to this agent

    def can_send(self) -> bool:
        # Clean old failures outside window
        cutoff = time.time() - self.window
        self.failures = [f for f in self.failures if f > cutoff]
        return len(self.failures) < self.threshold
```

### Work-Stealing Scheduler (M1+ from gap analysis)

When workers are idle, they can steal work from overloaded workers:

```python
class WorkStealingScheduler:
    """Fair work distribution with work-stealing for idle workers."""

    def schedule(self, workers: list[Worker], tasks: list[Task]) -> list[Assignment]:
        # 1. Assign tasks to workers based on capacity
        # 2. Idle workers steal from overloaded workers' queues
        # 3. Ensure fairness: no worker waits while another has excess
        pass
```

---

## 24. Human-in-the-Loop

### Confirmation Flows

| Flow | Trigger | User Action | Timeout |
|------|---------|-------------|---------|
| **Simple Confirm** | D/IRREVERSIBLE mutation | YES/NO | 5 minutes |
| **Approval Chain** | Multi-step approval needed | Approve/Reject at each step | 15 minutes per step |
| **Escalation** | User unavailable | Admin override | 30 minutes |
| **Re-entry** | Confirmation expired | Restart from S10 | N/A |


> **S12–S15 gate v9 repair (C20, C38):** The canonical confirmation contract is DATA_CONTRACTS `Confirmation` (certified in S0–S11); canonical statuses are `pending`, `consumed`, `rejected`, `expired` (STATE_TRANSITIONS §8). The block below is historical.

### Confirmation Token

```python
@dataclass(frozen=True)
class ConfirmationToken:
    token_id: str                    # UUID v4
    user_id: str                     # Who must confirm
    conversation_id: str             # Which conversation
    plan_id: str                     # Which plan
    operations: list[str]            # What will be executed
    created_at: float                # Creation timestamp
    expires_at: float                # Expiration timestamp (created + 300s)
    status: str                      # pending | confirmed | rejected | expired
```

### Confirmation Rules

| Rule | Implementation |
|------|----------------|
| **Single-use** | Token consumed atomically on first use |
| **Time-limited** | Expires after 5 minutes |
| **User-bound** | Token tied to user_id + conversation_id |
| **Specific** | Message lists exact operations |

---

## 25. Security Model

### Six Security Principles

| # | Principle | Rule |
|---|-----------|------|
| 1 | **Never trust user input** | All user input is sanitized before processing |
| 2 | **Never trust LLM output for auth** | Authorization is deterministic, not delegated to LLM |
| 3 | **Fail-closed** | When in doubt, deny — never guess |
| 4 | **No privilege escalation via context** | ExecutionContext is frozen and never from LLM |
| 5 | **Defense in depth** | Multiple layers of security, not just one |
| 6 | **Audit everything** | Every action is logged with who, what, when, where |

### Trust Boundaries

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  User Input │────▶│   Sanitize  │────▶│   Process   │
│  (UNTRUSTED)│     │  (BOUNDARY) │     │  (TRUSTED)  │
└─────────────┘     └─────────────┘     └─────────────┘

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│Provider Resp│────▶│   Sanitize  │────▶│    LLM      │
│ (UNTRUSTED) │     │  (BOUNDARY) │     │  (TRUSTED)  │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Prompt Injection Defense

Every text crossing a trust boundary MUST be sanitized:

| Boundary | Direction | Action |
|----------|-----------|--------|
| User → System | Input | Scan + sanitize before LLM call |
| Provider → System | Input | Scan + sanitize before any processing |
| System → LLM | Output | Scan provider data before including in prompt |
| System → User | Output | Scan LLM output before sending to user |
| Database → System | Output | Sanitize when displaying to user |

### Injection Handling Rules

| Severity | Action | User Sees |
|----------|--------|-----------|
| none | Normal processing | Normal response |
| medium | Log warning, sanitize, flag for review | Normal response |
| high | Log alert, block, notify admin | "I couldn't process that request" |

---

## 26. Identity & Tenancy

### Identity Hierarchy

```
Tenant
  └── Workspace(s)
       └── User(s)
            └── Membership(s) [role, scopes]
                 └── Connection(s) [provider credentials]
                      └── Execution(s) [trace_id, request_id]
```

### Worker Identity Model

> **Worker-management repair (RD-1; audit round 2 C1, B7):** key type ruling — `workers.worker_id` and every column that references it are `TEXT`, like every other key in DATABASE.md (`tenant_id`, `user_id`, `workspace_id`, `execution_id`); the owner ruling overrides the gate §7.3 default of changing the referencing column. Timestamps in new columns are `TIMESTAMPTZ` (RD-2). DATABASE.md is authoritative for this table; the DDL below mirrors it.

```sql
CREATE TABLE workers (
    worker_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id TEXT REFERENCES workspaces(workspace_id),  -- gate v10 C39 filter 4b; NULL = legacy, ineligible
    worker_class VARCHAR(100) NOT NULL,
    runtime_version VARCHAR(50),
    capability_profile JSONB NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'REGISTERED',   -- STATE_TRANSITIONS §4
    capacity INTEGER NOT NULL DEFAULT 1,               -- max concurrent executions
    current_load INTEGER NOT NULL DEFAULT 0,
    lease_epoch BIGINT NOT NULL DEFAULT 0,             -- newest fence token issued (gate C25)
    heartbeat_at TIMESTAMP,
    last_assignment_at TIMESTAMP,
    drain_state VARCHAR(20),
    -- worker-management columns (gate v10 C39; WORKER_LIFECYCLE §16.1)
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    assigned_user_id TEXT REFERENCES users(user_id),
    paused_until TIMESTAMPTZ,
    scheduled_activation_at TIMESTAMPTZ,
    runtime_type TEXT NOT NULL DEFAULT 'llm',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---
## 27. Observability & Tracing

### Trace Hierarchy

```
execution_id (top-level execution)
  ├── trace_id (canonical correlation)
  │     ├── request_id (individual request)
  │     │     ├── step_id (pipeline stage)
  │     │     │     ├── provider_call_id (adapter call)
  │     │     │     └── attempt_id (retry attempt)
  │     │     └── llm_call_id (LLM interaction)
```

### Distributed Tracing

Every execution has a trace_id. All spans are correlated:

```python
with tracer.start_as_current_span("pipeline.s0.entry") as span:
    span.set_attribute("trace_id", context.trace_id)
    span.set_attribute("tenant_id", context.tenant_id)
```

---
## 28. Validation & Testing

### Four-Tier Testing Strategy

| Tier | What | When | Runtime |
|------|------|------|---------|
| 1 | Unit tests (pure logic) | Every commit | < 5s |
| 2 | Contract tests (adapter API) | Every commit | < 30s |
| 3 | Integration tests (full pipeline) | PR to main | < 2min |
| 3.5 | Billing tests | Every billing commit | < 1min |
| 4 | Chaos tests (failure injection) | Nightly / pre-deploy | < 5min |

---
## 29. Key Decisions & Rationale

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **Durable execution kernel** | Enables checkpoint/resume, crash recovery, auditability | Added complexity vs fire-and-forget |
| **One unconditional LLM call** | Predictable cost, deterministic behavior | Less flexibility for complex intents |
| **Frozen ExecutionContext** | Prevents LLM output from corrupting state | Requires immutable update pattern |
| **Frozen Binding Identity** | Prevents mid-execution provider swapping | Less flexibility if binding becomes invalid |
| **Deterministic authorization** | Security cannot depend on LLM judgment | More upfront work for auth rules |
| **Post-execution verification** | Catches failures that API success masks | Additional step adds latency |
| **Capability-driven design** | Decouples intent from implementation | Requires registry maintenance |
| **Adapter isolation** | Prevents cascading failures | More boilerplate per provider |
| **RLS at database level** | Tenant isolation enforced by DB, not application | Requires careful query design |
| **pgvector for vector search** (ADR-14) | Tenant isolation by RLS (I-001), writes atomic with their events (I-020), one backup procedure, shared across nodes | Vector search load on the primary database; a very large tenant gets its own partition, and a future backend needs its own ADR |
| **One execution path for every runtime type** (RD-8, RD-9) | Browser, RPA, vision, rules, data and human workers keep S8 authorization, S10 confirmation and the S11 manifest; `runtime_type` selects routing, binding and worker eligibility, never skipped stages | Simple recorded workflows still pass through every stage (FAST/REFLEX keep them cheap) |
| **Progressive autonomy is restrict-only** (RD-14) | The existing `AutonomyLevel` stays the one autonomy enum; any per-capability refinement can only tighten it | Promotion is an admin decision, not automatic |
| **Memory is not authorization** (§21) | Memory informs LLM behavior; the kernel decides what is allowed | Policy text must be maintained in policy tables, not memory |
| **Replanning = child execution** (RD-11) | A new plan runs as a new execution through S0→S15 with its own manifest; the plan of a running execution never changes (I-006, I-017) | A replan costs a new S0–S11 pass |
| **Worker checks are eligibility filters** (RD-4) | Admission runs before a worker is chosen, so worker pause, assignment and runtime match filter candidates at selection time | Two places to look: admission (tenant/workspace/system) and selection (worker) |

---

## 30. Architectural Evolution Path

### M0 — Foundation (Weeks 1-4)
- Repository structure, CI, PostgreSQL
- Data contracts, pipeline S0-S7
- Worker identity, execution contracts
- **Deliverable**: Running pipeline with mock adapters

### M1 — Execution (Weeks 5-8)
- Pipeline S8-S15 complete
- Reliability guard, circuit breaker, retry
- Adapters for 3 providers (GHL, Notion, Google)
- Verification layer
- **Deliverable**: Working execution with real providers

### M2 — Scale (Weeks 9-12)
- Worker pools, horizontal scaling
- Multi-agent coordination (A2A messaging)
- Memory architecture (L0-L3)
- Observability dashboard
- **Deliverable**: Production-ready multi-tenant platform

### M3 — Intelligence (Weeks 13-16)
- AGENTIC path (adaptive planning)
- Skill factory (dynamic skill compilation)
- Autonomous worker loops
- Advanced memory (semantic search, consolidation)
- **Deliverable**: Self-improving AI worker platform

### M4 — Ecosystem (Weeks 17-20)
- Provider marketplace
- Skill sharing
- Cross-tenant federation
- Advanced HITL (delegation, multi-step chains)
- **Deliverable**: AI worker marketplace

### Stability Tiers T1–T7

> **Worker-management repair (RD-15):** from the spec's §7 ("Seven-Layer Architecture Invariant"), renamed so it does not collide with the layer model of §6. Tiers rank how stable each concern must be; they are not a second layer stack.

| Tier | Concern | Stability |
|------|---------|-----------|
| T1 | Safety / identity / authorization (S0–S8, RBAC, grants, safety gate) | FROZEN after S0–S11 certification |
| T2 | Durable execution + evidence (lease, fence, ledger, checkpoint) | STABLE after S12–S15 certification; additive only |
| T3 | Provider / protocol / event ecosystem (adapters, Event Gateway) | Stable; new providers are additive |
| T4 | Model / runtime / worker routing (selection, `runtime_type`, model routing) | Evolving; worker-management filters (gate v10 C39) |
| T5 | Skills / capability composition | Evolving; compositions are planned at S9 |
| T6 | Multi-agent coordination (delegation, spawning, execution tree) | Evolving; spawning deferred |
| T7 | Marketplace / business outcomes (listing, templates, plans) | Evolving; the kernel never knows marketplace mechanics |

Rules: no tier may bypass a lower tier (T5 executes only through T4→T3→T2; T6 spawns only through T1 authorization); each tier can only restrict what lower tiers allow.

---

## 31. Implementation Roadmap

### Week-by-Week Plan

| Week | Focus | Deliverable | Validation |
|------|-------|-------------|------------|
| W1 | Foundation | PostgreSQL, Alembic, CI | `pytest db/ -v` all green |
| W2 | Data layer | Schema, RLS, seed data | RLS tests pass |
| W3 | Worker identity | State machine, lease mgmt | State machine tests |
| W4 | Execution contracts | Frozen dataclasses | Contract tests |
| W5 | Pipeline S0-S7 | First half operational | Integration tests |
| W6 | Pipeline S8-S15 | Full pipeline | End-to-end tests |
| W7 | Reliability guard | Circuit breaker, retry, budget | Chaos tests |
| W8 | Adapters | 3 providers, binding resolution | Adapter tests |
| W9 | Verification layer | Post-execution validation | Verification tests |
| W10 | Memory | L0-L3 persistence, retrieval | Memory tests |
| W11 | Multi-agent | A2A messaging, worker pools | A2A tests |
| W12 | HITL | Confirmation gates, workflows | HITL tests |
| W13 | Observability | Tracing, logging, metrics | Trace tests |
| W14 | Skill factory | Compilation, caching | Skill tests |
| W15 | Integration testing | 50 integration tests | CI green |
| W16 | Performance | Load testing, optimization | Load test report |
| W17 | Documentation | API docs, architecture docs | Docs build |
| W18 | Deployment | Docker, CI/CD, staging | Deploy runbook |
| W19 | Production readiness | Monitoring, runbooks, DR | Production review |

---

## 32. Definition of Done

```text
Component Complete =
    Contract Defined
AND Implementation Built
AND Unit Tests
AND Integration Tests
AND Negative Tests
AND Failure Tests
AND Security Tests
AND Tenant-Isolation Tests
AND Observability Test
AND Documentation Updated
AND Certification Evidence Stored
```

Every component in the execution plan must have all 11 items checked before it can be marked complete.

**Validation test**: `test_definition_of_done()` — verifies no component is marked complete without all 11 items.

---
## 33. Worker Capacity & Scale — 10,000-Worker Contract

### Scalability Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Concurrent workers | 10,000 | Per cluster |
| Steps per second | 5,000 | Sustained |
| P99 latency | <500ms | For S0-S11 decisions |
| Lease sweep interval | <30s | For stale lease detection |
| Circuit breaker update | <1s | For distributed state |

### Worker Capacity Semantics

```python
@dataclass(frozen=True)
class WorkerCapacity:
    worker_id: str
    max_concurrency: int
    current_concurrency: int
    provider_capacity: dict[str, int]
    drain_state: str  # NONE | DRAINING | DRAINED
```

> **Worker-management repair (RD-4, RD-12):** a worker's load is its number of usable leases (`current_load`, gate C26). Batch slices are ordinary steps, so they are already counted by their leases; no separate `batch_count` is added. Child workers (post-S15) have their own capacity and are not added to the parent's load. Worker-management eligibility filters (gate v10 C39) run before capacity and locality scoring.

**Tenant fairness**: Each tenant gets proportional share of worker pool. Noisy-neighbor tenants are rate-limited at tenant scope, not worker scope.

**Validation test**: `test_10k_worker_contract()` — verifies 10,000 concurrent workers maintain SLOs.

---
## 34. Terminology

```text
Worker
= durable identity, persisted in database, survives restarts

Worker Runtime
= running process/container that embodies a Worker

Worker Pod
= isolated runtime environment for a Worker Runtime

Model
= LLM inference component (Claude, GPT, Gemini, etc.)

Execution Strategy
= REFLEX / REACT / DAG / PLAN_EXECUTE / AGENTIC

Agent (deprecated in architecture docs)
= ambiguous; use Worker, Worker Runtime, or Execution Strategy instead

Worker Group
= tenant-scoped set of Workers managed together (bulk pause, schedule, assign); post-S15

runtime_type
= how a Worker executes: llm, rules, vision, browser, rpa, data, rag, code, human.
  Selects routing, binding family and worker eligibility; never skips a stage.
  Plan/event/hybrid is derived from active WorkerSubscription rows, not stored.
```

Never say "Worker equals Agent." They are different concepts.

> **Worker-management repair (RD-10, spec area 8):** a Worker Runtime is deployment-target agnostic (Docker, Kubernetes, serverless, edge, on-prem) behind the Runtime Contract (§38) and `WorkerRuntime` (§37a Principle 5). "Worker Deployment" in §51's lifecycle model (a customer's installed instance) is not `WorkerDeployment` in WORKER_LIFECYCLE §5 (a running runtime instance).

### Documented Conflicts (catalogue)

> **Worker-management repair (RD-16):** this catalogue had lost its heading. Its summary is §37c.

---

All documented conflicts from the rebuild documents are catalogued in this section, with resolution references:

### Critical Conflicts (Would Break Implementation)

| # | Conflict | Source A | Source B | Resolution |
|---|----------|----------|----------|------------|
| 1 | ExecutionContext immutability | DATA_CONTRACTS.md says frozen | PIPELINE_STAGES.md says S5 populates provider | Use `replace()` immutable update pattern; document this explicitly |
| 2 | LLM call count | PIPELINE_STAGES.md says "ONE unconditional LLM call" | S2 allows retry once | Document as "max 2 LLM calls" with retry policy |
| 3 | Memory layer numbering | MEMORY_ARCHITECTURE.md uses L0-L3 | GAP_ANALYSIS.md references L0-L6 | Unified to L0-L3 (Episodic, Working, Session, Long-Term) |
| 4 | Pipeline stage numbering | TOC lists S11, S13 but not S12 explicitly | PIPELINE_STAGES.md body has S12 | Explicitly named S12 "Execute with Reliability Guard" |
| 5 | CONCURRENCY_MODEL.md | Listed as MISSING in BUILD_READINESS_MATRIX.md | TRACING_AND_CONCURRENCY.md exists | Clarified: CONCURRENCY_MODEL.md is M2 deliverable, TRACING_AND_CONCURRENCY.md covers M0-M1 |
| 6 | Verification layer | Referenced as MISSING in GAP_ANALYSIS.md | Not present in any document | Added as S13 in pipeline, with full specification |
| 7 | Circuit breakers | Referenced as MISSING in GAP_ANALYSIS.md | RELIABILITY.md mentions but doesn't fully specify | Fully specified in Reliability Layer section |
| 8 | Durable event IDs | Referenced as MISSING in GAP_ANALYSIS.md | Not present in any document | Added to Multi-Agent Communication section |
| 9 | Adaptive autonomy | Referenced as MISSING in GAP_ANALYSIS.md | Referenced in MASTER_ARCHITECTURE_FINAL.md | Documented as M3 feature (AGENTIC path) |
| 10 | Worker persistence across restarts | Referenced as MISSING in GAP_ANALYSIS.md | Referenced in IDENTITY_AND_TENANCY.md | Specified in Durable Execution Kernel section |

### Minor Conflicts (Documentation Inconsistencies)

| # | Conflict | Source A | Source B | Resolution |
|---|----------|----------|----------|------------|
| 11 | Kernel operation counts | PROVIDER_ADAPTERS.md shows varying counts | No explanation for variance | Documented as capability-specific; add rule for minimum coverage |
| 12 | Database schema vs data contracts | DATABASE.md and DATA_CONTRACTS.md may diverge | Cross-document check needed | Added validation checklist requirement |
| 13 | OpenFlow/CRX references | Some docs mention removal | CLAUDE.md says completely removed | Verified all references removed or marked as historical |
| 14 | Semantic capability layer | Referenced as analytical overlay | MASTER_ARCHITECTURE_FINAL.md says retained as metadata | Clarified as metadata-only, not executable |
| 15 | Voice channel scope | MASTER_ARCHITECTURE_FINAL.md says "one interface among many" | Layer 5 diagram shows it as first-class | Documented as interface channel, not product boundary |
| 16 | Budget atomicity | DATABASE.md mentions atomic operations | RELIABILITY.md mentions budget guard | Specified atomic reserve/commit/release/lock pattern |
| 17 | Multi-provider routing | Referenced in gap analysis | Not fully specified in PROVIDER_ADAPTERS.md | Added provider selection algorithm |
| 18 | Provider failover | Referenced as MISSING | RELIABILITY.md mentions circuit breaker | Added failover strategy to Reliability section |
| 19 | Skill versioning | Referenced as MISSING | SKILL_FACTORY_ARCHITECTURE.md doesn't mention versioning | Added versioning to Skill Factory |
| 20 | Tool sandboxing | Referenced as MISSING in some repos | SKILL_FACTORY_ARCHITECTURE.md mentions sandboxing | Specified sandboxing requirements |

---

## 35. No Silent Success

**I-XXX: No Silent Success**

No external mutation may be represented as successful solely because the provider returned an API success response. Required chain:

```
Provider Response
    ↓
Adapter Result
    ↓
Kernel Interpretation
    ↓
Verification
    ↓
Committed SUCCESS
```

An adapter returning HTTP 200 is NOT sufficient for SUCCESS. The kernel must verify the actual outcome before committing success.

**Validation test**: `test_no_silent_success()` — verifies adapter success does not directly become committed SUCCESS.

---
## 36. Pluggable Memory Backends

Memory backends are pluggable behind one interface. The vector backend is **pgvector in PostgreSQL**; LanceDB was not chosen (ADR-14, DECIDED 2026-09-29). Target phase: memory / LLM layer, after S15 (gate v10 §14).

**Backend interface** (async; a scope is mandatory on every call; contracts in DATA_CONTRACTS §54):
```python
class MemoryBackend(Protocol):
    async def write(self, tx: Transaction, scope: MemoryScope, entry: MemoryEntry) -> WriteResult: ...
    async def read(self, scope: MemoryScope, query: MemoryQuery) -> list[MemoryEntry]: ...
    async def search(self, scope: MemoryScope, vector: Sequence[float],
                     limit: int, filters: MemoryFilter | None = None) -> list[MemoryHit]: ...
    async def delete(self, tx: Transaction, scope: MemoryScope, entry_id: str) -> bool: ...
    async def purge(self, scope: MemoryScope | TenantScope) -> int: ...
    async def close(self) -> None: ...
```

**Rules** (ADR-14 §3.1, §3.3):
1. The scope comes from `ExecutionContext` / `PrincipalChain` only (user = original principal), never from LLM output or request parameters.
2. The tenant boundary is enforced by RLS (I-001); the workspace, worker, user and session boundaries by the backend's mandatory predicates.
3. `read` and `search` cover a fixed read set: `(worker, user)`, `(worker, no user)`, `(no worker, user)`, workspace-wide. Memory is private to its worker; shared memory is written to the workspace-wide scope.
4. `MemoryFilter` only narrows (tags, time range, source, minimum confidence).
5. `write` and `delete` take the caller's transaction, so the memory row and its event commit together (I-014, I-020).
6. The backend never calls an embedding provider (§6 dependency direction; register MR-3).
7. `purge` accepts a tenant-only scope, may be called only by an owner/admin member or the off-boarding job, and is audited.

**Implementations**:
| Backend | Use Case | Persistence |
|---------|----------|-------------|
| PostgreSQL + pgvector | Vector search (`memory_vectors`: RLS, LIST partitions for large tenants, HNSW per partition), structured memory, checkpoints | Durable; DATABASE §5 backups |
| Amazon S3 (payload store behind the PostgreSQL backend, not a `MemoryBackend`) | Payloads above `memory_payload_inline_max_bytes` (default 256 KiB) | Durable; per-tenant envelope encryption, crypto-shredding (ADR-14 Part 3) |
| In-process LRU cache | Hot reads; every key holds the full `MemoryScope`, and `purge` invalidates it | Volatile (a shared Redis cache waits for the fleet phase) |

**Validation test**: `test_memory_backend_swap()` — verifies backend can be swapped without changing kernel.

---
## 37. PostgreSQL Not Message Bus

PostgreSQL is the durable source of truth for all execution state. It is NOT the message bus.

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| State storage | PostgreSQL | ACID, RLS, durability |
| Message passing | In-process or dedicated queue | PostgreSQL is not a message bus |
| Ephemeral state | Redis | Fast, TTL-based |
| Vector search | pgvector (in PostgreSQL) | Durable, RLS; state, not messaging |

**Rule**: PostgreSQL stores what must survive restarts. Nothing else does.

------

## 37a. Adaptability Principles

> **Purpose**: Define the principles that allow SuprAgents to integrate new runtimes, protocols, and adapters without modifying the kernel. The kernel is stable; everything above it is pluggable.

### Principle 1: Kernel Stability Boundary

```
╔═══════════════════════════════════════════════════════════════╗
║  KERNEL (STABLE — never modified for new adapters/runtimes)   ║
║  S0–S15 Pipeline, State Machines, Budget, Safety, RLS         ║
╠═══════════════════════════════════════════════════════════════╣
║  EXTENSION ZONE (PLUGGABLE — add without kernel changes)      ║
║  Provider Adapters, Capabilities, Skills, Workflows, Memory   ║
╚═══════════════════════════════════════════════════════════════╝
```

No change to S0–S15, no change to state machines, no change to budget or safety is ever required to add a new adapter, protocol, or runtime.

### Principle 2: Protocol Independence via Adapter Interface

Every external protocol (MCP, browser automation, REST API, gRPC) implements the `BaseAdapter` interface:

```python
class BaseAdapter(ABC):
    @abstractmethod
    async def call(self, kernel_op_id: str, params: dict,
                   binding: BindingRow, context: ExecutionContext) -> KernelResult:
        """Execute a kernel operation. NEVER raises — always returns KernelResult."""
        pass
```

New protocols add an adapter class. They do NOT modify the kernel, the pipeline, or the resolution chain.

> **S12–S15 gate v9 repair (C32):** `BaseAdapter` also has `probe()` and `observe()` with safe defaults (INCONCLUSIVE / inconclusive observation) and `call()` accepts an optional `call_meta` (idempotency key, attempt and call ids). These are additive: an adapter written to the signature above keeps working, and the defaults keep uncertain mutations out of silent success. See PROVIDER_ADAPTERS §1.

### Principle 3: Bidirectional MCP (Ouroboros Pattern)

The kernel can serve as both an MCP client (consuming external MCP servers) and an MCP server (exposing its capabilities to external agents).

```
EXTERNAL MCP CLIENT                    SUPRAGENTS KERNEL                    EXTERNAL MCP SERVER
       │                                     │                                    │
       │  MCP Request (tool_call)            │                                    │
       │────────────────────────────────────▶│                                    │
       │                                     │  S0 → S1 → S2 → ... → S15           │
       │                                     │  (identical pipeline)               │
       │                                     │────────────────────────────────────▶│
       │                                     │                                    │  Execute tool
       │                                     │◀────────────────────────────────────│
       │  MCP Response (tool_result)         │                                    │
       │◀────────────────────────────────────│                                    │
```

MCP tools are registered as capabilities with `kernel_op_id` prefixed `mcp://`. MCP tool results go through the same S13 verification as any other adapter result.

### Principle 4: Capability-Driven Routing

The kernel never calls a specific adapter directly. It always routes through:

```
Intent → Capability → FrozenBindingIdentity → Adapter → KernelResult
```

Adding a new capability requires: (1) define capability in registry, (2) implement adapter, (3) create binding. No pipeline changes.

### Principle 5: Runtime Agnostic Execution

Worker runtimes (Docker, Kubernetes, serverless, bare metal) are interchangeable. The kernel interacts with workers through:

- Lease acquisition/renewal (not process management)
- Heartbeat monitoring (not health checks)
- Execution results (not process output)

A new runtime integrates by implementing the `WorkerRuntime` interface:

```python
class WorkerRuntime(ABC):
    @abstractmethod
    async def execute(self, step: PlanStep, context: ExecutionContext) -> KernelResult: ...
    @abstractmethod
    async def heartbeat(self) -> bool: ...
    @abstractmethod
    async def shutdown(self) -> None: ...
```

### Principle 6: Configuration Versioning

Configuration is versioned and frozen per execution:

```python
@dataclass(frozen=True)
class ConfigurationVersion:
    capability_version: str
    binding_version: str
    policy_version: str
    risk_policy_version: str
    adapter_version: str
    kernel_version: str
```

An execution always uses the configuration versions frozen at S11. Configuration changes affect new executions only (I-017).

### Principle 7: Extensible Event Sourcing

All significant events in the system are emitted as `OutboxEvent` entries. External events arrive as `EventEnvelope`. Both share the same event identity model:

```python
@dataclass(frozen=True)
class EventIdentity:
    event_id: str              # UUID v4
    event_type: str            # Event type enum
    source: str                # Who generated this event
    correlation_id: str        # Links to execution trace
    causation_id: str | None   # What caused this event
    tenant_id: str             # Isolation boundary
    timestamp: str             # ISO 8601 UTC
```

New event types add a new enum value. They do NOT modify the event storage, correlation, or routing infrastructure.

### Principle 8: No Custom Execution Paths

There is exactly ONE execution path through the kernel: S0 → S1 → ... → S15. Whether triggered by human, schedule, API, event, or internal system call — all executions follow the identical pipeline. There are no special cases, no bypass modes, no shortcuts.

| Trigger | Enters At | Pipeline | Same Safety Gate? |
|---------|-----------|----------|-------------------|
| Human message | S0 | S0→S15 | Yes (S8) |
| Cron schedule | S0 | S0→S15 | Yes (S8) |
| API call | S0 | S0→S15 | Yes (S8) |
| External event | S0 (via Event Gateway) | S0→S15 | Yes (S8) |
| Internal trigger | S0 | S0→S15 | Yes (S8) |

**This is an architecture invariant (I-023, generalized by I-029).**

> **Worker-management repair (RD-8):** the reference used to say I-024, which is Kernel Stability. Browser, RPA, vision, rules, data and human workers are **not** exceptions: they enter at S0 and pass S8, S10 and S11 like every other execution. `runtime_type` selects the strategy (S7), the binding (S5) and the eligible workers (S12); recorded workflows are skill compositions planned at S9. Speed-ups come from FAST/REFLEX strategies with no LLM call, never from skipping stages.

### Extension Point Catalog

| What You Want to Add | Where | What Changes |
|---------------------|-------|-------------|
| New provider (e.g., Salesforce) | Layer 1 (Adapter) | New adapter class + kernel_ops entries + bindings |
| New capability (e.g., "create_invoice") | Layer 2 (Registry) | New capability definition + binding |
| New protocol (e.g., GraphQL) | Layer 1 (Adapter) | New adapter class implementing BaseAdapter |
| New event source (e.g., Slack) | Event Gateway | New EventSource enum value + receive handler |
| New worker runtime (e.g., Lambda) | Execution Kernel | New WorkerRuntime implementation |
| New memory backend | Layer 0 | New MemoryBackend implementation |
| New interface (e.g., Slack bot) | Layer 5 | New Interface adapter → S0 |
| New skill | Capability layer | New skill definition, no kernel changes |
| New runtime type (e.g., browser) | Layer 1 (Adapter) + routing | New adapter + bindings (one per provider, frozen at S5) + `runtime_type` value; no pipeline change (RD-8, RD-9) |

**Nothing in the KERNEL (S0–S15, state machines, budget, safety) ever changes for any of the above.**

**Source**: [ADAPTABILITY_PRINCIPLES.md](ADAPTABILITY_PRINCIPLES.md) for complete design rationale. [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) for Event Gateway contracts.


## 37b. Execution Manifest as Frozen Artifact

> **Worker-management repair (RD-16):** formerly headed "38..", duplicating §38. Cited as §37b by §13 and gate C38.

The ExecutionManifest is a frozen artifact created at the end of S11 and consumed by S12.

```python
@dataclass(frozen=True)
class ExecutionManifest:
    execution_id: str
    trace_id: str
    plan_hash: str
    capability_version: str
    binding_version: str
    policy_version: str
    risk_policy_version: str
    authorization_version: str
    worker_runtime_version: str
    model_version: str
    created_at: float
```

**Storage**: Frozen at S11 completion; persisted to `execution_manifests` at S12 entry in the admission transaction, byte-identical to the S11 manifest (see §13). Read-only for S12 and all subsequent stages. Never updated after creation.

**Validation test**: `test_execution_manifest_frozen()` — verifies manifest cannot be modified after S11.

---
## 37c. Conflict Resolution Log

All documented conflicts from the rebuild documents are catalogued in this section, with resolution references:

### Critical Conflicts (Would Break Implementation)

| # | Conflict | Source A | Source B | Resolution |
|---|----------|----------|----------|------------|
| 1 | ExecutionContext immutability | DATA_CONTRACTS.md says frozen | PIPELINE_STAGES.md says S5 populates provider | Use replace() immutable update pattern |
| 2 | LLM call count | PIPELINE_STAGES.md says ONE call | S2 allows retry once | Document as max 2 LLM calls |
| 3 | Memory layer numbering | L0-L3 vs L0-L6 | Unified to L0-L3 |
| 4 | Pipeline stage numbering | TOC missing S12 | Explicitly named S12 |
| 5 | CONCURRENCY_MODEL.md | Listed MISSING | TRACING_AND_CONCURRENCY.md exists |
| 6 | Verification layer | MISSING in GAP_ANALYSIS | Added as S13 |
| 7 | Circuit breakers | MISSING in GAP_ANALYSIS | Fully specified |
| 8 | Durable event IDs | MISSING in GAP_ANALYSIS | Added to A2A section |
| 9 | Adaptive autonomy | MISSING in GAP_ANALYSIS | Documented as M3 feature |
| 10 | Worker persistence | MISSING in GAP_ANALYSIS | Specified in Durable Kernel |

---
## 37d. Patterns Adopted from Studied Repos

### AgentsMesh Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Worker identity persistence** | E2 (Durable worker identity) | Identity & Tenancy | Durable worker_id with state machine |
| **Circuit breakers for A2A** | E2 (A2A circuit breakers) | Multi-Agent Communication | A2ACircuitBreaker per agent |
| **Row-level security** | E2 (RLS) | Identity & Tenancy | PostgreSQL RLS on all tenant tables |
| **Multi-tenant isolation** | E2 (Tenant isolation) | Identity & Tenancy | Tenant-scoped all operations |

### SystemOneHarness Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Debug replay** | E2 (Debug replay) | Observability | DebugReplay class for execution replay |
| **Escalation** | E2 (Escalation) | Human-in-the-Loop | Multi-step approval chains |
| **Timeout/re-entry** | E2 (Timeout/re-entry) | Human-in-the-Loop | Confirmation timeout with re-entry |

### Ruflo Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Memory evolution** | E2 (Memory evolution) | Memory Architecture | Confidence decay, memory consolidation |
| **Write barriers** | E2 (Write barriers) | Memory Architecture | MemoryWriteBarrier class |
| **Autonomous collaboration** | E2 (Autonomous collaboration) | Multi-Agent Communication | Work-stealing scheduler |

### CrewMeld Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Task handoffs** | E2 (Task handoffs) | Multi-Agent Communication | TaskHandoff message type |
| **Concurrent handoff logs** | E2 (Concurrent handoff logs) | Multi-Agent Communication | A2AEvent with durable event IDs |

### AIOS Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Provider failover** | E0 → E2 | Reliability Layer | Multi-provider routing with fallback |
| **Provider adapters** | E2 | Provider Adapters | Unified adapter interface |

### MARKUS Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Agent handoff** | E2 (Agent handoff) | Multi-Agent Communication | Task handoff protocol |

### Xagent Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Causal ordering** | E2 (Causal ordering) | Observability | Trace propagation with causal ordering |
| **Read-your-writes** | E2 (Read-your-writes) | Observability | Consistent read after write |

### Cherry Studio Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Agentic loops** | E1 | Execution Engine | AgenticPlanner with adaptive loop |

### OBA-Core Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Clean architecture** | E1 | Overall Architecture | Layer separation, dependency rules |

### Evo Nexus Patterns

| Pattern | Original Capability | Adopted Into | Implementation |
|---------|---------------------|--------------|----------------|
| **Mutation risk classification** | E1 | Safety Model | R/W/D/IRREVERSIBLE taxonomy |
| **Reversibility tracking** | E1 | Safety Model | Undo tokens, reversibility checks |

---



---

## 38. Runtime Contract

> **Purpose**: Decouple Workers from specific AI providers and runtimes. A Worker never imports or directly calls Claude, OpenAI, Gemini, a browser runtime, or any specific execution environment. It depends only on the Runtime Contract.

### Architecture

```
Worker → Runtime Contract → Runtime Adapter → Actual Runtime
```

The Worker emits structured intents. The Runtime Contract defines what a runtime must provide. The Runtime Adapter translates between the contract and the specific runtime API. The Actual Runtime is the implementation detail.

### Runtime Contract Definition

```python
class RuntimeContract(ABC):
    """Interface that every runtime must implement."""

    @abstractmethod
    async def generate(self, messages: list[Message], context: ExecutionContext) -> GenerationResult:
        """Generate a response. Never raises — returns GenerationResult."""
        pass

    @abstractmethod
    async def stream(self, messages: list[Message], context: ExecutionContext) -> AsyncIterator[StreamChunk]:
        """Stream a response. Never raises."""
        pass

    @abstractmethod
    def capabilities(self) -> RuntimeCapabilities:
        """Return this runtime's capabilities (function calling, vision, etc.)."""
        pass

    @abstractmethod
    def cost_model(self) -> CostModel:
        """Return token pricing for budget tracking."""
        pass
```

### Runtime Adapters

| Adapter | Runtime | Capabilities |
|---------|---------|-------------|
| `ClaudeRuntimeAdapter` | Anthropic Claude | Function calling, vision, extended thinking |
| `OpenAIRuntimeAdapter` | OpenAI GPT | Function calling, vision, structured output |
| `GeminiRuntimeAdapter` | Google Gemini | Function calling, vision, grounding |
| `LocalLLMRuntimeAdapter` | Ollama/LM Studio | Basic text, function calling (varies) |
| `BrowserRuntimeAdapter` | Playwright/Puppeteer | DOM interaction, screenshots |
| `ProcessorRuntimeAdapter` | Sandboxed Python | Data transformation, computation |

**Key**: Adding a new runtime requires only a new adapter class. No Worker code changes.

---

## 39. Immutable Intent Specification

> **Purpose**: Capture the user's true objective between raw intent (S2) and execution planning (S9). Prevent the LLM's interpretation from becoming an uncontrolled execution decision.

### Intent Pipeline

```
Raw Intent (S2 LLM output)
    ↓
Normalized Intent (structured, validated)
    ↓
Intent Specification (frozen artifact)
    ↓
Execution Plan (S9)
    ↓
Frozen Manifest (S11)
```

### Intent Specification Contract

```python
@dataclass(frozen=True)
class IntentSpecification:
    """Immutable specification of what the user actually wants."""

    # ─── Core ─────────────────────────────────────────────────────────
    objective: str                  # What the user wants (in their terms)
    normalized_intent: str          # Canonical capability name
    constraints: list[Constraint]   # Hard limits the user set
    acceptance_criteria: list[str]  # How success is verified
    autonomy_level: AutonomyLevel   # How much the Worker can decide

    # ─── Execution ──────────────────────────────────────────────────
    required_capabilities: list[str]  # What must be available
    risk_requirements: RiskRequirement  # Max acceptable risk
    budget_constraints: BudgetConstraint  # Cost limits
    time_constraints: TimeConstraint | None  # Deadline if any

    # ─── Traceability ───────────────────────────────────────────────
    intent_id: str                  # UUID v4
    trace_id: str                   # From ExecutionContext
    created_at: str                 # ISO 8601 UTC
    created_by: str                 # user_id or worker_id
```

### Autonomy Levels

| Level | Worker Can | Human Approval Required |
|-------|-----------|------------------------|
| `FULLY_AUTONOMOUS` | Execute within constraints | Never |
| `SUPERVISED` | Execute, report after | High-risk only |
| `CONFIRM_ALL` | Nothing without approval | Every mutation |
| `READ_ONLY` | Query only, no mutations | N/A |

### Constraint Types

| Type | Meaning | Enforcement |
|------|---------|-------------|
| `HARD` | Cannot be violated | Kernel blocks execution |
| `SOFT` | Prefer to satisfy | Worker weighs in planning |
| `TEMPORAL` | Time-bound | Expires after deadline |
| `SCOPED` | Resource-limited | Budget/budget enforcement |

**Rule**: IntentSpecification is frozen at S3. It cannot be modified by any LLM output. If execution fails to meet acceptance_criteria, the Worker reports failure — it does not silently redefine success.

---

## 40. Execution Ledger

> **Purpose**: Provide a complete, reconstruction-capable record of every execution. The ledger is the forensic truth of the system — it must be possible to reconstruct any execution without application logs.

### Ledger Events

Every significant transition is recorded as a `LedgerEvent`:

| Event | When Recorded | Required Fields |
|-------|---------------|-----------------|
| `RequestReceived` | S0 entry | trace_id, request_id, activation_mode, tenant_id |
| `IntentCreated` | S2 complete | intent_id, intent, confidence, task_id |
| `CapabilityResolved` | S3 complete | capability_id, capability_name, version |
| `BindingFrozen` | S5 complete | binding_id, capability_id, provider, adapter_class, kernel_op_id |
| `PlanCreated` | S9 complete | plan_id, step_count, estimated_budget |
| `ConfirmationGranted` | S10 complete | confirmation_id, plan_hash, granted_by |
| `ManifestFrozen` | S11 complete | manifest_hash, config_versions |
| `ExecutionStarted` | S12 start | execution_id, worker_id, lease_token |
| `StepStarted` | S12 step start | step_id, attempt_id, kernel_op_id, provider_call_id |
| `ProviderCalled` | S12 adapter call | provider_call_id, adapter_class, kernel_op_id |
| `ProviderReturned` | S12 adapter result | provider_call_id, status, duration_ms |
| `VerificationStarted` | S13 start | execution_id, verification_method |
| `VerificationCompleted` | S13 complete | execution_id, verified, evidence_ref |
| `ExecutionCompleted` | S13/S14 end | execution_id, status, outcome, budget_spent |
| `OutcomeDelivered` | S15 complete | execution_id, response_format, delivered_to |
| `WorkerWaiting` | Between executions | worker_id, state, lease_token |

### Ledger Contract

```python
@dataclass(frozen=True)
class LedgerEvent:
    event_id: str              # UUID v4
    event_type: str            # From the table above
    execution_id: str | None   # NULL for pre-execution events
    trace_id: str              # Always present
    tenant_id: str             # Always present
    actor_id: str              # Who/what triggered this
    payload: dict              # Event-specific data
    evidence_ref: str | None   # Reference to evidence (verification, etc.)
    created_at: str            # ISO 8601 UTC — server-authoritative
```

### Reconstruction Guarantee

Given a `trace_id` or `execution_id`, the system can reconstruct:

1. The user's original request
2. The LLM's interpretation (IntentSpecification)
3. The selected capability and binding
4. The execution plan and each step
5. Every provider call and result
6. Verification evidence
7. The final outcome

**Rule**: Ledger events are APPEND ONLY. No update, no delete, no soft-delete. Every event has an immutable `event_id`.

### Database

Ledger events are stored in `execution_events` (DATABASE.md §7) with full RLS and append-only enforcement.

---

## 41. Event Correlation and Aggregation

> **Purpose**: Prevent sending every webhook directly to an LLM. Aggregate, deduplicate, and correlate events before triggering expensive execution.

### Pipeline

```
Raw Events (100 webhooks)
    ↓
Deduplicate (idempotency_key, nonce, sequence)
    ↓
Filter (drop irrelevant per WorkerSubscription)
    ↓
Group (by correlation key)
    ↓
Window (time-bounded aggregation)
    ↓
Aggregate (summarize, count, detect patterns)
    ↓
Meaningful Event → S0 Entry
```

### Correlation Rules

```python
@dataclass(frozen=True)
class CorrelationRule:
    rule_id: str                    # UUID v4
    name: str                       # Human-readable
    event_types: list[str]          # Events to correlate
    window_seconds: int             # Time window for correlation
    group_by: list[str]             # Fields to group on
    aggregation: str                # sum, count, latest, first, custom
    filter_expression: str | None   # JMESPath filter
    min_events: int                 # Minimum events before emitting
    max_events: int                 # Maximum events in one aggregate
```

### Example Aggregations

| Scenario | Input Events | Aggregated Output |
|----------|-------------|-------------------|
| GHL lead.created burst | 50 leads in 5 min | Single "lead_created_batch" event with count |
| Stripe payment.failed + retry | 3 failures in 10 min | Single "payment_repeatedly_failing" event |
| Inventory alerts | 5 items below threshold | Single "inventory_critical" event with item list |
| Email.received from same sender | 10 emails in 1 hour | Single "email_thread" event |

**Rule**: The aggregation layer must be deterministic. Same input events in same order → same output. This enables replay correctness.

---

## 42. Sandboxed Processor Runtime

> **Purpose**: Enable data transformation and computation within the execution kernel, with strict isolation. Python is one processor type among many.

### Processor Runtime Contract

```python
class ProcessorRuntime(ABC):
    """Interface for sandboxed computation."""

    @abstractmethod
    async def execute(self, input_data: dict, processor: ProcessorDefinition,
                      context: ExecutionContext) -> ProcessorResult:
        """Execute a processor. Sandbox enforces all limits."""
        pass

    @abstractmethod
    def validate_schema(self, input_data: dict, schema: dict) -> ValidationResult:
        """Validate input against schema before execution."""
        pass
```

### Processor Types

| Type | Implementation | Use Case |
|------|---------------|----------|
| `python` | Restricted Python (RestrictedPython + resource limits) | Data transformation |
| `sql` | Read-only SQL in isolated schema | Database queries |
| `wasm` | WASM runtime (Wasmtime) | Fast, portable computation |
| `visual` | Declarative transform pipeline | UI/data formatting |
| `custom` | Registered handler | Domain-specific processing |

### Sandbox Constraints

| Resource | Limit | Enforcement |
|----------|-------|-------------|
| CPU time | Configurable per processor | SIGXCPU / timeout |
| Memory | Configurable per processor | Memory limit + OOM kill |
| Filesystem | `/tmp/processor-{id}/` only | chroot / namespace |
| Network | None by default | Network namespace |
| Packages | Explicit allowlist | Pre-approved module list |
| Execution time | 30s default | Async timeout |
| Output size | 1MB default | Size check before return |

**Rule**: Processors run in the `system` actor_type with restricted permissions. They cannot access other tenants' data, cannot make network calls by default, and cannot persist state between executions.

---

## 43. Progressive Verification

> **Purpose**: Replace S13's binary pass/fail with a layered verification framework. Not every execution needs every layer, but high-risk operations require stronger evidence.

### Verification Layers

```
Schema verification
    ↓ (pass)
Deterministic verification
    ↓ (pass)
Provider-state verification
    ↓ (pass)
Semantic verification
    ↓ (pass)
Business-rule verification
    ↓ (pass)
Human verification
```

| Layer | What It Checks | When Required |
|-------|---------------|---------------|
| **Schema** | Output matches expected structure | Always |
| **Deterministic** | Internal consistency, type checks, value ranges | Always |
| **Provider-state** | Read-back from provider confirms operation | W, D, IRREVERSIBLE mutations |
| **Semantic** | AI-based assessment of whether outcome matches intent | AGENTIC path, high-risk |
| **Business-rule** | Domain-specific rules (e.g., "lead must have email") | Configurable per capability |
| **Human** | Human confirms outcome | IRREVERSIBLE, D mutations, low-confidence |

### Layer Selection Rules

```python
def required_verification_layers(mutation: str, risk: float, autonomy: AutonomyLevel) -> list[str]:
    layers = ["schema", "deterministic"]  # Always required

    if mutation in ("W", "D", "IRREVERSIBLE"):
        layers.append("provider_state")
    if risk >= 0.7 or mutation == "IRREVERSIBLE":
        layers.append("semantic")
    if mutation == "IRREVERSIBLE" or autonomy == "CONFIRM_ALL":
        layers.append("human")

    return layers
```

**Rule**: Each layer must independently pass before the execution is marked `COMPLETED`. A failure at any layer routes to `DEAD_LETTER` with full evidence.

---

## 44. Explicit Acceptance Criteria

> **Purpose**: Define success beyond "API returned 200." The system must verify that the intended business outcome actually occurred.

### Acceptance Criteria Contract

```python
@dataclass(frozen=True)
class AcceptanceCriteria:
    """Formal definition of what 'success' means for an execution."""

    criteria_id: str              # UUID v4
    intent_id: str                # Links to IntentSpecification
    conditions: list[Condition]   # Verifiable conditions

    # ─── Verification ───────────────────────────────────────────────
    verification_method: str      # provider_state, semantic, human
    verification_timeout_seconds: int
    max_verification_attempts: int
```

### Condition Types

| Type | Example | Verification |
|------|---------|-------------|
| `resource_exists` | "Contact with email john@example.com exists" | Provider read-back |
| `resource_matches` | "Created record has status='active'" | Provider read-back |
| `side_effect_present` | "Email was sent to john@example.com" | Provider query |
| `state_transition` | "Deal moved from 'new' to 'qualified'" | Provider read-back |
| `count_threshold` | "At least 3 records were created" | Provider query |
| `custom` | Domain-specific check | Worker-provided verifier |

### Business Objective Verification Flow

```
Business Objective
    ↓
Acceptance Criteria (formal, verifiable)
    ↓
Execution
    ↓
Evidence (provider responses, reads, observations)
    ↓
Verification (against acceptance criteria)
    ↓
Outcome (verified success / verified failure / inconclusive)
```

**Rule**: "API returned 200" is NOT sufficient for W/D/IRREVERSIBLE mutations. The kernel must independently verify acceptance criteria against the provider's actual state.

---

## 45. Bounded Autonomous Loops

> **Purpose**: Enable Workers to iterate toward a goal, but never allow unrestricted loops. Every autonomous loop has explicit bounds.

### Loop Contract

```python
@dataclass(frozen=True)
class AutonomyBounds:
    """Hard limits for autonomous execution loops."""

    max_iterations: int           # Maximum observe-decide-act cycles
    max_budget: float             # Maximum cost in budget units
    max_duration_seconds: int     # Maximum wall-clock time
    max_tool_calls: int           # Maximum adapter invocations
    max_risk: float               # Maximum risk per iteration
    termination_criteria: list[str]  # Conditions that end the loop
    escalation_criteria: list[str]   # Conditions that trigger human review
```

### Default Bounds

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `max_iterations` | 5 | Most tasks converge in few iterations |
| `max_budget` | 10.0 | Prevents runaway cost |
| `max_duration_seconds` | 300 | 5 minutes per autonomous task |
| `max_tool_calls` | 20 | Prevents tool-call storms |
| `max_risk` | 0.5 | Upper medium risk |

### Loop Lifecycle

```
Observe (read state)
    ↓
Decide (LLM or rule-based)
    ↓
Act (execute via kernel)
    ↓
Verify (check outcome against acceptance criteria)
    ↓
Refine (adjust approach based on verification)
    ↓
Check bounds (iterations, budget, duration, risk)
    ↓
[Continue or Terminate or Escalate]
```

**Rule**: If any bound is reached, the loop terminates immediately. If `escalation_criteria` are met, a human is notified before termination.

---

## 46. Runtime/Model Routing

> **Purpose**: Route tasks to the appropriate runtime and model based on complexity, cost, latency, and availability. Simple tasks should not consume expensive reasoning models.

### Routing Decision Factors

```python
@dataclass(frozen=True)
class RoutingDecision:
    """Factors that determine runtime and model selection."""

    task_complexity: str          # simple, moderate, complex
    risk: float                   # 0.0-1.0
    latency_requirement_ms: int | None
    budget_available: float
    provider_availability: dict[str, bool]
    worker_profile: WorkerProfile
```

### Routing Matrix

| Task Type | Complexity | Preferred Runtime | Preferred Model |
|-----------|-----------|-------------------|-----------------|
| Simple query | Low | Any | Fast/cheap model |
| Structured extraction | Low | Any | Fast with structured output |
| Reasoning | Medium | Any | Balanced model |
| Complex analysis | High | Any | Most capable model |
| Code generation | Medium | Any | Code-specialized model |
| Vision task | Medium | Vision-capable | Vision-capable model |
| Long context | Medium | Large-context | Large-context model |
| Autonomous loop | High | Any | Most capable (with bounds) |

**Rule**: Routing is determined at S7 (Path Routing) based on the IntentSpecification. It is frozen in the ExecutionManifest. No mid-execution model switching.

---

## 47. Event Replay and Recovery

> **Purpose**: Replay past executions for debugging, recovery, and audit without causing duplicate side effects.

### Replay Contract

```python
@dataclass(frozen=True)
class ReplayContext:
    """Context for replaying an execution."""

    original_execution_id: str    # What we're replaying
    replay_reason: str            # Debug, recovery, audit
    mode: ReplayMode              # DRY_RUN, ISOLATED, PRODUCTION
    isolation_scope: str          # test, staging, production
```

### Replay Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `DRY_RUN` | Execute everything except actual mutations | Debug, test |
| `ISOLATED` | Execute in isolated tenant/environment | Recovery, staging |
| `PRODUCTION` | Execute with idempotency protection | Only for idempotent operations |

### Replay Safety Guarantees

1. **Idempotency keys are preserved**: Replayed executions use the same `request_id` as the original. Provider adapters must honor idempotency.
2. **Frozen manifests are reused**: Replay uses the exact same ExecutionManifest (capability versions, binding versions, policy versions).
3. **External side effects are NOT blindly repeated**: Verification checks whether the side effect already exists before re-executing.
4. **Evidence is compared**: Replay success means acceptance criteria are met, not just "no error."

**Rule**: Replay ≠ repeat. Replay reconstructs the execution path. Whether side effects execute depends on idempotency keys and acceptance criteria verification.

---

## 48. Capability/Schema Evolution

> **Purpose**: Enable capabilities, adapters, and providers to evolve without breaking existing executions.

### Compatibility States

| State | Meaning | Allowed for New Executions? |
|-------|---------|----------------------------|
| `compatible` | Fully backward compatible | Yes |
| `conditionally_compatible` | Compatible with known constraints | Yes, with warnings |
| `breaking` | Incompatible with previous version | Yes, old executions unaffected |
| `deprecated` | Being phased out | Yes, with deprecation warning |
| `revoked` | No longer available | No |

### Version Freezing Rule

```
FrozenBinding captures:
  - capability_version
  - binding_version
  - adapter_version
  - policy_version

ExecutionManifest captures:
  - All of the above
  - Plus: kernel_version, runtime_version, model_version, processor_version

Rule: An execution ALWAYS uses the versions frozen at S11.
      Configuration changes affect new executions only.
```

### Migration Path

1. New version deployed alongside old version
2. New executions use new version (via binding)
3. Old executions continue on old version (via frozen manifest)
4. Deprecation period: both versions available
5. Revocation: old version removed, only after no active executions depend on it

---

## 49. Formal Architecture Compliance Testing

> **Purpose**: Make architecture compliance executable in CI. Every invariant, contract, and security rule must have a named test that fails if violated.

### Compliance Test Layers

```python
class ArchitectureComplianceSuite:
    """Mandatory CI check — blocks merge if any test fails."""

    # Layer 1: Contract completeness
    def test_all_stages_have_contracts(self): ...
    def test_all_state_machines_have_valid_transitions(self): ...
    def test_all_contracts_have_version(self): ...

    # Layer 2: Invariant preservation
    def test_I001_tenant_isolation(self): ...
    def test_I002_frozen_bindings(self): ...
    def test_I005_no_silent_success(self): ...
    def test_I009_immutable_execution_context(self): ...
    def test_I022_event_gateway_tenant_isolation(self): ...
    def test_I023_event_driven_same_pipeline(self): ...

    # Layer 3: State machine validity
    def test_all_transitions_are_legal(self): ...
    def test_terminal_states_have_no_outgoing(self): ...
    def test_illegal_transitions_raise(self): ...

    # Layer 4: Failure coverage
    def test_adapter_failure_never_raises(self): ...
    def test_timeout_produces_unknown(self): ...
    def test_worker_crash_recovery(self): ...
    def test_lease_expiry_handled(self): ...

    # Layer 5: Negative path testing
    def test_cross_tenant_access_blocked(self): ...
    def test_illegal_state_transition_rejected(self): ...
    def test_prompt_injection_detected(self): ...
    def test_malicious_event_payload_blocked(self): ...

    # Layer 6: Concurrency
    def test_concurrent_budget_reservation(self): ...
    def test_lease_fencing_prevents_zombie(self): ...
    def test_rls_under_concurrent_writes(self): ...

    # Layer 7: Recovery
    def test_checkpoint_resume(self): ...
    def test_event_replay_no_duplicate_effects(self): ...
    def test_dead_letter_retry(self): ...
```

### CI Enforcement

```yaml
# .github/workflows/architecture-compliance.yml
- name: Architecture Compliance
  run: |
    pytest tests/architecture/ -v --tb=short
    # FAILS THE BUILD if any architecture test fails
```

**Rule**: Architecture compliance tests run on every PR. They are not optional. They are not "nice to have." A PR that passes functional tests but fails architecture compliance is rejected.

---

## 50. Architecture Invariants

> **Worker-management repair (RD-16):** formerly two identical "## 41." headings, colliding with §41 Event Correlation. The duplicate rows I-022…I-025 were removed and I-029 added. Cited as "invariants §50" by the implementation plan.

```
╔═══════════════════════════════════════════════════════════════╗
║  ARCHITECTURE INVARIANTS                                      ║
║  These are non-negotiable. Every implementation, every test,  ║
║  and every configuration change must preserve these           ║
║  invariants.                                                  ║
╚═══════════════════════════════════════════════════════════════╝
```

| ID | Name | Rule |
|----|------|------|
| **I-001** | TENANT ISOLATION | No cross-tenant data access under any circumstance. RLS enforces this at the database level. |
| **I-002** | FROZEN BINDINGS | Frozen bindings cannot change during execution. S5 output is immutable after S5. |
| **I-003** | SINGLE BUDGET RESERVATION | Only S12 performs budget reservation. S8 checks affordability. S9 does not reserve. |
| **I-004** | ZOMBIE WORKER PROTECTION | A stale owner — a Worker Runtime whose fence token for an execution is lower than that execution's current `execution_ownership.fencing_token` — cannot commit any state change for that execution. Fence tokens come from one database sequence (gate C25). |
| **I-005** | NO SILENT SUCCESS | UNKNOWN cannot become SUCCESS without verification. S13 must establish truth before CONFIRMED_SUCCESS. |
| **I-006** | IMMUTABLE PLAN | A plan cannot mutate after S10 confirmation. |
| **I-007** | LLM CANNOT AUTHORIZE | LLM output cannot authorize an action. Authorization is kernel-evaluated only. |
| **I-008** | PRINCIPAL CHAIN | Every mutation is traceable to an authenticated principal. Original principal is preserved through delegation. |
| **I-009** | IMMUTABLE EXECUTION CONTEXT | ExecutionContext is immutable after S0 creation. |
| **I-010** | IMMUTABLE FROZEN BINDING IDENTITY | FrozenBindingIdentity is immutable after S5 creation. |
| **I-011** | LLM CALL BUDGET | Only one LLM call per request (S2), max 2 with retry. |
| **I-012** | ADAPTER AUTHORIZATION BOUNDARY | No adapter can make authorization decisions. |
| **I-013** | EXTERNAL MUTATION VERIFICATION | Every external mutation must be verified before SUCCESS. |
| **I-014** | MEMORY WRITE BARRIER | Memory writes must pass through MemoryWriteBarrier. |
| **I-015** | SINGLE SOURCE OF TRUTH | FINAL_ARCHITECTURE.md is the single authoritative architecture document. No other document may contradict it. |
| **I-016** | NO CUSTOMER CONFIGURATION OVERRIDE | Customer configuration cannot override kernel security invariants. |
| **I-017** | EXECUTION CONFIGURATION SNAPSHOT | An execution uses the configuration versions frozen in its manifest. Configuration changes affect new executions only. |
| **I-018** | SECRET ISOLATION | Provider credentials never enter execution context, prompts, traces, memory, checkpoints, or artifacts. |
| **I-019** | SERVER-AUTHORITATIVE TIME | Distributed timing decisions use server time, not worker-local clocks. |
| **I-020** | OUTBOX ATOMICITY | State changes and their announcing events are committed atomically. No state change exists without its event. No event exists without its state change. |
| **I-021** | AT-LEAST-ONCE SEMANTICS | Execution is at-least-once (not exactly-once). The step idempotency key (`request_id:plan_step_id`, gate C9), the idempotency ledger and probing before any retry of an uncertain step prevent duplicate effects. Duplicate execution is safe; missing execution is not. |
| **I-022** | EVENT GATEWAY TENANT ISOLATION | `EventEnvelope.tenant_id` comes from the Event Gateway authentication context (HMAC credential lookup). It is NEVER extracted from the event payload. |
| **I-023** | EVENT DRIVEN = SAME PIPELINE | Event-driven executions follow the identical S0→S15 pipeline as human-driven. No parallel path, no bypass mode, no special case exists. |
| **I-024** | KERNEL STABILITY BOUNDARY | No change to S0–S15, state machines, budget, or safety is ever required to add a new adapter, protocol, or runtime. |
| **I-025** | EXTERNAL EVENT SANITIZATION | Event payloads are UNTRUSTED input. They must pass through DataSanitizer before inclusion in any prompt or system processing. |
| **I-026** | FROZEN INTENT SPECIFICATION | IntentSpecification is frozen at S3. It cannot be modified by any LLM output. Execution success is measured against acceptance_criteria, not just API success. |
| **I-027** | EXECUTION LEDGER APPEND ONLY | Ledger events are never updated, deleted, or soft-deleted. Every execution event is permanently recorded. |
| **I-028** | BOUNDED AUTONOMY | Every autonomous loop has explicit bounds (iterations, budget, duration, risk). No unrestricted execution loops exist. |
| **I-029** | ONE EXECUTION PATH | Every execution, whatever its trigger or `runtime_type`, follows S0→S15 and passes S8. No bypass path exists (§37a Principle 8; ruling RD-8 in `WORKER_MGMT_SPEC_REVIEW.md` Part E). |

### Invariant Numbering Schemes

> **Repair (audit round 2 D10):** four numbering schemes coexist. This table (I-001…I-029) is the architecture-level one and is authoritative.

| Scheme | Where | Scope |
|---|---|---|
| I-001 … I-029 | This section | Architecture invariants (authoritative) |
| I-001 … I-014 | IDENTITY_AND_TENANCY.md "Architecture Invariants" | A copy of I-001…I-014 above |
| I-1 … I-10 | STATE_TRANSITIONS.md §12 | Cross-state-machine invariants |
| I1 … I18 | S12_S15_EXECUTION_GATE.md §17 | The S12–S15 invariant checker (`assert_system_invariants`) |

### Guardrail Precedence Order

When multiple guardrails apply to an execution, they are evaluated in this order (highest precedence first):

| Level | Guardrail | Scope | Overrideable |
|-------|-----------|-------|-------------|
| 1 | Identity | Authentication required | No |
| 2 | Tenant Isolation | RLS enforces boundaries | No |
| 3 | Kill Switch | Emergency stop | No |
| 4 | Authorization | Capability + scope check | No |
| 5 | Capability Scope | Capability-specific limits | No |
| 6 | Policy | Risk, mutation, business rules | No |
| 7 | Risk/Mutation | effective_risk, effective_mutation | No |
| 8 | Budget | Reservation and limits | No |
| 9 | Reliability | Retry, circuit breaker, timeout | Conditional |
| 10 | Execution | Step ordering, consolidation | No |

**Rule**: Lower-numbered guardrails cannot be overridden by higher-numbered guardrails. A tenant isolation failure (level 2) cannot be bypassed by an execution retry (level 9).

### Invariant Implementation Requirements

Every invariant must have:

1. A named test that verifies it.
2. A CI gate that runs that test on every commit.
3. A failure mode that halts the pipeline if the invariant is violated.

**Validation test**: `test_architecture_invariants()` — runs all invariant tests as a suite.

---

## 51. Future Worker Platform Compatibility — Architecture Extension Points

> **Worker-management repair (RD-16):** this heading was missing; the content below had no section of its own.

### Foundational Principle

Worker-specific behavior is configurable and replaceable; kernel-level safety, identity, tenancy, durability, authorization, verification, and execution invariants are not customer-configurable.

This means:
- A customer can customize **how the worker behaves**.
- A customer **cannot** customize whether the kernel considers an unauthorized operation authorized.

### Required Extension Points

The architecture has clean extension points for worker platform concepts **without changing the durable execution model, identity model, pipeline semantics, or safety invariants**.

| # | Extension Point | Kernel Boundary |
|---|----------------|-----------------|
| 1 | **Worker Definition** | Kernel owns worker identity. Worker definition is a versioned product record referencing capabilities and skills. |
| 2 | **Worker Deployment** | Deployment extends worker identity with tenant-scoped configuration. Kernel tenancy model already supports this. |
| 3 | **Worker Configuration Layer** | Configuration is data consumed by the worker runtime, not by the kernel. Kernel never interprets configuration content. |
| 4 | **Worker Behavior Profile** | Behavior profile influences worker runtime decisions. Kernel enforces hard boundaries regardless of behavior profile. |
| 5 | **Business Outcome Model** | Business outcome maps to a Business Skill, which maps to technical capabilities. The kernel sees only the execution graph. |
| 6 | **Business Capability Spine** | Business capabilities reference technical capabilities. Kernel authorization operates on technical capabilities only. |
| 7 | **Business Skill Composition** | Business skills are compiled units. Kernel validates their capability references. |
| 8 | **Decision Policy Layer** | Decision policy is a kernel-evaluated guard at level 6 (Policy). LLM output never authorizes an action. |
| 9 | **Worker Exceptions** | Exceptions are evaluated as policy rules. Kernel enforces that exceptions cannot override security invariants. |
| 10 | **Worker Personalization / Lexicon** | Personalization affects output formatting only. Kernel security sanitization is separate and non-overridable. |
| 11 | **Artifact Set + Versioning** | Artifacts are distinct from memory. Artifact version is frozen in ExecutionManifest. |
| 12 | **Memory / Learning Boundaries** | MemoryWriteBarrier enforces these boundaries. Learning policy is a kernel-evaluated rule. |
| 13 | **Worker Autonomy Levels** | Autonomy level is a runtime configuration. Kernel authorization and risk rules are unaffected. |
| 14 | **Marketplace Package + Certification** | Certification uses the existing E0-E4 evidence framework. Kernel does not need to know about marketplace mechanics. |
| 15 | **Subscription / Entitlement Model** | Kernel only needs to know "is this deployment entitled to execute this capability?" Entitlement check is added to the authorization chain. |
| 16 | **Worker Management Settings** (spec F1–F6, F12, F16) | Pause, scheduled activation, assignment, workspace boundary, restrictions and operation quotas. Tenant/workspace pause is checked at S0.1 (S0–S11 ruling R-P) and again at S12 entry, never per step; worker checks are eligibility filters at worker selection; quota is consumed once per run at durable admission, tenant and workspace levels only (gate v10 C39). Settings changes affect new leases only (I-017). |
| 17 | **Batch Processing** (spec F9) | BATCH strategy producing ordinary PlanSteps at S9 (§15, gate v10 C40). Post-S15. |
| 18 | **Sub-Agent Delegation** (spec F7, F28) | Child workers get ⊆ parent capabilities and grants; PrincipalChain records the parent; replans and delegations are child executions (RD-11, RD-13). Post-S15. |
| 19 | **Runtime-Type Routing** (spec F19, F32–F36) | Adapters and bindings per runtime; same pipeline (I-029). Post-S15. |

Spec features map onto existing rows as follows: F10/F16 → #3; F33 skills → #5–#7; F22 PolicyEngine → #8; F20 autonomy → #13; F27 marketplace → #14; F26 plans/entitlements → #15.

### Architecture Acceptance Gate

Before any component moves to E2 (Contract Validated), it must pass all 7 acceptance criteria:

| Criterion | Requirement | Test |
|-----------|-------------|------|
| **A. Contract Complete** | All data contracts (inputs, outputs, errors) are specified | Contract test suite passes |
| **B. Invariant Preserved** | No implementation violates any I-001 through I-029 | `test_architecture_invariants()` |
| **C. State Machine Valid** | All state transitions are enumerated and valid | State transition test suite |
| **D. Failure Paths Covered** | Every failure mode has a defined handler | Negative-path matrix test |
| **E. Negative Path Tested** | Every failure path has a passing test | `test_negative_path_matrix()` |
| **F. Performance Contract** | Latency and throughput targets are defined and met | Performance benchmark suite |
| **G. Observability Complete** | Every critical path emits traceable events | Trace coverage analysis |

**Gate enforcement**: No component proceeds to E2 (Built) until ALL 7 criteria pass. CI enforces this gate on every pull request.

### Architecture Test Harness

The architecture test harness validates invariants and contracts at build time:

```python
class ArchitectureTestHarness:
    """Validates architecture invariants before implementation proceeds."""

    def test_all_invariants_hold(self) -> None:
        """I-001 through I-029 must all pass."""
        for invariant in ARCHITECTURE_INVARIANTS:
            assert invariant.validate(), f"{invariant.id} violated"

    def test_negative_path_matrix(self) -> None:
        """Every failure mode must have a defined handler."""
        for failure in NEGATIVE_PATH_MATRIX:
            assert failure.handler is not None

    def test_acceptance_gate(self) -> None:
        """A-G criteria must all pass."""
        for criterion in ACCEPTANCE_CRITERIA:
            assert criterion.passed(), f"{criterion.id} failed"

    def test_state_machine_coverage(self) -> None:
        """Every state transition must be reachable and valid."""
        for state_machine in STATE_MACHINES:
            assert state_machine.all_transitions_valid()
```

**CI enforcement**: `pytest tests/architecture/ -v` runs on every PR. Failure blocks merge.

### Worker Lifecycle Model

Five distinct concepts the architecture distinguishes:

```text
1. Worker Product
   What you sell in the marketplace.

2. Worker Definition
   The canonical specification: capabilities, skills, policies, artifacts, certification.

3. Worker Deployment
   A customer's installed and customized instance of a worker definition.

4. Worker Runtime
   The process/container actually executing.

5. Worker Execution
   One durable execution of a task through the kernel.
```

This gives the marketplace structure:

```text
                  MARKETPLACE
                      │
               Worker Product
                      │
                Worker Definition
                      │
               Worker Deployment
                      │
                Worker Runtime
                      │
               Worker Execution
```

> **Worker-management repair (RD-16):** the diagram's code fence was never closed, which swallowed the appendices when rendered.

## Appendix A: Document Relationships

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
| VALIDATION.md | All Tier 1-2 docs | M0 implementation |
| DATABASE.md | MASTER_ARCHITECTURE_FINAL.md | Implementation |

---

## Appendix B: Implementation Readiness Checklist

### M0 Complete When
- [ ] All Tier 1 documents are COMPLETE
- [ ] All Tier 2 documents (9-14) are COMPLETE
- [ ] Implementation passes all contract tests
- [ ] CI pipeline green
- [ ] All P0 conflicts resolved (see CRITICAL_FIXES.md and ARCHITECTURE_AUDIT.md)
- [ ] Architecture completeness verified (no missing contracts, no contradictions)
- [ ] Circuit breakers fully specified
- [ ] Durable event IDs specified

### M1 Complete When
- [ ] All Tier 1 and Tier 2 documents are COMPLETE
- [ ] Tier 3 documents (15-19) are COMPLETE
- [ ] Durable execution kernel implemented
- [ ] Worker identity system implemented
- [ ] Multi-tenant RLS verified
- [ ] Memory architecture (L0-L3) implemented
- [ ] A2A messaging with circuit breakers implemented

### M2+ Complete When
- [ ] All Tier 1-3 documents are COMPLETE
- [ ] Tier 4 documents (20-24) are COMPLETE
- [ ] Worker pools implemented
- [ ] Horizontal scaling verified
- [ ] Observability dashboard operational
- [ ] Work-stealing scheduler implemented
- [ ] AGENTIC path operational

---

## Appendix C: Reading Paths

### Path 1: Complete Understanding (New Team Member)
1. This document (FINAL_ARCHITECTURE.md)
2. DATA_CONTRACTS.md (focus on state machines)
3. PIPELINE_STAGES.md (focus on stage contracts)
4. COMPONENTS_BLUEPRINT.md (focus on directory structure)
5. EXECUTION_PLAN.md (focus on your module)

### Path 2: Implementation (Working on a specific area)

| Working On | Read These |
|------------|-----------|
| Pipeline stage | PIPELINE_STAGES.md → DATA_CONTRACTS.md → EXECUTION_PLAN.md |
| Provider adapter | PROVIDER_ADAPTERS.md → DATA_CONTRACTS.md → DATABASE.md |
| Mutation safety | MUTATION_SAFETY.md → PIPELINE_STAGES.md → RELIABILITY.md |
| Multi-tenancy | IDENTITY_AND_TENANCY.md → SECURITY.md → DATABASE.md |
| Skill system | SKILL_FACTORY_ARCHITECTURE.md → RESOLVE_LAYER.md → DATA_CONTRACTS.md |
| Human-in-the-loop | HUMAN_IN_THE_LOOP.md → PIPELINE_STAGES.md → MUTATION_SAFETY.md |
| Memory | MEMORY_ARCHITECTURE.md → DATA_CONTRACTS.md → DATABASE.md |
| Testing | VALIDATION.md → TRACING_AND_CONCURRENCY.md → EXECUTION_PLAN.md |
| Observability | TRACING_AND_CONCURRENCY.md → VALIDATION.md → EXECUTION_PLAN.md |
| Multi-agent | MULTI_AGENT_COORDINATION.md → MEMORY_ARCHITECTURE.md → IDENTITY_AND_TENANCY.md |

### Path 3: Security Review
1. SECURITY.md
2. IDENTITY_AND_TENANCY.md
3. MUTATION_SAFETY.md
4. HUMAN_IN_THE_LOOP.md
5. TRACING_AND_CONCURRENCY.md

---

## Appendix D: Glossary

| Term | Definition |
|------|------------|
| **Capability** | A contract defining what the system can do, with risk, cost, and mutation metadata |
| **Binding** | A mapping from a capability to a specific provider adapter |
| **Kernel Operation** | A specific operation exposed by a provider adapter |
| **ExecutionContext** | Frozen request state containing all non-LLM fields |
| **FrozenBindingIdentity** | Immutable binding selected at S5, used for entire execution |
| **Worker** | An AI agent with identity, lifecycle, memory, and execution context |
| **Pipeline Stage** | One of 15 stages in the request lifecycle |
| **Cordon Point** | A stage that can stop execution (short-circuit) |
| **Lease** | Time-bounded right for one Worker Runtime to execute a step for a Worker; a worker's usable leases never exceed its capacity |
| **Worker Runtime** | The running process/container that executes on behalf of Workers (§34); identified by `runtime_instance_id` |
| **Fence** | Monotonic token (one database sequence) preventing a stale owner's writes |
| **Probe** | Post-execution check to determine UNKNOWN outcome |
| **A2A** | Agent-to-agent communication |
| **HITL** | Human-in-the-loop |
| **RLS** | Row-level security (PostgreSQL) |
| **M0/M1/M2/M3/M4** | Milestone phases (Foundation, Execution, Scale, Intelligence, Ecosystem) |

---

**End of Final Architecture Document**

**Total Lines**: ~1,600
**Conflicts Resolved**: 20 (see CRITICAL_FIXES.md and ARCHITECTURE_AUDIT.md)
**Patterns Adopted**: 20 patterns from 10 repositories
**Status**: DESIGN_LOCKED — awaiting P0 resolution (23 items) and P1 resolution (33 items) per CRITICAL_FIXES.md and ARCHITECTURE_AUDIT.md
