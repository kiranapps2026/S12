# Adaptability Principles

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — all sections. [VOCABULARY_INDEX.md](VOCABULARY_INDEX.md) — canonical terminology. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — all contracts. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S0–S15. [RESOLVE_LAYER.md](RESOLVE_LAYER.md) — capability-driven resolution. [IDENTITY_AND_TENANCY.md](IDENTITY_AND_TENANCY.md) — identity hierarchy. [SECURITY.md](SECURITY.md) — authorization model. [RELIABILITY.md](RELIABILITY.md) — 5-layer guard. [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — worker lifecycle. [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — event ingress.
**Status**: DESIGN_PROPOSED
**Purpose**: Define the architectural principles that ensure SuprAgents can evolve as models, protocols, tools, and execution technologies change — without redesigning the core execution kernel.

---

## Core Principle

**Technology may change, but the SuprAgents execution contract, safety boundaries, identity, reliability, verification, and observability should remain stable.**

The objective is not to predict every future technology. It is to ensure that new technologies can be integrated through controlled extension points without modifying the kernel contracts.

---

## 1. Runtime Independence

Workers operate against a stable execution contract rather than depending directly on a specific LLM, agent framework, or runtime. New runtimes — Claude, OpenAI, Gemini, local models, browser agents, or future execution engines — are introduced through controlled runtime adapters.

| Existing contract | Role |
|-------------------|------|
| `BaseAdapter` (PROVIDER_ADAPTERS.md) | Adapter interface that all runtimes implement |
| `BindingRow` / `FrozenBindingIdentity` (DATA_CONTRACTS §6) | Runtime selection happens at S5 resolution, hardcoded at S6 |
| `kernel_ops` table (DATABASE.md) | Runtime/operation registry — new runtimes register here |
| WorkerIdentity (WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §3) | Worker does not reference a specific runtime |

**Invariant**: A Worker never depends directly on a specific model or agent runtime. The resolution layer selects the runtime at S5; the Worker only knows it has a capability.

---

## 2. Immutable Intent and Execution Contracts

User intent is transformed into a validated specification and then into a frozen execution plan and manifest. This separates *what the Worker must accomplish* from *how the system executes it*.

| Existing contract | Role |
|-------------------|------|
| `IntentResult` (PIPELINE_STAGES.md §4) | S2 output — what the user wants |
| `ExecutionManifest` (DATA_CONTRACTS §12) | S11 output — immutable execution truth |
| `FrozenBindingIdentity` (DATA_CONTRACTS §6) | S5 output — immutable provider/binding/risk/mutation |
| `ExecutionContext` (DATA_CONTRACTS §2) | S0 output — immutable execution context |

**Flow**:
```
User Intent
    ↓
Intent Specification (S2 IntentResult)
    ↓
Validated Specification (S7 PathRouting + S8 SafetyGate)
    ↓
Execution Plan (S9 Plan)
    ↓
Frozen Manifest (S11 ExecutionManifest)
```

The specification describes *what outcome is required*. The plan describes *how this particular execution will achieve it*. Implementation strategies can evolve without changing the specification.

---

## 3. Event-Sourced Execution

Every important execution transition produces an immutable, traceable event. This enables auditing, debugging, recovery, replay, and reconstruction of Worker behavior.

| Existing contract | Role |
|-------------------|------|
| `EventIdentity` (DATA_CONTRACTS §29) | Every event carries ordering metadata |
| `OutboxEvent` (DATA_CONTRACTS §28) | System-generated outbound events |
| `OutboxRecord` / `InboxRecord` (DATA_CONTRACTS §31) | Reliable delivery with at-least-once semantics |
| `audit_log` (DATABASE.md) | Immutable audit trail |
| `trace_id` (PIPELINE_STAGES.md §2) | Canonical correlation ID |

**Event types in the execution ledger** (extend as needed):

| Event | When emitted |
|-------|-------------|
| `ExternalEventReceived` | Event Gateway receives external event |
| `WorkerActivated` | Worker begins processing an execution |
| `PlanCreated` | S9 produces an ExecutionPlan |
| `StepStarted` | S12 begins a step |
| `ProviderCalled` | Adapter invokes provider |
| `StepCompleted` | S12 completes a step |
| `VerificationCompleted` | S13 completes verification |
| `OutcomeDelivered` | S15 delivers response |
| `WorkerWaiting` | Worker enters WAITING state (outcome loop) |

**Invariant**: The event ledger is append-only. Events are never modified or deleted. New event types can be added; existing types cannot change meaning.

---

## 4. Replay and Recovery

SuprAgents distinguishes replaying an execution from repeating an external mutation.

| Scenario | Approach |
|----------|----------|
| Replay execution from checkpoint | Restore state, re-execute from checkpoint |
| Re-execute external mutation | Use idempotency + probe verification — do NOT blindly repeat |

**Protection mechanisms** (all already exist in the architecture):

| Mechanism | Where defined |
|-----------|---------------|
| Checkpoint/resume | RELIABILITY.md §4, PIPELINE_STAGES.md S12 |
| Idempotency keys | DATA_CONTRACTS §26, PIPELINE_STAGES.md S0 |
| Provider probing | WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §6 |
| Lease/fencing | IDENTITY_AND_TENANCY.md §7, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §14 |
| UNKNOWN → PROBE resolution | STATE_TRANSITIONS.md §2, PIPELINE_STAGES.md S13 |

**Flow for unknown outcomes**:
```
Original execution
    ↓
External event #123
    ↓
Execution failed / outcome unknown
    ↓
Replay
    ↓
Reconstruct state from checkpoint
    ↓
Do NOT blindly repeat mutation
    ↓
Probe / idempotency verification
    ↓
Proceed or escalate
```

---

## 5. Progressive Verification

Results pass through increasingly strong verification stages. Not every execution needs the strongest verification.

| Level | Description | Where defined |
|-------|-------------|---------------|
| Level 1 — Schema validation | Output matches expected structure | DATA_CONTRACTS §24 ValidationResult |
| Level 2 — Deterministic business rules | Hard-coded rules (format, range, type) | SECURITY.md §4 |
| Level 3 — Provider/state verification | Independent observation of actual provider state | WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §6 |
| Level 4 — Semantic verification | LLM-based evaluation of result quality | PIPELINE_STAGES.md S13 |
| Level 5 — Human verification | Human-in-the-loop confirmation | PIPELINE_STAGES.md S10, MUTATION_SAFETY.md |

**Mapping to mutation safety classes**:

| Mutation class | Minimum verification level | Can escalate |
|----------------|---------------------------|-------------|
| READ | Level 1 | Yes |
| WRITE | Level 1 + Level 2 | Yes |
| DELETE | Level 1 + Level 2 + Level 3 | Yes |
| IRREVERSIBLE | Level 1 + Level 2 + Level 3 + Level 5 | No — Level 5 required |

**Invariant**: Verification level is determined by the `effective_mutation` field in `FrozenBindingIdentity` (set at S5). It cannot be escalated by the Worker or the LLM.

---

## 6. Bounded Decomposition

Complex tasks are decomposed only when necessary and within explicit limits. This prevents uncontrolled recursive planning.

| Existing contract | Role |
|-------------------|------|
| `Plan` (PIPELINE_STAGES.md §9) | S9 creates a plan with explicit step structure |
| `Step` (DATA_CONTRACTS §8) | Each step has defined input/output contract |
| `GraphClassification` (PIPELINE_STAGES.md §6) | S4 classifies as LINEAR, BRANCH, or GRAPH |
| AdmissionController (WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §10) | 11 gates evaluated before execution |

**Decomposition rules**:

| Rule | Rationale |
|------|-----------|
| Decompose only when evidence shows the unit is too large | Prevents unnecessary complexity |
| Each decomposed unit must be independently verifiable | Enables S13 verification at each level |
| Maximum decomposition depth: configurable per tenant | Prevents runaway recursion (default: 3) |
| Decomposition is deterministic, not LLM-driven | S4 GraphClassification determines structure |

**Flow**:
```
Business Objective
    ↓
Execution Unit
    ↓
Can this unit be independently verified?
    │
  NO → Decompose (deterministic, bounded)
    │
  YES
    ↓
Execute
    ↓
Verify
```

---

## 7. Adaptive Model and Runtime Routing

Model selection considers task complexity, cost, latency, reliability, and risk. Deterministic processing avoids unnecessary LLM usage.

| Routing dimension | Decision factor | Where evaluated |
|-------------------|-----------------|-----------------|
| Task complexity | Step count, dependency depth | S6 TaskProfile |
| Risk level | effective_risk from S5 | FrozenBindingIdentity |
| Cost | Model pricing, token estimates | RELIABILITY.md §6 BudgetTracker |
| Latency | Provider health, P99 metrics | PROVIDER_ADAPTERS.md §5 |
| Determinism | Can this be done without LLM? | S4 GraphClassification |

**Routing policy** (not part of the Resolve chain):

```
Simple task → cheaper model
Complex reasoning → stronger model
Structured transformation → Python/SQL processor
Deterministic operation → no LLM
Critical decision → stronger model + verification
```

**Invariant**: Model routing is an Execution Strategy policy, not part of the Capability Resolver. The resolver selects *what capability*; the execution strategy selects *which runtime*.

---

## 8. Protocol and Extension Independence

MCP and future protocols integrate through the existing capability, binding, and execution-endpoint abstractions — they do not become separate execution systems.

| Existing contract | Role |
|-------------------|------|
| `BaseAdapter` (PROVIDER_ADAPTERS.md) | All protocols implement this interface |
| `BindingRow` (DATA_CONTRACTS §6) | Maps capability → kernel_op → adapter_class |
| `kernel_ops` table (DATABASE.md) | Protocol operations registered here |
| `FrozenBindingIdentity` (DATA_CONTRACTS §6) | Protocol selection frozen at S5 |

**MCP integration** (bidirectional):

```
External MCP Server
    ↓
MCPAdapter (implements BaseAdapter)
    ↓
kernel_op with adapter_class = "MCPAdapter"
    ↓
S5 resolves → S6 binds → S12 executes
    ↓
Result verified at S13

AND

External Agent
    ↓
SuprAgents MCP Server (exposes certified capabilities)
    ↓
Authorized capability → existing Kernel
    ↓
Same S0–S15 execution path
```

**Invariant**: A new protocol is an adapter, not a new execution engine. It goes through the same S0–S15 pipeline, the same S8 Safety Gate, the same S13 verification.

---

## Design Rules

These rules apply to ALL future enhancements:

1. **No parallel execution paths** — everything feeds into S0
2. **No runtime-specific code in the kernel** — adapters isolate runtime dependencies
3. **No bypass of FrozenBindingIdentity** — S5 resolution is final
4. **No escalation of verification level by Worker or LLM** — S5 sets it, S13 enforces it
5. **All state in PostgreSQL** — no in-memory-only state that survives restarts
6. **All contracts are additive** — existing contracts are never modified, only extended

---

## Relationship to Ouroboros

SuprAgents shares architectural DNA with Ouroboros (immutable seeds, event-sourced execution, runtime abstraction, progressive verification) but diverges in one critical way:

| Dimension | Ouroboros | SuprAgents |
|-----------|-----------|------------|
| Execution kernel | Monolithic agent runtime | 15-stage pipeline with frozen bindings |
| Runtime binding | Runtime selects tools | S5 resolution selects runtime, S6 freezes it |
| Verification | Post-execution evaluation | S13 independent verification before acceptance |
| Event model | Internal event store | External + internal events through unified Event Gateway |
| Tenant isolation | Not a first-class concern | RLS at PostgreSQL level, three canonical roles |
| Mutation safety | Not architecturally enforced | MUTATION_SAFETY.md — READ/WRITE/DELETE/IRREVERSIBLE classes |

SuprAgents extracts the runtime abstraction, immutable specification, and progressive verification primitives from Ouroboros without adopting its monolithic runtime model.

---

## Implementation Sequence

These principles are not implemented all at once. They are realized progressively:

| Principle | M0 | M1 | M2 | M3 |
|-----------|----|----|----|-----|
| Runtime independence | Provider adapters | MCP adapter | Browser adapter | Future adapters |
| Immutable contracts | ExecutionManifest | FrozenBindingIdentity | Intent Specification | Full lifecycle |
| Event-sourced execution | Outbox/Inbox | Event Gateway | Event ledger extension | Full ledger |
| Replay/recovery | Checkpoint/resume | Idempotency | Probe verification | Full replay |
| Progressive verification | S13 Level 1-2 | Level 3 provider verification | Level 4 semantic | Level 5 HITL |
| Bounded decomposition | S4 GRAPH classification | Deterministic split | Skill/Workflow layer | Full decomposition |
| Adaptive routing | S5 provider selection | Cost-aware routing | Model selection policy | Full strategy |
| Protocol independence | BaseAdapter | MCP adapter | MCP server exposure | Multi-protocol |

---

*End of Adaptability Principles.*
