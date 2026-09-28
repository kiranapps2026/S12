# Pipeline Stages

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §6 Request Lifecycle, §10 Execution Safety, §12 Reliability, §15 Observability. [IDENTITY_AND_TENANCY.md](IDENTITY_AND_TENANCY.md) — identity model, principal chain. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §5 ExecutionContext, §9 Step, §9 ExecutionResult, §9 ExecutionStatus, §9 ExecutionOutcome, §22 RetryDecision, §19 StepState, §17 IdempotencyKey, §20 BudgetStates. [RESOLVE_LAYER.md](RESOLVE_LAYER.md) — resolution chain. [STATE_TRANSITIONS.md](STATE_TRANSITIONS.md) — all state machine definitions. [SECURITY.md](SECURITY.md) — §3 Authorization Model, §10 Guardrail Precedence. [MUTATION_SAFETY.md](MUTATION_SAFETY.md) — mutation safety rules, confirmation requirements. [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — worker lifecycle, independent verification, admission control, state locality.
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [S0 — Entry](#2-s0--entry)
3. [S1 — Normalize](#3-s1--normalize)
4. [S2 — Intent Analysis](#4-s2--intent-analysis)
5. [S3 — Capability Discovery](#5-s3--capability-discovery)
6. [S4 — Graph Classification](#6-s4--graph-classification)
7. [S5 — Provider Resolution](#7-s5--provider-resolution)
8. [S6 — Task Profile Assembly](#8-s6--task-profile-assembly)
9. [S7 — Path Routing](#9-s7--path-routing)
10. [S8 — Safety Gate](#10-s8--safety-gate)
11. [S9 — Plan Creation](#11-s9--plan-creation)
12. [S10 — Confirmation](#12-s10--confirmation)
13. [S11 — Plan Validation](#13-s11--plan-validation)
14. [S12 — Execute with Reliability Guard](#14-s12--execute-with-reliability-guard)
15. [S13 — Validate Result](#15-s13--validate-result)
16. [S14 — Dead Letter](#16-s14--dead-letter)
17. [S15 — Response Formatting](#17-s15--response-formatting)
18. [Short-Circuit Paths Summary](#18-short-circuit-paths-summary)
19. [Negative-Path Matrix](#19-negative-path-matrix)
20. [No Silent Success Invariant](#20-no-silent-success-invariant)
21. [Execution Strategy Selection (CODE-PROVEN)](#21-execution-strategy-selection-code-proven)
22. [A2A Communication Semantics (CODE-PROVEN)](#22-a2a-communication-semantics-code-proven)

---

## 1. Pipeline Overview

### Request Flow Diagram

```
User Message (terminal)
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│                      PIPELINE EXECUTION                            │
│                                                                   │
│  S0  Entry ──────→ S1  Normalize ──────→ S2  Intent Analysis     │
│                                               │                   │
│                                               ▼                   │
│  S3  Capability Discovery ←── S4  Graph Classification           │
│       │                    ←── S5  Provider Resolution             │
│       │                    ←── S6  Task Profile                    │
│       ▼                                                           │
│  S7  Path Routing ──→ CLARIFY ──→ S15 Response                   │
│       │               DENY ──→ S15 Response                       │
│       │               FAST ──→ S8 Safety Gate ──→ S9 Plan        │
│       │               WORKFLOW ──→ S8 ──→ S9 Plan                │
│       │               AGENTIC ──→ S8 ──→ S9 Plan                 │
│       ▼                                                           │
│  S8  Safety Gate ──→ DENY ──→ S15 Response                        │
│       │                                                           │
│       ▼                                                           │
│  S9  Plan Creation                                                │
│       │                                                           │
│       ▼                                                           │
│  S10 Confirmation (if D/IRREVERSIBLE) ──→ wait for user           │
│       │                                                           │
│       ▼                                                           │
│  S11 Plan Validation ──→ INVALID ──→ S15 Response                 │
│       │                                                           │
│       ▼                                                           │
│  S12 Execute with Guard                                            │
│       │                                                           │
│       ▼                                                           │
│  S13 Validate Result                                              │
│       │                                                           │
│       ▼                                                           │
│  S14 Dead Letter (if failures)                                     │
│       │                                                           │
│       ▼                                                           │
│  S15 Response Formatting ──→ terminal Message                     │
└───────────────────────────────────────────────────────────────────┘
```

### Stage Contract

Every stage follows this contract:

> **S12–S15 gate v9 repair (C38):** historical. The certified S0–S11 implementation replaced
> `StageResult` with the typed `PipelineState`: each stage handler is
> `async def handle(state: PipelineState) -> PipelineState` and writes only its own output
> through `with_stage_output()`; short-circuits use `StageStatus`. S12–S15 stages follow the
> same pattern. `StageResult` must not be reintroduced (the S0–S11 certifier fails on it).

```python
@dataclass(frozen=True)
class StageResult:
    can_short_circuit: bool           # If True, stop pipeline
    short_circuit_value: Any | None   # Value to return if short-circuiting
    next_stage: str | None            # Next stage to execute (None = default)
    context_updates: dict             # Updates to execution context
    metadata: dict                    # Additional metadata
    error: str | None                 # Error message if stage failed (None = success)
    trace_events: list                # TraceEvent list to append to trace

# Canonical short-circuit enum (matches DATA_CONTRACTS StageStatus):
# NORMAL, CLARIFY, DENY, ERROR, PROBE
```

### Cordon Points (Execution Stops)

These stages can stop execution (short-circuit):

| Stage | Name | Stop Condition | Envelope Status |
|-------|------|----------------|-----------------|
| S2 | Normalize | CLARIFY needed | `clarify` |
| S2 | Normalize | DENY (refusal) | `deny` |
| S7 | Path Routing | CLARIFY needed | `clarify` |
| S7 | Path Routing | DENY | `deny` |
| S8 | Safety Gate | Any check fails | `error` |
| S9 | Task Profile | CLARIFY needed | `clarify` |
| S10 | Confirmation | User rejects | `error` |
| S10 | Confirmation | Token expires | `error` |
| S11 | Plan Validation | Invalid plan | `error` |
| S13 | Result Validation | CLARIFY needed | `clarify` |
| S13 | Result Validation | DENY | `deny` |

---

## 2. S0 — Entry

**Purpose**: Receive the incoming request, generate identifiers, set up execution context.

**Input**: Terminal message (text, callback, etc.) or `EventEnvelope` (event-driven mode)

**Output**: `ExecutionContext` with generated IDs

**Actions**:
1. Determine activation mode: HUMAN, SCHEDULE, API, EVENT_DRIVEN, or INTERNAL
2. Generate `trace_id` (UUID v4) — canonical correlation ID for the entire request lifecycle
3. Generate `request_id` (UUID v4) — identifies this specific incoming request
4. Extract `conversation_id` from terminal chat or `EventEnvelope.correlation_id`
5. Look up `user_id` and `tenant_id` from connection (HUMAN/SCHEDULE/API) or Event Gateway auth (EVENT_DRIVEN)
6. Set `connection_id` from terminal user or subscription
7. Create immutable `ExecutionContext`

**Event-Driven Mode (EVENT_DRIVEN)**:
- Input: `EventEnvelope` created by the Event Gateway
- `event_id` → `task_id`
- `correlation_id` → `trace_id`
- `payload_ref` → `context_snapshot`
- `tenant_id` comes from Event Gateway authentication context (HMAC credential lookup), NEVER from the event payload
- All downstream stages (S1–S15) are identical to human-driven mode

**Cautions**:
- S0 accepts a normalized inbound request contract. Host-specific payload shapes
  are normalized before S0, not inside it. S0 operates on the normalized contract
  only.
- COMPONENTS_BLUEPRINT rule: `servers/` contains no business logic. Inbound
  normalization belongs outside S0; S0 receives the already-normalized contract.
- This is transport normalization (host payload → inbound contract). Content normalization and sanitization remain S1's responsibility.
- `trace_id` and `request_id` MUST be generated by the system, NOT from user input or event payload
- `trace_id` is the canonical identity — `correlation_id` is a deprecated alias for backward compatibility only
- `user_id` MUST come from authentication, NOT from LLM output or event payload
- This is the ONLY place `trace_id` and `request_id` are created — they are immutable thereafter
- `task_id` is generated later at S2 (or set from `EventEnvelope.event_id` in EVENT_DRIVEN mode)
- `execution_id` and `plan_id` are generated at S9

**See**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) §12 for S0 integration details.

---

## 3. S1 — Normalize

**Purpose**: Clean the user's message, resolve references, extract structured data, detect injection.

**Input**: Raw user message text, `ExecutionContext`

**Output**: `NormalizedInput`

```python
@dataclass(frozen=True)
class NormalizedInput:
    text: str                       # Cleaned, sanitized text
    entities: dict[str, Any]        # Extracted entities (dates, names, etc.)
    references: dict[str, str]      # $ref → resolved value
    injection_detected: bool
    injection_patterns: list[str]
```

**Actions**:
1. Trim whitespace, normalize unicode
2. Resolve `$ref` references (e.g., "$1" → previous result)
3. Resolve `$file` references (e.g., "$file:invoice.pdf")
4. Resolve `{{template}}` expressions
5. Extract mentioned entities (dates, contact names, file names)
6. Run DataSanitizer on input (detect prompt injection)

**Short-Circuit Paths**:

| Decision | Next Stage | User Sees |
|----------|-----------|-----------|
| CLARIFY | S15 | "Can you tell me more about...?" |
| DENY | S15 | "I can't do that because..." |

**Cautions**:
- **ALWAYS run DataSanitizer on user input** before passing to LLM
- If injection detected: log warning, sanitize text, flag for review — but DON'T block unless severity is high
- Never trust resolved references without validation
- If `UnresolvedReference` → CLARIFY
- If high-severity injection → DENY (safety gate at S8 is the enforcement point)

---

## 4. S2 — Intent Analysis

**Purpose**: Understand what the user wants. This is the **ONE and ONLY unconditional LLM call** per request. No other stage re-queries the LLM.

**Input**: Normalized user text, `ExecutionContext`

**Output**: `IntentResult`

```python
@dataclass(frozen=True)
class IntentResult:
    intent: str                # e.g., "contact_create"
    entities: dict[str, Any]   # e.g., {"name": "John", "email": "john@example.com"}
    confidence: float          # 0.0 to 1.0
    parameters: dict[str, Any] # Extracted parameters
    raw_response: str          # Raw LLM response for debugging
    task_id: str               # Generated at S2 — links intent to execution chain
```

**Actions**:
1. Build system prompt with available capabilities
2. Call LLM with structured output schema
3. Validate LLM response against schema
4. If validation fails, retry once with error feedback
5. Map returned intent to internal capability names
6. Calculate confidence score
7. Generate `task_id` (UUID v4) — ties this intent analysis to the broader execution chain

**LLM Call**:
```python
response = llm.call(
    system_prompt=INTENT_SYSTEM_PROMPT,
    user_message=normalized.text,
    response_schema=IntentResultSchema,
    max_tokens=500,
    temperature=0.1  # Low temperature for deterministic output
)

# [BILLING] Record LLM token consumption for internal infrastructure billing
# This is an LLM call, NOT a provider API call. Resource type is "llm.token".
billing.record_usage(
    tenant_id=execution_context.tenant_id,
    user_id=execution_context.user_id,
    resource_type="llm.token",     # LLM internal consumption (not provider API)
    quantity=response.usage.total_tokens,
    unit="token",
    kernel_op_ref="llm.intent_analysis",  # Internal kernel op for LLM
    evidence_ref=execution_context.trace_id,
    metadata={"model": response.model, "provider": response.provider}
)
```

**Errors**:

| Error | Cause | Recovery |
|-------|-------|----------|
| LowConfidence | confidence < 0.5 | Route to CLARIFY |
| ValidationError | LLM output doesn't match schema | Retry once, then CLARIFY |
| LLMUnavailable | LLM API down | Error message, suggest retry |

**Cautions**:
- **ONLY unconditional LLM call.** All other LLM calls are conditional (only in AGENTIC path).
- ALWAYS validate LLM output against schema. Never trust raw LLM output.
- Confidence threshold: if < 0.5, route to CLARIFY rather than guessing.
- Temperature MUST be low (0.1) for deterministic intent classification.
- **Never use LLM output to populate ExecutionContext fields.**

---

## 5. S3 — Capability Discovery

**Purpose**: Map the user's intent to one or more system capabilities.

**Input**: `IntentResult` from S2, `ExecutionContext`

**Output**: `CapabilityMatch`

```python
@dataclass(frozen=True)
class CapabilityMatch:
    capabilities: list[Capability]
    primary_capability: Capability | None
    match_quality: str    # "exact" | "fuzzy" | "none"
```

**Actions**:
1. Look up intent in CapabilitySpine
2. For each matched capability, retrieve metadata
3. Build list of candidate capabilities
4. Filter by truth state (only PRODUCTION_ENABLED for execution)

**Errors**:

| Error | Cause | Recovery |
|-------|-------|----------|
| NoCapabilityFound | No capability matches intent | Route to CLARIFY |
| CapabilityNotEnabled | Matched capability not PRODUCTION_ENABLED | Route to CLARIFY with suggestion |

**Cautions**:
- Only PRODUCTION_ENABLED capabilities are eligible for execution
- DISCOVERED/LIVE_VERIFIED/CERTIFIED capabilities can be shown but not executed
- If match_quality is "fuzzy", include confidence in the clarify message

---

## 6. S4 — Graph Classification

**Purpose**: Determine the complexity of the task by analyzing capabilities and their dependencies.

**Input**: `CapabilityMatch` from S3, `ExecutionContext`

**Output**: `GraphAnalysis`

```python
@dataclass(frozen=True)
class GraphAnalysis:
    graph_type: str            # "simple" | "chain" | "complex"
    step_count: int
    dependency_graph: dict     # {step_id: [dependent_step_ids]}
    parallelism_opportunity: int
```

**Actions**:
1. Count the number of steps (capabilities x parameters)
2. Analyze dependencies between capabilities
3. Determine graph type

**Decision Rules**:

| Steps | Dependencies | Graph Type |
|-------|-------------|------------|
| 1 | None | Simple |
| 2-5 | Linear (each depends on previous) | Chain |
| 2-5 | Some parallel | Chain |
| 5+ | Any | Complex |

**Cautions**:
- Graph type affects planner selection
- Dependency analysis must account for parameter dependencies
- Parallelism opportunity affects estimated execution time

---

## 7. S5 — Provider Resolution

**Purpose**: Determine which provider(s) can execute each capability.

**Input**: `CapabilityMatch` from S3, `GraphAnalysis` from S4, `ExecutionContext`

**Output**: `FrozenBindingIdentity`

```python
@dataclass(frozen=True)
class ProviderResolution:
    """Intermediate resolution result — feeds into FrozenBindingIdentity."""
    bindings: dict[str, BindingRow]  # capability → binding
    unavailable: list[str]           # capabilities with no provider
    providers_used: list[str]

@dataclass(frozen=True)
class FrozenBindingIdentity:
    """The immutable binding identity — frozen at S5, never changes.

    This is the ONLY binding information S12 receives — it can NEVER
    re-resolve or swap providers mid-execution.
    """
    binding_id: str                  # Selected binding row ID
    capability_id: str               # Matched capability
    kernel_op_id: str                # The kernel operation to call
    provider: str                    # Provider prefix (e.g., "ghl_public")
    engine_module: str               # Python module path (e.g., "supr.kernel.engines.ghl")
    adapter_class: str               # Adapter class (e.g., "GHLPublicAdapter")
    effective_risk: float            # Risk computed from TaskProfile at S5
    effective_mutation: str          # Mutation type computed from TaskProfile at S5
    resolved_at_stage: str           # Always "S5"
    selection_rank: int              # Tie-breaker rank (lower = selected)
```

**Actions**:
1. For each capability from S3, look up available bindings in registry
2. Apply deterministic selection: `priority ASC → created_at ASC → binding_id ASC`
3. Build `FrozenBindingIdentity` with selected binding + risk/mutation from TaskProfile
4. If any capability has no available binding → short-circuit to CLARIFY

**Errors**:

| Error | Cause | Recovery |
|-------|-------|----------|
| NoProviderAvailable | No provider for a capability | Route to CLARIFY or DENY |

**Cautions**:
- Multiple capabilities might use the same provider — plan for connection pooling
- Circuit breaker state affects provider availability
- User might have credentials for one provider but not another

### Frozen Binding Identity (CRITICAL — from forensic audit)

Once S5 completes, the resolved binding is **immutable** for the rest of this execution. The `FrozenBindingIdentity` produced at S5 becomes the **authoritative binding identity** for S12.

**Rules**:
1. S12 receives `FrozenBindingIdentity` — it does NOT re-resolve the binding
2. If the binding is invalid at execution time, the step fails — it does NOT re-resolve
3. All step results must persist `resolved_binding_id` from this frozen identity
4. If `resolve_binding()` fails at S5, the execution does NOT proceed — route to CLARIFY or DENY

### Temporal Dependency: effective_risk and effective_mutation (CRITICAL)

**FIXED**: S5 computes `effective_risk` and `effective_mutation` from capability metadata, kernel metadata, and deterministic contextual inputs available at S5 — NOT from S6's TaskProfile. S6 is a downstream consumer of these frozen values.

**Source inputs for S5 risk/mutation computation**:
- `capability.risk_floor` (from capability metadata)
- `capability.mutation` (from capability metadata)
- `kernel_op.risk_floor` (from kernel operation metadata)
- Tag-implied risk (from normalized input tags)
- Tenant/workspace risk policy (from ExecutionContext)

**Formula**: `effective_risk = max(capability.risk_floor, kernel_op.risk_floor, tag_implied_risk)`

These values are baked into `FrozenBindingIdentity` and never recomputed. Downstream stages (S6-S15) consume these frozen values, ensuring the risk/mutation used for safety decisions at S8 and execution at S12 is the same value that was used to select the binding at S5.

> **Note**: S5 computes effective_risk and effective_mutation once. All downstream stages (S6-S15) consume these frozen values.

**Invariant**: No stage after S5 recomputes risk or mutation.

---

## 8. S6 — Task Profile Assembly

**Purpose**: Build the complete task profile with risk, cost, mutation, and security analysis.

**Input**: `CapabilityMatch`, `GraphAnalysis`, `ProviderResolution`, `ExecutionContext`

**Note**: effective_risk and effective_mutation are consumed from S5 `FrozenBindingIdentity`, not recomputed. S5 computed effective_risk and effective_mutation from capability metadata, kernel metadata, and deterministic contextual inputs available at S5. S6 receives them via the `FrozenBindingIdentity` from `ProviderResolution`.

**Output**: `TaskProfile`

```python
@dataclass(frozen=True)
class TaskProfile:
    intent: str
    capabilities: list[Capability]
    graph_type: str
    steps_estimated: int
    mutations: list[str]
    risk: float              # 0.0-1.0 (max of all steps) — computed by S5, consumed here
    cost: int                # Total budget cost
    requires_confirmation: bool
    resource_scope: str
    providers: list[str]
```

**Risk Calculation** (performed by S5, referenced here):

```python
def calculate_risk(profile: TaskProfile) -> float:
    """Risk only goes up — max of all contributing factors.
    Computed by S5, stored in FrozenBindingIdentity.effective_risk.
    """
    risk_floor = max(step.risk_floor for step in profile.steps)
    risk_rule = max(step.risk_rule for step in profile.steps)
    risk_implied = max(step.risk_implied for step in profile.steps)
    return max(risk_floor, risk_rule, risk_implied)
```

**Invariant**: No stage after S5 recomputes risk or mutation. S5 computes `effective_risk` and `effective_mutation` once. All downstream stages (S7-S15) consume these frozen values from `FrozenBindingIdentity`.

**Confirmation Rules**:

| Condition | Requires Confirmation |
|-----------|----------------------|
| Any IRREVERSIBLE mutation | YES |
| Any D mutation with cost > 5 | YES |
| Total cost > 20 | YES |
| Total risk > 0.7 | YES |
| Cross-provider (3+ providers) | YES |

**Cautions**:
- Risk formula: `final_risk = max(risk_floor, risk_rule, risk_implied)` — risk only goes up
- Confirmation uses OR logic — any condition triggers it
- Budget check at this stage prevents wasting resources

---

## 9. S7 — Path Routing

**Purpose**: Determine the execution path for this request.

**Input**: `TaskProfile`, `ExecutionContext`

**Output**: `PathDecision`

**Decision Matrix**:

| Confidence | Graph Type | Risk | Path |
|------------|-----------|------|------|
| >= 0.9 | Simple | <= 0.3 | FAST |
| >= 0.7 | Chain | <= 0.5 | WORKFLOW |
| Any | Complex | Any | CLARIFY ("Complex tasks coming in M2") |
| < 0.5 | Any | Any | CLARIFY |
| Any | Any | > threshold | DENY |
| — | No capability | — | CLARIFY |

> **M0/M1**: Only FAST and WORKFLOW paths are active. AGENTIC path is stubbed — routes to CLARIFY. AGENTIC-specific fields (`branch_id`) in Plan are reserved for M2.

**Short-Circuit Paths**:

| Decision | Next Stage | User Sees |
|----------|-----------|-----------|
| CLARIFY | S15 | "Can you tell me more about...?" |
| DENY | S15 | "I can't do that because..." |

**Cautions**:
- CLARIFY should provide specific questions
- DENY should explain WHY — not just say no
- PATH decisions are logged for routing optimization

---

## 10. S8 — Safety Gate

**Purpose**: The primary security boundary. Every execution passes through these checks.

**Input**: `PathDecision`, `TaskProfile`, `ExecutionContext`

**Output**: `SafetyResult`

```python
@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    reason: str | None = None
    failed_check: str | None = None
```

**Checks (ALL must pass)**:

| # | Check | Fails → |
|---|-------|---------|
| 1 | User active | DENY |
| 2 | Tenant active | DENY |
| 3 | Connection active | DENY |
| 4 | Capability granted | DENY |
| 5 | Resource scope | DENY |
| 6 | Circuit breaker | DENY |
| 7 | Budget available | DENY |
| 8 | Mutation safety | DENY |

**Budget precheck**:

At S8, the safety gate **verifies** that `budget_remaining >= task_cost`. This is a precheck only — budget is NOT reserved here. Reservation happens exclusively at S12 Execute with Reliability Guard.

**Cautions**:
- **FAIL-CLOSED**: If any check can't make a decision, DENY
- **NO LLM in this path** — every check is deterministic
- Every rejection has a specific reason
- Budget precheck HERE prevents wasting resources on plans that can't execute

---

## 11. S9 — Plan Creation

**Purpose**: Build an executable plan from the task profile.

**Input**: `TaskProfile`, `PathDecision` (planner type), `ProviderResolution`, `ExecutionContext`

**Output**: `Plan`

```python
@dataclass(frozen=True)
class Plan:
    id: str                    # plan_id — UUID generated at S9
    execution_id: str          # execution_id — UUID generated at S9
    branch_id: str | None      # branch_id — set for AGENTIC path (branch exploration); None for FAST/WORKFLOW
    steps: list[Step]
    join_mode: str           # "all" | "any" | "threshold"
    budget_required: int      # Budget needed (not reserved — reservation at S12 only)
    created_at: float
    confirmations: list[str]
```

**Actions**:
1. Generate `execution_id` (UUID v4) — unique execution instance
2. Generate `plan_id` (UUID v4) — ties plan to the execution
3. For AGENTIC path: generate `branch_id` (UUID v4) — identifies this exploration branch
4. Select planner based on path decision
5. Build step graph with dependencies
6. Validate plan (acyclic, budget, bindings)
7. **Compute plan_hash** — SHA-256 of the frozen Plan object (this is the authoritative binding for confirmation)
8. Freeze the Plan — it cannot change after this point without invalidating confirmation

**Cautions**:
- `execution_id` and `plan_id` are generated ONLY at S9, not before
- `branch_id` is only set for AGENTIC path; FAST and WORKFLOW have a single linear path with no branching
- MAX_STEPS = 10 hard limit for agentic planning
- Dependency graph must be acyclic — reject circular deps
- Plan is frozen at S9 with plan_hash — confirmation at S10 binds to this hash
- **S9 does NOT reserve budget.** Budget reservation happens only at S12 Execute with Reliability Guard. The `budget_required` field records the estimated cost; actual reservation occurs atomically at execution start.

### Step Output and Parameter Binding (Multi-Step Execution)

```python
@dataclass(frozen=True)
class StepOutputReference:
    """Reference to a specific output from a previous step."""
    step_id: str                    # Which step produced this output
    output_field: str               # Which field in the step's result
    field_type: str                 # Expected type for validation

@dataclass(frozen=True)
class StepParameterBinding:
    """Binds a step's input parameter to a previous step's output."""
    step_id: str                    # Target step
    parameter: str                  # Target parameter name
    source: StepOutputReference     # Where the value comes from
```

**Data Flow Validation** (all must pass):
1. Referenced step exists in the plan
2. Output field exists in referenced step's result schema
3. Types match: `source.field_type == parameter.type`
4. Tenant/workspace remains identical across steps
5. Secret data cannot flow into unsafe destinations (secrets never in step output)
6. Dependency graph is acyclic

**Execution**: Steps execute in topological order. Each step's output becomes the next step's input via the binding. Parallel steps (no dependency between them) execute concurrently.

---

## 12. S10 — Confirmation

**Purpose**: Present D/IRREVERSIBLE operations to the user for explicit approval.

**Input**: `Plan`, `ExecutionContext`

**Output**: Confirmation token or proceed signal

**Actions**:
1. Scan plan for D/IRREVERSIBLE mutations
2. If found:
   - Generate confirmation token
   - Build confirmation message with operation summary
   - Store token in database with expiry (5 minutes)
   - Return ENVELOPE(status="confirm", ...)
   - Wait for user callback
3. If user confirms: consume token (single-use, atomic), proceed to S11
4. If user rejects: mark token as rejected, route to S15
5. If token expires: route to S15

**Confirmation Message Format**:

```
This will:
1. Delete contact "John Doe" from GHL
2. Remove 3 tags from their profile

Total operations: 2 (Dangerous)
Cost: 8 units

Reply YES to confirm or NO to cancel.
```

**Rules**:

| Rule | Implementation |
|------|---------------|
| Single-use | Token consumed atomically on first use |
| Time-limited | Expires after 5 minutes (300 seconds) |
| User-bound | Token tied to user_id + conversation_id |
| Specific | Message lists exact operations |

**Cautions**:
- **NEVER execute D/IRREVERSIBLE operations without confirmation**
- If confirmation times out, the plan is discarded
- The confirmation message must list EXACTLY what will happen

### Durable Pending Confirmation (FROZEN CONTRACT)

S10 is a potential interruption point. The user must respond. Worker may disappear.
A durable `pending_confirmations` table ensures re-entry is safe.

**Schema** (in `DATABASE.md`):
```sql
CREATE TABLE pending_confirmations (
    confirmation_id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES execution_manifests(execution_id),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    plan_hash TEXT NOT NULL,
    confirmation_message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected | expired
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMP
);
CREATE INDEX idx_confirmations_execution ON pending_confirmations(execution_id);
```

**Re-entry Protocol**:
1. User replies to confirmation message → match by `execution_id + confirmation_message_hash`
2. Atomic: `UPDATE pending_confirmations SET status='confirmed' WHERE confirmation_id=? AND status='pending'`
3. If updated row count == 0: token already consumed, expired, or rejected → check new state
4. S10 never trusts in-memory state — always re-read from database

**Concurrency Rules**:
- A user may have N pending confirmations (one per conversation)
- Each confirmation is single-use (atomic consume)
- Expired confirmations are swept by background job
- On worker restart: resume pending confirmations from DB, NOT from memory

### Plan Immutability After S10 (CRITICAL — from forensic audit)

Once confirmation is received at S10, the plan is **frozen**. Any change to the plan after confirmation **invalidates the confirmation** and requires re-confirmation.

| Event | Action |
|-------|--------|
| Plan changes after S10 confirmation | Invalidate confirmation token, re-build plan, re-confirm |
| Step added/removed/modified after S10 | Same — invalidate and restart from S9 |
| Binding resolution changes after S10 | Invalidates plan — confirm new bindings |
| Risk increases after S10 | Re-evaluate confirmation requirements |
| Cost increases after S10 | If over user's budget, invalidate |

```python
class PlanFreeze:
    """Manages plan immutability after confirmation."""
    
    def __init__(self):
        self._plan_hash: str | None = None
        self._confirmed: bool = False
    
    def freeze(self, plan: Plan) -> None:
        """Freeze plan after S10 confirmation."""
        self._plan_hash = self._compute_hash(plan)
        self._confirmed = True
    
    def check(self, plan: Plan) -> bool:
        """Check if plan is still the same. Returns True if frozen and unchanged."""
        if not self._confirmed:
            return True  # Not frozen yet — allowed
        current_hash = self._compute_hash(plan)
        if current_hash != self._plan_hash:
            raise PlanMutationError("Plan changed after confirmation — re-confirm required")
        return True
```

---

## 13. S11 — Plan Validation

**Purpose**: Final validation of the plan before execution.

**Input**: Validated `Plan`, `ExecutionContext`

**Output**: Validation result or error

**Validation Checks**:

| Check | Fail → |
|-------|--------|
| Circular dependency | INVALID |
| Missing binding | INVALID |
| Parameter mismatch | INVALID |
| Budget exceeded | DENY |
| Timeout exceeded | INVALID |

**Actions**:
1. Validate plan completeness (all steps have bindings, all params valid)
2. Verify the S9-authoritative SHA-256 `plan_hash` against the canonical plan representation received at S11
3. Create ExecutionManifest with all version stamps
4. Persist frozen manifest to `execution_manifests` table

**Output**: Frozen `ExecutionManifest` (stored in `execution_manifests` table), `Plan` (frozen with plan_hash)

**Cautions**:
- Pre-resolving bindings at this stage catches issues before expensive execution
- Budget check at S11 is informational only — the authoritative atomic reservation happens at S12
- Plan is frozen here — any change after this point invalidates confirmation
- Confirmation was already consumed at S10; S11 does NOT re-verify it

---

## 14. S12 — Execute with Reliability Guard

**Purpose**: Execute the plan through the 5-layer reliability guard. S12 is the ONLY stage that reserves budget.

**Input**: Validated `Plan`, `ExecutionContext`

**Output**: `ExecutionResult`

> **S12–S15 gate v9 repair (C3, C4, C11, C17, C30, C31, C35):** The normative per-step sequence is S12_S15_EXECUTION_GATE §8. In short: live authorization check → admission → worker selection → lease → budget reserve (per step) → pre-flight → step RUNNING + budget LOCKED → live check → idempotency lookup → dispatch marker → adapter call through the guard (components by name: Bulkhead, CircuitBreaker, BudgetTracker check, RetryStormGuard, TimeoutManager) → verification → COMPLETED + COMMITTED, or FAILED + RELEASED → checkpoint → lease release. Steps run in topological order of `depends_on`; admission QUEUE and lease failure are retried, never skipped. Uncertain outcomes go RUNNING → PENDING_PROBE (not UNKNOWN). The list below is historical where it differs.

**Actions**:

```
For each step in execution order (respecting dependencies):
1. ADMISSION       → ACCEPT / QUEUE / REJECT / DEGRADE (see WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §10-11)
   Admission is stateless — no budget reserved, no lease acquired.
   If REJECT → FAIL the execution
   If QUEUE/DELAY → retry after retry_after_ms
2. WORKER SELECT   → Choose worker via state locality scoring (if ACCEPT)
   See WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §13 for scoring weights
3. LEASE           → Acquire lease on chosen worker (fencing token)
   If lease fails → retry step
4. BudgetReserver.reserve(step_cost) — atomically transition PENDING → RESERVED
   If budget cannot be reserved → FAIL, release lease
5. PRE-FLIGHT       → Validate params, check scope
6. Layer 1: Circuit breaker check
7. Layer 2: Retry storm guard check
8. EXECUTE         → Run step via adapter (through 5-layer reliability guard)
   Layer 3: Timeout handling (UNKNOWN, not FAILED)
   Layer 4: Record health
   Layer 5: Record billing (see RELIABILITY.md §1)
9. CHECKPOINT      → Save state after step
10. VERIFY (S13)   → Independent verification for W/D/IRREVERSIBLE mutations
    See WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §6-9
    If verification FAILS → mark step FAILED, release budget
    If verification UNKNOWN → step enters UNKNOWN, PENDING_PROBE cycle
11. On UNKNOWN (timeout) — State Machine (per STATE_TRANSITIONS.md):
    Step enters UNKNOWN → PENDING_PROBE → (probe) → RECONCILING
    RECONCILING resolves to:
      CONFIRMED_SUCCESS → step.state = COMPLETED, commit budget
      CONFIRMED_FAILURE → step.state = FAILED, release budget, trigger retry or rollback
      PENDING_PROBE (inconclusive) → retry probe or DEAD_LETTER after max attempts
12. On failure (confirmed):
    a. Check retry safety (mutation-aware)
    b. If retryable: wait (exponential backoff), retry
    c. If not retryable: record inverse, mark step as failed
13. On success: record undo_token for potential rollback
14. Consolidate: merge step result into running result
15. BudgetReserver.commit() on full success → transition RESERVED → COMMITTED
    BudgetReserver.release() on any failure → transition RESERVED → RELEASED
```

**Key rule**: Admission (step 1) runs BEFORE worker selection (step 2).
No worker is selected, no lease acquired, no budget reserved before
admission passes. See WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §10.

```
States:  PENDING → RESERVED → COMMITTED (success)
                          → RELEASED (failure)
                          → LOCKED (UNKNOWN outcome — waiting for probe)
```

```python
class BudgetReserver:
    """Manages budget reservation lifecycle — ONLY at S12."""

    STATE_PENDING = "PENDING"
    STATE_RESERVED = "RESERVED"
    STATE_COMMITTED = "COMMITTED"
    STATE_RELEASED = "RELEASED"
    STATE_LOCKED = "LOCKED"

    def __init__(self, db: Database, execution_id: str, amount: int):
        self._db = db
        self._execution_id = execution_id
        self._amount = amount
        self._state = self.STATE_PENDING
        self._lock = asyncio.Lock()

    async def reserve(self) -> bool:
        """Atomically reserve budget. PENDING → RESERVED."""
        async with self._lock:
            if self._state != self.STATE_PENDING:
                raise BudgetStateError(
                    f"Cannot reserve from state {self._state}. "
                    f"Reservation is a one-time operation."
                )
            # Atomically check and deduct
            success = await self._db.execute(
                "UPDATE tenant_budget "
                "SET reserved = reserved + :amount, remaining = remaining - :amount "
                "WHERE tenant_id = :tenant_id AND remaining >= :amount",
                {"amount": self._amount, "tenant_id": self._tenant_id}
            )
            if success:
                self._state = self.STATE_RESERVED
                # Write checkpoint
                await CheckpointManager.write(self._db, self._execution_id, {
                    "budget_state": self._state,
                    "budget_amount": self._amount
                })
            return success

    async def commit(self) -> None:
        """Commit reserved budget on success. RESERVED → COMMITTED."""
        async with self._lock:
            if self._state != self.STATE_RESERVED:
                raise BudgetStateError(
                    f"Cannot commit from state {self._state}. "
                    f"Must be RESERVED."
                )
            await self._db.execute(
                "UPDATE tenant_budget SET reserved = reserved - :amount "
                "WHERE tenant_id = :tenant_id",
                {"amount": self._amount, "tenant_id": self._tenant_id}
            )
            self._state = self.STATE_COMMITTED
            await CheckpointManager.write(self._db, self._execution_id, {
                "budget_state": self._state
            })

    async def release(self) -> None:
        """Release budget on failure. RESERVED → RELEASED."""
        async with self._lock:
            if self._state not in (self.STATE_RESERVED, self.STATE_LOCKED):
                raise BudgetStateError(
                    f"Cannot release from state {self._state}. "
                    f"Must be RESERVED or LOCKED."
                )
            # Return budget to available pool
            await self._db.execute(
                "UPDATE tenant_budget "
                "SET reserved = reserved - :amount, remaining = remaining + :amount "
                "WHERE tenant_id = :tenant_id",
                {"amount": self._amount, "tenant_id": self._tenant_id}
            )
            self._state = self.STATE_RELEASED
            await CheckpointManager.write(self._db, self._execution_id, {
                "budget_state": self._state
            })

    async def lock(self) -> None:
        """Lock budget during UNKNOWN reconciliation. RESERVED → LOCKED."""
        async with self._lock:
            if self._state != self.STATE_RESERVED:
                raise BudgetStateError(
                    f"Cannot lock from state {self._state}. "
                    f"Must be RESERVED."
                )
            # Budget stays deducted but is not usable for other executions
            self._state = self.STATE_LOCKED
            await CheckpointManager.write(self._db, self._execution_id, {
                "budget_state": self._state,
                "locked_at": time.time()
            })

    @property
    def state(self) -> str:
        return self._state
```

**Budget reservation rules** (S12–S15 gate v9 repair, C3, C14, C31):
1. Budget is reserved **per step**, after lease acquisition and before pre-flight (the earlier "atomic with plan validation" and "reserved at S12 start" are superseded; S11's budget check is informational)
2. RESERVED → LOCKED immediately before execution; LOCKED → COMMITTED when the step is verified COMPLETED; → RELEASED when it FAILED, was cancelled/skipped, or a probe confirmed NOT_EXECUTED
3. Budget stays LOCKED while the outcome is uncertain — it cannot be used by other executions
4. A LOCKED reservation is resolved only by probe, verification or dead-letter resolution — crash recovery never releases it blindly (a step that actually executed would otherwise be free and let the tenant overspend)
5. The `BudgetReserver` sketch above (with its `tenant_budget` table and RESERVED → COMMITTED) is non-normative; the pool is `tenants.budget_pool` and the transitions are STATE_TRANSITIONS §3

**Rollback on Failure**:

```python
for step in reversed(completed_steps):
    if step.inverse and step.mutation in ("W", "D"):
        # CRITICAL: Verify the original operation actually executed
        # before running the compensating action
        provider_state = await self._verify_operation_state(step, binding)
        if provider_state == "EXECUTED":
            try:
                await self._execute_inverse(step)
            except Exception:
                pass  # Best effort — log and continue
        else:
            # Never executed or UNKNOWN — skip or escalate
            self._log_rollback_skipped(step, reason=provider_state)
```

**Cautions**:
- **ALWAYS use the Reliability Guard** — never call adapters directly
- BudgetReserver is the ONLY reservation point — no other stage reserves budget
- Timeout → UNKNOWN → probe provider — never treat timeout as failure
- attempt_id is scoped to a step within a plan; format att-{step_index}-{attempt_N}
- provider_call_id is globally unique (UUID) for each adapter invocation
- UNKNOWN is a reconciliation state, not a terminal state - do NOT route UNKNOWN directly to DEAD_LETTER
- If probe is inconclusive after max reconciliation attempts then route to DEAD_LETTER
- Record undo_token for every W/D step before moving to the next step
- Checkpoint after EVERY step for crash recovery
- Rollback must verify original operation executed before compensating

---

## 15. S13 — Validate Result

**Purpose**: Verify that execution results are correct and complete.
  Two sub-contracts:
  1. Result consolidation (all steps terminal → overall outcome)
  2. Independent verification for mutations (worker claim ≠ evidence)

**Input**: `ExecutionResult`, `Plan`, `ExecutionContext`

**Output**: Validated result or flag for dead letter

**Upstream contracts**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §6-9 (independent verification contract)

**Consolidation Rules** (DATA_CONTRACTS §22 — ExecutionStatus + ExecutionOutcome):

| Step Outcomes | ExecutionStatus | ExecutionOutcome |
|---------------|----------------|-----------------|
| All COMPLETED | COMPLETED | SUCCESS |
| Some COMPLETED, some FAILED | PARTIAL | PARTIAL |
| All FAILED | FAILED | FAILURE |
| Any step DEAD_LETTER (uncertainty unresolved after max probes/verification) | DEAD_LETTER | FAILURE |
| At least one COMPLETED and at least one FAILED/CANCELLED | PARTIAL | PARTIAL |
| No step COMPLETED | FAILED | FAILURE |

> **S12–S15 gate v9 repair (C8, C38, §10):** a step whose uncertainty resolved to CONFIRMED_SUCCESS counts as COMPLETED (it was listed as PARTIAL). CANCELLED and SKIPPED steps count as not completed; COMPLETED + SKIPPED with no failures is SUCCESS. The "All SKIPPED" row is unreachable (a step is skipped only after a predecessor failed) and was removed. The gate §10 table is authoritative.

**UNKNOWN Handling (CRITICAL)**:

UNKNOWN is a first-class outcome state alongside SUCCESS, FAILURE, and PARTIAL. It means the actual result is not yet deterministically known.

```
Outcome State Machine (DATA_CONTRACTS §22 ReconciliationStatus):
  UNKNOWN ──→ PENDING_PROBE ──→ CONFIRMED_SUCCESS
                                     ──→ CONFIRMED_FAILURE
                      ──→ RECONCILING ──→ DEAD_LETTER
```

**Actions on UNKNOWN**:

```
1. If any step is uncertain (PENDING_PROBE with an open episode):
   → Trigger PROBE phase — actively query the provider for the actual outcome
   → Set execution status to RECONCILING only when every other step is terminal
     (gate C13; while other steps remain executable, probing happens in RUNNING)
   → Do NOT consolidate to partial or failed yet
2. PROBE phase actions:
   a. Call provider's status endpoint with the operation ID
   b. If provider confirms success → CONFIRMED_SUCCESS
   c. If provider confirms failure → CONFIRMED_FAILURE
   d. If provider returns UNKNOWN or times out → STILL_UNKNOWN
3. If STILL_UNKNOWN after max PROBE attempts (default: 3):
   → Transition to RECONCILING
   → Escalate to DEAD_LETTER (S14) for human review
4. CONFIRMED_SUCCESS → consolidate to SUCCESS
   CONFIRMED_FAILURE → consolidate to FAILED or PARTIAL
```

**Independent Verification (for mutations only)**:

For W, D, and IRREVERSIBLE mutations, S13 runs independent verification
BEFORE consolidation. The verifier was built at S11 from the step definition.
S13 executes it — it does not construct it.

```
WORKER CLAIM → ADAPTER RESULT → VERIFIER OBSERVES → VERDICT
```

| Mutation | Verification | Method |
|----------|-------------|--------|
| R | No — reads are self-verifying | N/A |
| W | Yes | Observe written resource |
| D | Yes | Confirm resource absent |
| IRREVERSIBLE | Yes + human notification | Observe + notify on failure |

**Verifier contract** (WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §7):
- Built at S11, frozen in ExecutionManifest
- Uses observation methods to query provider independently
- Does NOT trust adapter's KernelResult.data
- Does NOT re-authorize (S8 already passed)
- Does NOT re-resolve bindings (S5 is frozen)
- Bounded: max 3 attempts, 1s apart, 5s timeout per attempt

| Verdict | Condition | Next Step |
|---------|-----------|-----------|
| `PASS` | Observation matches expected state | Step → COMPLETED |
| `FAIL` | Observation contradicts expected state | Step → FAILED, retry or DLQ |
| `UNKNOWN` | Observation inconclusive | Retry observation (up to max_attempts) |

**Ledger Event**: `LedgerEventType.VERIFICATION_STARTED` at entry, `LedgerEventType.VERIFICATION_COMPLETED` at exit.

### Progressive Verification Layers

S13 runs verification in layers. The required layers are determined by mutation type and risk:

| Layer | What It Checks | When Required | Method |
|-------|---------------|---------------|--------|
| **Schema** | Output matches expected structure | Always | Structural validation |
| **Deterministic** | Internal consistency, type checks, value ranges | Always | Rule-based |
| **Provider-state** | Read-back from provider confirms operation | W, D, IRREVERSIBLE | Adapter read |
| **Semantic** | AI-based assessment of outcome vs intent | AGENTIC path, risk ≥ 0.7 | LLM evaluation |
| **Business-rule** | Domain-specific rules (e.g., "lead must have email") | Configurable per capability | Worker-provided verifier |
| **Human** | Human confirms outcome | IRREVERSIBLE, D mutations, low-confidence | HITL |

**Layer selection**:
```python
def required_verification_layers(mutation: str, risk: float, autonomy: AutonomyLevel) -> list[str]:
    layers = ["schema", "deterministic"]
    if mutation in ("W", "D", "IRREVERSIBLE"):
        layers.append("provider_state")
    if risk >= 0.7 or mutation == "IRREVERSIBLE":
        layers.append("semantic")
    if mutation == "IRREVERSIBLE" or autonomy == AutonomyLevel.CONFIRM_ALL:
        layers.append("human")
    return layers
```

**Rule**: Each layer must independently PASS before the execution is marked `COMPLETED`. A failure at any layer routes to `DEAD_LETTER` with full evidence.

### Ledger Events

S13 emits the following LedgerEvents:

| Event | When |
|-------|------|
| `VERIFICATION_STARTED` | S13 entry, includes required layers |
| `VERIFICATION_COMPLETED` | S13 exit, includes all layer results |

---

## 16. S14 — Dead Letter

**Purpose**: Handle permanent failures that cannot be retried.

> **S12–S15 gate v9 repair (C21, C29, D4, D5, §11):** A dead-letter **record** is created for retries exhausted on a definitive error, unresolved uncertainty (`unknown_unresolved`), verification FAIL, human-layer pending and inverse failures; not for 401/403/404/422. Only unresolved uncertainty puts the **step** in DEAD_LETTER; the other cases leave it FAILED. Records follow the dead-letter state machine (`status`, `retry_mode` PROBE/VERIFY/NONE, `resolution_outcome`, `origin`); a retry never re-executes a step. Resolving a dead letter never changes run or step state.


**Input**: Failed steps from S13, `ExecutionContext`, `ReconciliationResult`

**Output**: Dead letter records

```python
@dataclass(frozen=True)
class DeadLetter:
    id: str
    execution_id: str
    step_id: str
    kernel_op_id: str
    error: str
    error_type: str         # "transient" | "permanent" | "data" | "unknown_unresolved"
    retry_count: int
    max_retries: int
    next_retry_at: float | None
    context: dict
```

**UNKNOWN Resolution (STILL_UNKNOWN) Handling**:

When S13 sends a step to S14 with `STILL_UNKNOWN` after max reconciliation attempts, S14:

1. Classify the UNKNOWN outcome: provider unreachable → `transient`, provider returned inconclusive → `unknown_unresolved`, operation confirmed failed but no error detail → `data`
2. Store dead letter record with `error_type = "unknown_unresolved"`
3. Schedule reconciliation retry (exponential backoff, max 3 additional probe attempts)
4. Alert operations team for `unknown_unresolved` — human review required
5. If all reconciliation retries exhausted → finalize as DEAD_LETTER terminal state

**Actions**:
1. Classify failure: transient → retry later, permanent → alert, unknown_unresolved → escalate to human + retry reconciliation
2. Store dead letter record
3. Schedule retry if applicable (exponential backoff, max 3 for transient, max 3 reconciliation retries for unknown_unresolved)
4. Alert if permanent or unknown_unresolved

**Cautions**:
- Dead letters should NEVER be silently dropped
- Transient failures should be retried with backoff
- Permanent failures should trigger alerts
- `unknown_unresolved` outcomes require human review — do NOT silently route to error
- STILL_UNKNOWN after max reconciliation attempts → DEAD_LETTER terminal state
- DEAD_LETTER is a terminal state — execution cannot resume from DEAD_LETTER

---

## 17. S15 — Response Formatting

**Purpose**: Build the final response envelope and format for terminal.

**Input**: Result from any previous stage, `ExecutionContext`

**Output**: `Envelope` → terminal message

**Envelope → terminal Mapping**:

| Envelope Status | terminal Response |
|----------------|-------------------|
| `ok` | Success message + results summary |
| `partial` | Partial success message + list of failed steps |
| `error` | Error message + suggested action |
| `clarify` | Question + inline keyboard for options |
| `confirm` | Summary of operations + YES/NO buttons |

**Cautions**:
- NEVER send raw internal error messages to users
- NEVER include sensitive data in user-facing messages
- Clarify messages should offer specific options
- Confirm messages should list EXACTLY what will happen

---

## 18. Short-Circuit Paths Summary

| From Stage | Condition | Short-Circuit To | Envelope Status |
|------------|-----------|-------------------|-----------------|
| S7 | No capability match | S15 | `clarify` |
| S7 | Low confidence (< 0.5) | S15 | `clarify` |
| S7 | High risk / unauthorized | S15 | `error` |
| S8 | Any safety check fails | S15 | `error` |
| S10 | User rejects confirmation | S15 | `error` |
| S10 | Confirmation expires | S15 | `error` |
| S11 | Invalid plan | S15 | `error` |
| S13 | Result Validation | CLARIFY needed | `clarify` |
| S13 | Result Validation | DENY | `deny` |
| S13 | Permanent failure | S14 → S15 | `error` |

### Rules for Short-Circuits

1. Every short-circuit must produce a user-friendly message
2. Every short-circuit must log the reason for debugging
3. Short-circuits at S7/S8 are authorization/safety issues — no retry
4. Short-circuits at S10/S11 are user/plan issues — user can retry with modifications
5. Short-circuits at S13/S14 are execution issues — may be retryable

---

## 19. Negative-Path Matrix

**Purpose**: Exhaustive table of every failure mode, how it is detected, what state it produces, and how the pipeline responds. This is the operational reference for error handling design and incident response.

| Failure Case | Detection | State | Retry | Probe | Dead Letter | User Response |
|--------------|-----------|-------|-------|-------|-------------|---------------|
| LLM unavailable | HTTP 5xx / timeout from LLM provider | FAILED | No (S2 has no retry) | No | No | "Service temporarily unavailable — please retry" |
| LLM malformed | Schema validation fails at S2 | FAILED | Once with error feedback | No | No | CLARIFY — "I had trouble understanding, could you rephrase?" |
| Provider timeout | Adapter timeout at S12 TimeoutManager | UNKNOWN | No — trigger PROBE | Yes — call provider status endpoint | If STILL_UNKNOWN after 3 probes | "Operation timed out — checking status..." |
| Provider 429 (rate limit) | HTTP 429 at adapter call | FAILED | Yes — exponential backoff | No | If retries exhausted | "Service is busy — retrying automatically" |
| Provider 401/403 | HTTP 401/403 at adapter call | FAILED | No — auth failure | No | No | "Authentication failed — check credentials" |
| Provider 500 | HTTP 500 at adapter call | FAILED | Yes — up to 3 retries | No — if retries still 500 | If retries exhausted | "Provider error — retrying or escalating" |
| Network disconnect | Connection error / DNS failure at S12 | FAILED | Yes — reconnect and retry | If timeout, PROBE after reconnect | If unreachable after max retries | "Connection lost — retrying..." |
| Worker Runtime crash | Process exit / heartbeat timeout | In-flight step → PENDING_PROBE (recovery, gate §13) | Recovery resolves the in-flight step (ledger, dispatch marker, probe), then resumes from the first PENDING step | Yes — verify step state after restart | If checkpoint gap unrecoverable | Resume transparently or "Retrying..." |
| DB disconnect | Database connection error | FAILED | Yes — reconnect and retry transaction | No | If DB unreachable | "Service temporarily unavailable" |
| Lease expiration | Lease expires during execution (renewal missed) | In-flight step → PENDING_PROBE under the new owner | No — an *expired* lease is never reactivated (leases are renewable while usable; gate C5, C26) | Yes — check provider for actual outcome | If STILL_UNKNOWN | "Operation expired — please retry" |
| Duplicate request | Idempotency key collision | PARTIAL | No — idempotency returns existing result | No | If new failure | Return existing result |
| Stale Worker Runtime (heartbeat lost) | Worker Runtime heartbeat > threshold | Execution taken over by a new owner (new fence token) | No — the stale owner is fenced out | Yes — the new owner probes the provider | If unreachable | Transparent reassignment |
| Expired confirmation | S10 confirmation token TTL exceeded | FAILED | No — must re-confirm | No | No | "Confirmation expired — please confirm again" |
| Budget exhausted | Budget precheck fails at S8 | DENY | No — no execution started | No | No | "Budget limit reached — upgrade or reduce scope" |
| Tenant disabled | Tenant status check fails at S8 | DENY | No | No | No | "Account disabled — contact support" |

**Notes**:
- UNKNOWN outcomes always go through PROBE before any terminal state — no silent transitions
- Retry count is per-step, not per-execution — each step has independent retry budget
- Probe is triggered only for UNKNOWN/timeout outcomes, not for confirmed failures
- Dead Letter at S14 handles permanent failures and STILL_UNKNOWN after max reconciliation

---

## 20. No Silent Success Invariant

**Purpose**: Define the explicit rule that prevents UNKNOWN outcomes from becoming SUCCESS without verification.

**Rule**: UNKNOWN cannot become SUCCESS without verification. S13 must establish truth before CONFIRMED_SUCCESS.

> **No silent success**: Any step that reaches UNKNOWN state must complete the full PROBE → CONFIRMED_SUCCESS/CONFIRMED_FAILURE/STILL_UNKNOWN resolution before its outcome is recorded as SUCCESS or FAILURE. There is no implicit or shortcut path from UNKNOWN to SUCCESS.

**Error Handling Requirement**: Any UNKNOWN outcome must go through PROBE before reaching a terminal state. The PROBE phase actively queries the provider to determine the actual outcome. Only after the provider confirms (CONFIRMED_SUCCESS) or confirms failure (CONFIRMED_FAILURE), or after max probes return STILL_UNKNOWN, can the step reach a terminal state.

**Implementation contract**:
1. S12 TimeoutManager timeout → step RUNNING → TIMEOUT → PENDING_PROBE (not FAILED; gate C6)
2. The reconciliation code (S13 package, called from the S12 loop — gate C12) opens an episode and triggers the PROBE phase
3. PROBE calls provider status endpoint → gets CONFIRMED_SUCCESS, CONFIRMED_FAILURE, or STILL_UNKNOWN
4. CONFIRMED_SUCCESS → step state = COMPLETED, proceed normally
5. Probe EXECUTED_FAILURE → step state = FAILED (no retry); probe NOT_EXECUTED → step state = PENDING, retried within its ceiling (never IRREVERSIBLE or non-idempotent D)
6. STILL_UNKNOWN after max probes → step state = DEAD_LETTER (not FAILED: FAILED would allow a duplicate retry), budget stays LOCKED, route to S14 (gate C6, D4)
7. No step transitions from UNKNOWN to COMPLETED without passing through PROBE

```python
class UnknownResolutionContract:
    """Enforces the no-silent-success invariant for UNKNOWN outcomes."""

    MAX_PROBE_ATTEMPTS = 3
    PROBE_TIMEOUT_SECONDS = 10

    def __init__(self, provider_client, execution_id: str):
        self.provider = provider_client
        self.execution_id = execution_id

    async def resolve_unknown(self, step_id: str, operation_id: str, attempt_id: str, budget_reservation_id: str) -> StepResult:
        """Resolve an UNKNOWN step through PROBE phase.

        Returns StepResult with ExecutionStatus, ExecutionOutcome, and
        ReconciliationStatus per DATA_CONTRACTS §9.
        """
        for attempt in range(self.MAX_PROBE_ATTEMPTS):
            try:
                probe_result = await asyncio.wait_for(
                    self.provider.get_operation_status(operation_id),
                    timeout=self.PROBE_TIMEOUT_SECONDS
                )
                if probe_result.status == "completed":
                    return StepResult(
                        step_id=step_id,
                        attempt_id=attempt_id,
                        status=ExecutionStatus.COMPLETED,
                        outcome=ExecutionOutcome.SUCCESS,
                        reconciliation_status=ReconciliationStatus.CONFIRMED_SUCCESS,
                        budget_reservation_id=budget_reservation_id,
                    )
                elif probe_result.status == "failed":
                    return StepResult(
                        step_id=step_id,
                        attempt_id=attempt_id,
                        status=ExecutionStatus.FAILED,
                        outcome=ExecutionOutcome.FAILURE,
                        reconciliation_status=ReconciliationStatus.CONFIRMED_FAILURE,
                        budget_reservation_id=budget_reservation_id,
                    )
                # STILL_UNKNOWN — continue probing
            except asyncio.TimeoutError:
                continue  # Probe timed out, try again
            except ProviderError:
                return StepResult(
                    step_id=step_id,
                    attempt_id=attempt_id,
                    status=ExecutionStatus.DEAD_LETTER,
                    outcome=ExecutionOutcome.FAILURE,
                    reconciliation_status=ReconciliationStatus.CONFIRMED_FAILURE,
                    budget_reservation_id=budget_reservation_id,
                )

        # Max probes exhausted — DEAD_LETTER
        return StepResult(
            step_id=step_id,
            attempt_id=attempt_id,
            status=ExecutionStatus.DEAD_LETTER,
            outcome=ExecutionOutcome.FAILURE,
            reconciliation_status=ReconciliationStatus.RECONCILING,
            budget_reservation_id=budget_reservation_id,
        )
```

**Verification**: This invariant is verified in S13 (Validate Result). Any step still in UNKNOWN state when S13 runs must trigger the PROBE phase. S13 will not consolidate an UNKNOWN step into any outcome until PROBE returns CONFIRMED_SUCCESS or CONFIRMED_FAILURE.

---

## Appendix: State Transition Matrix (CRITICAL — from forensic audit)

This appendix defines all legal state transitions. Any transition not listed here is **illegal** and must be rejected with an explicit exception.

### Execution Run States

```
Valid Transitions:
  PENDING     ──→ RUNNING      (S12 starts execution)
  RUNNING     ──→ COMPLETED    (all steps succeeded)
  RUNNING     ──→ FAILED       (unrecoverable error)
  RUNNING     ──→ CANCELLED    (user cancelled or budget exhausted)
  RUNNING     ──→ DEAD_LETTER  (exhausted retries, unrecoverable)
  RUNNING     ──→ RECONCILING  (step(s) timed out, probing provider)
  PENDING     ──→ CANCELLED    (cancelled before execution starts)

  NOTE: TIMEOUT is NOT a run state. Timeout is an EVENT that triggers
  reconciliation. The execution enters RECONCILING while probing.

Illegal Transitions (MUST be rejected):
  COMPLETED   ──→ any non-terminal (terminal states are final)
  FAILED      ──→ RUNNING     (must create new execution)
  CANCELLED   ──→ RUNNING     (must create new execution)
  DEAD_LETTER ──→ RUNNING     (must create new execution)
  RECONCILING ──→ RUNNING     (must resolve to terminal state first)
  Any terminal ──→ PENDING  (terminal states are final)

Recovery Transitions (from RECONCILING):
  RECONCILING ──→ COMPLETED   (probe confirms all steps succeeded)
  RECONCILING ──→ FAILED      (probe confirms failure, rollback done)
  RECONCILING ──→ DEAD_LETTER (probe inconclusive after max reconciliation attempts)
```

```python
class StateTransitionValidator:
    """Validates execution run state transitions."""
    
    LEGAL_TRANSITIONS: dict[str, set[str]] = {
        "PENDING":     {"RUNNING", "CANCELLED"},
        "RUNNING":     {"COMPLETED", "FAILED", "CANCELLED", "DEAD_LETTER", "RECONCILING"},
        "RECONCILING": {"COMPLETED", "FAILED", "DEAD_LETTER"},
        "COMPLETED":   set(),      # Terminal
        "FAILED":      set(),      # Terminal
        "CANCELLED":   set(),      # Terminal
        "DEAD_LETTER": set(),      # Terminal
    }
    
    def validate(self, current: str, next_state: str) -> None:
        allowed = self.LEGAL_TRANSITIONS.get(current, set())
        if next_state not in allowed:
            raise IllegalStateTransition(
                f"Cannot transition from {current} → {next_state}. "
                f"Allowed: {allowed or 'none (terminal state)'}"
            )
```

### Execution Step States

```
Valid Transitions:
  PENDING   ──→ RUNNING     (S12 starts step)
  RUNNING   ──→ COMPLETED   (adapter succeeded)
  RUNNING   ──→ FAILED      (adapter failed, no retry)
  RUNNING   ──→ SKIPPED     (precondition not met)
  RUNNING   ──→ PARTIAL     (partial success — provider reported some failures)

Retry Transitions (same step_id, incremented attempt):
  FAILED    ──→ PENDING     (retry — only if retry-safe)
  PARTIAL   ──→ PENDING     (retry partial operations)
  UNKNOWN   ──→ PENDING     (probe failed, reconcile and retry if safe)

Illegal Transitions (MUST be rejected):
  COMPLETED ──→ any non-terminal
  FAILED    ──→ RUNNING    (must go through PENDING for retry)
  SKIPPED   ──→ any state  (skipped is final)
  PARTIAL   ──→ COMPLETED  (must resolve remaining items first)

CRITICAL: UNKNOWN is a reconciliation state, not equivalent to FAILED
  If a step times out, the outcome is UNKNOWN — not "failed".
  UNKNOWN means: the actual result is not yet deterministically known.
  The recovery process (probe provider) determines the final state.
  This must never be silently treated as "failed" for:
  - Retry decision (UNKNOWN requires explicit probe, not retry)
  - Budget accounting (UNKNOWN = reservation not released)
  - Rollback decision (UNKNOWN = must verify before compensating)
```

### Atomic State Transition Rule

State transitions MUST be atomic with their side effects:

```python
@dataclass(frozen=True)
class StateTransition:
    """A state transition with its side effects — all succeed or all fail."""
    execution_id: str
    step_id: str | None          # None for execution-level transitions
    from_state: str
    to_state: str
    side_effects: list[Callable] # checkpoint, budget, audit, etc.
    
    def apply(self, db: Database) -> None:
        with db.transaction() as tx:
            # 1. Validate transition
            StateTransitionValidator().validate(self.from_state, self.to_state)
            # 2. Update state
            self._update_state(tx)
            # 3. Apply all side effects
            for effect in self.side_effects:
                effect(tx)
            # 4. Write checkpoint
            CheckpointManager.write(tx, self.execution_id)
```

---

---
---

## 21. Execution Strategy Selection (CODE-PROVEN)

**Purpose**: The pipeline supports multiple execution strategies. The strategy is selected at S7 (Path Routing) and determines how S12 executes the plan.

**Source evidence**:
- SystemOneHarness reflex architecture: one LLM call per step, observe→encode→decide→gate→execute
- AIOS FIFO/RR scheduler with LLM request batching
- AgentsMesh pod-based execution with control/data plane separation
- Xagent heartbeat-driven autonomous worker loop

### Strategy Catalog

| Strategy | Trigger | Execution Pattern | LLM Calls Per Step | Use Case |
|----------|---------|-------------------|-------------------|----------|
| REFLEX | Confidence >= 0.9, simple graph | Observe→encode→decide→gate→execute | 1 | UI automation, API orchestration, safety-critical tasks |
| REACT | Confidence >= 0.7, chain graph | Thought→action→observation loop | 2-3 | Multi-step reasoning with tool use |
| DAG | Complex graph, known dependencies | Parallel step execution with join | 1 per step | Bulk operations, data pipelines |
| PLAN_EXECUTE | Complex graph, unknown deps | Full plan→execute→monitor | 3-5 | Multi-step workflows with planning |
| HUMAN_ASSISTED | High risk, D/IRREVERSIBLE | Execute→confirm→continue | Varies | Approval workflows, critical operations |
| BATCH | Multiple similar operations | Batch LLM requests, parallel adapters | 1 per batch | Bulk creates/updates, mass operations |
| EVENT_DRIVEN | External triggers | Webhook→queue→execute | Varies | Async workflows, integrations |

### REFLEX Strategy Detail (SystemOneHarness pattern)

```python
class ReflexExecutor:
    """One-step execution: observe, encode, decide, gate, execute."""

    async def execute_step(self, worker, observation) -> StepResult:
        # 1. Compile action space (deterministic, no LLM)
        compiled = worker.space.compile(
            candidates=observation.candidates,
            disabled=worker.disabled_actions
        )

        # 2. Encode state (deterministic)
        encoder_input = self.encoder.encode(
            goal=worker.goal,
            observation=observation,
            history=worker.history,
            memory=worker.memory,
            task_instructions=worker.task_instructions
        )

        # 3. LLM decides (ONE call — all questions in parallel)
        decision = await worker.provider.decide(
            state=encoder_input.state,
            questions=compiled.questions
        )

        # 4. Gate judges confidence (deterministic)
        verdict = worker.gate.judge(
            answers=decision.answers,
            compiled=compiled,
            space=worker.space
        )

        # 5. Execute or refuse
        if verdict.kind == "run":
            result = await worker.env.execute(verdict.action, verdict.params)
            return StepResult(status="completed", result=result)
        elif verdict.kind == "refused":
            return StepResult(status="refused", reason=verdict.reason)
        elif verdict.kind == "escalate":
            return StepResult(status="escalated", reason=verdict.reason)
        else:  # finish
            return StepResult(status="finished", reason=verdict.reason)
```

**Key properties**:
- 100-200ms per step
- Deterministic cost per step
- Auditable decisions (full distribution preserved in trace)
- No chain-of-thought, no multi-turn planning
- Action space is pre-compiled (typed parameters, fixed choices)

### REACT Strategy Detail

```python
class ReActExecutor:
    """Reason-Act-Observe loop with tool use."""

    async def execute_plan(self, plan: Plan, context: ExecutionContext) -> ExecutionResult:
        observations = []
        for step in plan.steps:
            # Thought: LLM reasons about current state
            thought = await self.llm.think(
                goal=context.goal,
                history=observations,
                available_tools=step.tools
            )

            # Action: LLM selects tool and parameters
            action = await self.llm.select_action(
                thought=thought,
                tools=step.tools
            )

            # Execute: adapter call through reliability guard
            result = await self.guard.execute(action, context)

            # Observe: record result for next iteration
            observations.append(Observation(
                thought=thought,
                action=action,
                result=result
            ))

            # Check termination condition
            if self._is_terminal(result):
                break
```

### DAG Strategy Detail

```python
class DAGExecutor:
    """Parallel step execution with dependency joins."""

    async def execute_plan(self, plan: Plan, context: ExecutionContext) -> ExecutionResult:
        # Build execution order from dependency graph
        levels = self._topological_levels(plan.steps)

        for level in levels:
            # Execute all steps at this level in parallel
            tasks = []
            for step in level:
                task = self.guard.execute(step, context)
                tasks.append(task)

            # Wait for all steps at this level
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Check join mode
            if plan.join_mode == "all":
                if any(isinstance(r, Exception) for r in results):
                    return ExecutionResult(status="failed", ...)
            elif plan.join_mode == "any":
                if not any(not isinstance(r, Exception) for r in results):
                    return ExecutionResult(status="failed", ...)
            elif plan.join_mode == "threshold":
                successes = sum(1 for r in results if not isinstance(r, Exception))
                if successes < plan.threshold:
                    return ExecutionResult(status="partial", ...)
```

### Verification After Execution (MISSING from all 10 repos)

**Critical finding**: No repository implements post-execution verification. The pipeline must add a verification stage after S12 and before S13.

```python
class VerificationLayer:
    """Post-execution outcome validation."""

    async def verify(self, execution: Execution, plan: Plan,
                     results: list[StepResult]) -> VerificationResult:
        """
        Verification is NOT the same as success detection.
        API success ≠ business-task success.
        """
        checks = []

        for step, result in zip(plan.steps, results):
            if result.status != "completed":
                continue

            # 1. Outcome verification: did the action achieve its intent?
            outcome_check = await self._verify_outcome(step, result)
            checks.append(outcome_check)

            # 2. Side-effect verification: are the expected side effects present?
            side_effect_check = await self._verify_side_effects(step, result)
            checks.append(side_effect_check)

            # 3. State verification: is the system in the expected state?
            state_check = await self._verify_state(step, result)
            checks.append(state_check)

        all_passed = all(c.passed for c in checks)
        return VerificationResult(
            passed=all_passed,
            checks=checks,
            failed_checks=[c for c in checks if not c.passed]
        )

    async def _verify_outcome(self, step: Step, result: StepResult) -> CheckResult:
        """Verify the business outcome matches intent."""
        # Read back the created/modified resource
        # Compare with expected state from step parameters
        # Return pass/fail with evidence
        pass

    async def _verify_side_effects(self, step: Step, result: StepResult) -> CheckResult:
        """Verify expected side effects are present."""
        # For email sent: check sent folder
        # For record created: query with unique identifier
        # For file written: read back and compare hash
        pass

    async def _verify_state(self, step: Step, result: StepResult) -> CheckResult:
        """Verify system state consistency."""
        # Check related records are consistent
        # Check referential integrity
        # Check business rules
        pass
```

**Verification contract**:
- Verification is a FIRST-CLASS stage, not an afterthought
- Verification has its own timeout separate from execution timeout
- Failed verification does NOT auto-retry — it routes to DEAD_LETTER
- Verification evidence is stored in the execution trace
- Verification failure triggers rollback of the verified step

---

## 22. A2A Communication Semantics (CODE-PROVEN)

**Purpose**: Define the 12 typed message semantics for agent-to-agent communication within the Worker OS.

**Source evidence**: MARKUS message bus, AgentsMesh gRPC/WebSocket protocols

### Message Type Catalog

| Semantic | Direction | Delivery Guarantee | Example | Evidence |
|----------|-----------|-------------------|---------|----------|
| COMMAND | A→B | At-least-once + idempotency | "Create contact" | MARKUS E2 |
| EVENT | System→A | At-least-once + dedup | "Pod created" | AgentsMesh E2 |
| QUERY | A→B | Exactly-once response | "Get contact 123" | MARKUS E2 |
| RESPONSE | B→A | Exactly-once (per query) | Contact data | MARKUS E2 |
| DELEGATION | A→B | At-least-once + ack | "Handle this ticket" | SystemOneHarness E2 |
| HANDOFF | A→B | Exactly-once + state transfer | Full task state | SystemOneHarness E2 |
| APPROVAL | A→Human | Exactly-once + timeout | "Approve deletion?" | Multiple E1-E2 |
| CANCELLATION | A→B | At-least-once + ack | "Stop execution" | SystemOneHarness E2 |
| PROGRESS | B→A | At-least-once + ordered | "Step 3/7 complete" | AgentsMesh E2 |
| HEARTBEAT | A↔System | At-least-once + timeout | Worker alive? | Xagent E2, AgentsMesh E2 |
| RESULT | B→A | At-least-once + dedup | "Task completed" | MARKUS E2 |
| FAILURE | B→A | At-least-once + retry | "Task failed: reason" | MARKUS E2 |

### Envelope Structure

```python
@dataclass(frozen=True)
class A2AEnvelope:
    """Agent-to-agent message envelope."""
    message_id: str           # UUID — durable event ID
    correlation_id: str       # Links related messages
    timestamp: datetime       # UTC
    source_worker_id: WorkerId
    target_worker_id: WorkerId | None  # None for broadcast
    semantic: str             # One of the 12 types above
    payload: dict             # Message-specific data
    metadata: dict            # Delivery hints, retry count, TTL
    idempotency_key: str      # For deduplication
    ttl_seconds: int          # Message TTL
```

### Delivery Contract

| Semantic | Retry | Dedup | Ordering | Persistence |
|----------|-------|-------|----------|-------------|
| COMMAND | Yes | Key | Ordered | Until ack |
| EVENT | No | Key | Ordered | None (fire-and-forget) |
| QUERY | Yes | Key | None | Until response |
| RESPONSE | No | Key | Ordered | Until consumed |
| DELEGATION | Yes | Key | Ordered | Until accepted |
| HANDOFF | Yes | Key | Ordered | Durable |
| APPROVAL | Yes | None | Ordered | Until responded |
| CANCELLATION | Yes | Key | Ordered | Until ack |
| PROGRESS | No | Key | Ordered | None |
| HEARTBEAT | Yes | None | None | None |
| RESULT | Yes | Key | Ordered | Durable |
| FAILURE | Yes | Key | Ordered | Durable |

### Implementation Notes

From MARKUS codebase:
- `A2AEnvelope` has 15 typed message types with validation
- `bus.send(envelope)` → `agentEndpoints.get(to)` for direct messages
- `bus.on(type, handler)` for topic subscription
- Persistent message history in execution traces

From AgentsMesh:
- gRPC bidirectional stream for control plane messages
- WebSocket binary protocol for terminal data plane
- Backend never touches PTY bytes — separation of concerns

**Critical rule**: Use at-least-once + idempotency keys + deduplication. Do NOT promise exactly-once delivery as the platform abstraction. It is unachievable across distributed systems.

---
