# Data Contracts

**Purpose**: Every data structure that flows between components, its fields, types, validation rules, and transformation rules. This is the API contract between layers.

> **Canonical Source**: The Provider Package (versioned, signed, checksummed) is the authoritative source for all kernel, capability, and binding definitions. `kernel_ops` and `bindings` DB tables are populated by migration from the Provider Package at install/upgrade time. DB tables are a cache, not a source of truth.

---

## Table of Contents

1. [Envelope — Universal Response Format](#1-envelope--universal-response-format)
2. [ExecutionContext — Frozen Request State](#2-executioncontext--frozen-request-state)
3. [KernelResult — Adapter Response](#3-kernelresult--adapter-response)
4. [Plan & Step — Execution Blueprint](#4-plan--step--execution-blueprint)
5. [CapabilityMetadata — Capability Definition](#5-capabilitymetadata--capability-definition)
6. [BindingRow — Capability-to-Adapter Mapping](#6-bindingrow--capability-to-adapter-mapping)
7. [TaskProfile — Task Characterization](#7-taskprofile--task-characterization)
8. [SafetyResult — Authorization Outcome](#8-safetyresult--authorization-outcome)
9. [ExecutionResult — Execution Outcome](#9-executionresult--execution-outcome)
10. [ValidationResult — Adapter Parameter Validation](#10-validationresult--adapter-parameter-validation)
11. [ProviderAdapter Contract](#11-provideradapter-contract)
12. [Kernel Policy — Per-Operation Config](#12-kernel-policy--per-operation-config)
13. [Confirmation — User Approval](#13-confirmation--user-approval)
14. [Error Hierarchy](#14-error-hierarchy)
15. [State Machines](#15-state-machines)
16. [Budget & Cost](#16-budget--cost)
17. [Idempotency](#17-idempotency)
18. [Billing Data Contracts](#18-billing-data-contracts)
19. [StepState — Execution State Enum](#19-stepstate--execution-state-enum)
20. [BudgetTracker — Atomic Budget Operations](#20-budgettracker--atomic-budget-operations)
21. [PathDecision — Execution Path Enum](#21-pathdecision--execution-path-enum)
22. [RetryDecision — Retry Action Enum](#22-retrydecision--retry-action-enum)
23. [DeadLetter — Permanent Failure Record](#23-deadletter--permanent-failure-record)
24. [ResponseFormatter — S15 Output](#24-responseformatter--s15-output)
25. [KernelMeta — Per-Operation Metadata](#25-kernelmeta--per-operation-metadata)
26. [StateTransitionValidator — Legal Transition Matrix](#26-statetransitionvalidator--legal-transition-matrix)
27. [ExecutionManifest — Frozen Execution Manifest](#27-executionmanifest--frozen-execution-manifest)
28. [Outbox-Inbox Event Delivery Contract](#28-outbox-inbox-event-delivery-contract)
29. [Event Ordering and Causality](#29-event-ordering-and-causality)
30. [Configuration Versioning and Rollout](#30-configuration-versioning-and-rollout)
31. [WorkerIdentity — Durable Worker Identity](#31-workeridentity--durable-worker-identity)
32. [WorkerVersion — Worker Code Version](#32-workerversion--worker-code-version)
33. [WorkerDeployment — Runtime Instance](#33-workerdeployment--runtime-instance)
34. [Verifier — Independent Post-Execution Verifier](#34-verifier--independent-post-execution-verifier)
35. [VerificationResult — Independent Verification Outcome](#35-verificationresult--independent-verification-outcome)
36. [AdmissionDecision — Admission Control Outcome](#36-admissiondecision--admission-control-outcome)
37. [ExecutionOwnership — Execution Ownership Tracking](#37-executionownership--execution-ownership-tracking)

---

## 1. Envelope — Universal Response Format

Every response from the control plane to the interface uses this envelope. The interface never receives raw data structures — only Envelope objects.

```python
@dataclass(frozen=True)
class Envelope:
    status: str           # REQUIRED — "ok" | "partial" | "error" | "clarify" | "confirm"
    data: Any = None      # Payload (varies by status)
    message: str | None = None   # Human-readable message (for display)
    error: EnvelopeError | None = None  # Structured error (for error status)
    metadata: dict | None = None  # Additional info (claude_code_buttons, next_action)
```

### Status Values

| Status | Meaning | Data Contains | Error Contains | Message |
|--------|---------|---------------|----------------|---------|
| `ok` | Execution succeeded | Step results dict | None | Success message |
| `partial` | Some steps succeeded, some failed | Step results dict | PartialError | Summary of failures |
| `error` | Execution failed | None or partial | Error details | Error message |
| `clarify` | Need more info from user | None | None | Question for user |
| `confirm` | Need user confirmation | ConfirmationRequest | None | Description of what will happen |
| `deny` | Request refused by safety/auth | None | None | Refusal message |
| `probe` | Probe response (capability discovery) | ProbeResult | None | Capability info |

### EnvelopeError

```python
@dataclass(frozen=True)
class EnvelopeError:
    type: str             # REQUIRED — error category
    message: str          # REQUIRED — human-readable message
    details: dict | None = None   # Additional error context
    recoverable: bool = True      # Can the user retry?
    suggested_action: str | None = None  # What the user can do
```

### Envelope Error Types

| Type | When | Recoverable | Suggested Action |
|------|------|-------------|-----------------|
| `unknown_capability` | Intent doesn't match any capability | Yes | Try a different request |
| `unauthorized` | User lacks permission | Yes | Request access from admin |
| `provider_unavailable` | No provider available | Yes | Try again later |
| `validation_error` | Input doesn't match schema | Yes | Provide the missing fields |
| `budget_exceeded` | User budget insufficient | Yes | Increase budget or use simpler request |
| `circuit_open` | Provider temporarily down | Yes | Try again in a few minutes |
| `plan_error` | Plan is invalid | No (internal) | Report bug |
| `execution_failed` | Execution failed | Yes | Check error details |
| `partial_execution` | Some steps failed | Yes | Review failed steps |
| `confirmation_expired` | Confirmation timed out | Yes | Restart the request |
| `timeout` | Execution timed out | Yes | Try with fewer steps |
| `injection_detected` | Prompt injection in input | No (blocked) | N/A |
| `unmapped_engine` | Kernel has no mapped engine | No (internal) | Report bug |

---

## 2. ExecutionContext — Frozen Request State

```python
@dataclass(frozen=True)
class ExecutionContext:
    """Frozen execution context. All fields from non-LLM sources only.
    NEVER modified after creation. NEVER populated from LLM output.
    """

    # ─── Identity (S0 — system-generated) ────────────────────
    trace_id: str           # Canonical correlation ID (UUID v4) — generated at S0
    request_id: str         # This specific request (UUID v4) — generated at S0

    # ─── Tenancy (S0 — from auth + session) ────────────────────────
    tenant_id: str          # Top-level isolation boundary
    user_id: str            # Authenticated user
    workspace_id: str       # Logical workspace within tenant
    membership_id: str      # User ↔ workspace ↔ role binding

    # ─── Actor (S0 — from authentication) ────────────────────────
    actor_type: Literal["user", "worker", "system"]  # Who initiated this execution
    actor_id: str | None = None  # user_id, worker_id, or "system"

    # ─── Request identity (S0 — from interface/auth, never from LLM) ─────
    conversation_id: str    # From interface chat session
    connection_id: str      # Provider connection being used
    idempotency_key: str    # = request_id (canonical idempotency key)
    resource_scope: str     # From user permissions, NOT from LLM
    tags: frozenset[str] = field(default_factory=frozenset)  # User attributes

    # ─── Task identity (S2 — from Intent Analysis) ────────────────
    task_id: str | None = None  # Links intent to execution chain, generated at S2

    # ─── Authorization (S8 — cached for MutationSafetyGate at S12) ───────
    auth_passed: bool = False  # True if S8 Safety Gate passed
    auth_result_id: str | None = None  # S8 auth result record ID

    # ─── Policy (S5 — versions that authorized this execution) ────────────
    tenant_policy_version_id: str | None = None
    workspace_policy_version_id: str | None = None
    policy_version_id: str | None = None  # Effective policy version


**Ownership note**: FrozenBindingIdentity owns provider resolution (S5). ExecutionContext owns only request identity (S0). FrozenBindingIdentity is produced at S5 and consumed by S6-S12. ExecutionContext is never modified after S0.

### Field Constraints

| Field | Source | Set At | Mutable | Validation |
|-------|--------|--------|---------|------------|
| `trace_id` | System (UUID v4) | S0 | No | UUID format |
| `request_id` | System (UUID v4) | S0 | No | UUID format |
| `tenant_id` | User session | S0 | No | Non-empty string |
| `user_id` | Authentication | S0 | No | Non-empty string |
| `workspace_id` | User session | S0 | No | Non-empty string |
| `membership_id` | Auth context | S0 | No | Valid membership |
| `provider` | Resolution (S5) | S5 | No | Valid provider name or None — owned by FrozenBindingIdentity |
| `task_id` | S2 (Intent Analysis) | S2 | No | UUID format — None before S2 |
| `conversation_id` | Interface | S0 | No | Valid conversation ID |
| `connection_id` | User session | S0 | No | Valid connection ID |
| `idempotency_key` | System (= request_id) | S0 | No | UUID format |
| `resource_scope` | User permissions | S0 | No | Scope pattern |
| `tags` | User attributes | S0 | No | Set of strings |
| `auth_passed` | S8 Safety Gate | S8 | No | Boolean |
| `auth_result_id` | S8 Safety Gate | S8 | No | Valid auth result record |
| `tenant_policy_version_id` | Policy system | S5 | No | Valid policy version |
| `workspace_policy_version_id` | Policy system | S5 | No | Valid policy version |
| `policy_version_id` | Policy system | S5 | No | Valid policy version |
| `resolution` | S5 Provider Resolution | S5 | No | Valid FrozenBindingIdentity |

### Critical Rules

**ALL fields come from non-LLM sources. The ExecutionContext is `@dataclass(frozen=True)` and is never mutated in place. S0 creates the immutable initial instance. Where the canonical field table explicitly assigns a field to S2/S5/S8, that stage may produce a replacement immutable ExecutionContext instance through the controlled `validate_replace()` mechanism. No LLM-derived semantic content may be stored in ExecutionContext. This is a controlled compatibility mechanism, not a general-purpose scratchpad.**

**Identity generation by stage:**
- S0 generates `trace_id` and `request_id`
- S2 (Intent Analysis) generates `task_id`
- S9 (Plan Creation) generates `execution_id` and `plan_id` (on Plan, not ExecutionContext)
- S9 (AGENTIC path) generates `branch_id` (on Plan, not ExecutionContext)
- S12 (Execute) generates `attempt_id` and `provider_call_id` (per step/attempt)

**`correlation_id` is a deprecated alias for `trace_id`.** Use `trace_id` everywhere in new code.

---

## 3. KernelResult — Adapter Response

```python
@dataclass(frozen=True)
class KernelResult:
    status: str           # "ok" | "partial" | "error" | "UNKNOWN"
    kernel: str           # kernel_op_id that produced this
    data: Any = None
    error: str | None = None
    attempt: int = 1      # Which attempt number
    undo_token: str | None = None  # Token for inverse operation
    metadata: dict | None = None   # Additional context (exception_type, etc.)
```

### Status Semantics

| Status | Meaning | Data | Error |
|--------|---------|------|-------|
| `ok` | Operation completed successfully | Result data | None |
| `partial` | Operation partially succeeded | Partial result | Summary of failures |
| `error` | Operation failed | None or partial | Error message |
| `UNKNOWN` | Outcome uncertain (timeout, network drop) | None or partial | Reason for uncertainty |

### Adapter Contract: NEVER Raise

```python
class SafeAdapterWrapper:
    def call(self, kernel_op_id: str, params: dict, binding: BindingRow) -> KernelResult:
        try:
            return self._adapter.call(kernel_op_id, params, binding)
        except Exception as e:
            logger.error(f"Adapter raised exception: {e}")
            return KernelResult(
                status="error",
                error=str(e),
                kernel=kernel_op_id,
                metadata={"exception_type": type(e).__name__},
            )
```

---

## 4. Plan & Step — Execution Blueprint

```python
@dataclass(frozen=True)
class Plan:
    id: str
    steps: list[Step]
    join_mode: str           # "all" | "any" | "threshold"
    budget_reserved: int
    created_at: float
    confirmations: list[str] # Confirmation tokens needed

@dataclass(frozen=True)
class Step:
    id: str
    kernel_op_id: str        # e.g., "ghl.contact_create"
    params: dict
    depends_on: list[str]    # Step IDs this depends on
    mutation: str            # "R" | "W" | "D" | "IRREVERSIBLE"
    risk: float              # 0.0-1.0 (CONSUMED from S5 effective_risk, never recomputed)
    cost: int                # Budget cost units
    retry_policy: dict       # {"max_attempts": int, "backoff": str, "safety": str}
                             # safety: "safe" | "idempotent" | "never"
                             # Precedence: step_policy → mutation_safety_ceiling → reliability_ceiling → provider_limit
                             # Effective value = min(all applicable ceilings)
    inverse: str | None      # Inverse kernel_op_id for rollback
    timeout: int             # Max seconds for this step
```

### Join Modes

| Mode | Meaning | Use Case |
|------|---------|----------|
| `all` | All steps must succeed | Critical operations |
| `any` | At least one step must succeed | Search/fetch operations |
| `threshold` | N of M steps must succeed | Bulk operations with tolerance |

### Step Constraints

| Field | Constraint |
|-------|-----------|
| `kernel_op_id` | Must be PRODUCTION_ENABLED in kernel_ops table |
| `params` | Must validate against kernel's input_schema |
| `depends_on` | Must reference existing step IDs in the same plan |
| `mutation` | Must be one of R/W/D/IRREVERSIBLE |
| `risk` | Must be 0.0-1.0 |
| `cost` | Must be positive integer |
| `retry_policy` | Dict with max_attempts (int), backoff (str), safety (str). Effective max_attempts = min(step_policy, mutation_safety_ceiling, reliability_ceiling, provider_limit) |
| `timeout` | Must be positive integer (seconds) |

---

## 5. CapabilityMetadata — Capability Definition

```python
@dataclass(frozen=True)
class CapabilityMetadata:
    capability_id: str
    name: str
    description: str
    mutation: str           # "R" | "W" | "D" | "IRREVERSIBLE"
    risk_floor: float       # Minimum risk (0.0-1.0)
    risk_rule: float        # Rule-based risk
    risk_implied: float     # Context-implied risk
    cost: int               # Budget cost units
    retry_safety: str       # "safe" | "idempotent" | "never"
    inverse: str | None     # Inverse operation for rollback
    truth_state: str                  # DRAFT | REVIEW | PRODUCTION_ENABLED | DEPRECATED
    schema: dict                      # Combined input/output schema
    tags: list[str]         # Categorization tags
```

---

## 6. BindingRow — Capability-to-Adapter Mapping

```python
@dataclass(frozen=True)
class BindingRow:
    id: str
    capability_id: str
    provider: str
    priority: int           # Lower = higher priority
    engine_module: str      # Python module path
    adapter_class: str      # Adapter class name
    is_active: bool
```

### Binding Resolution Flow

```
capability_id
  → provider (from binding)
    → engine_module (from ENGINE_MAP[provider])
      → kernel_meta.KERNEL_MAP[provider] → adapter_class (from binding)
        → adapter.call(kernel_op_id, params, binding)
```

### FrozenBindingIdentity — Frozen at S5 (PRODUCTION-READY)

```python
@dataclass(frozen=True)
class FrozenBindingIdentity:
    """The immutable result of S5 Provider Resolution.

    This is the ONLY binding information S12 receives — it can NEVER
    re-resolve or swap providers mid-execution.
    """
    binding_id: str                  # Selected binding row ID
    capability_id: str               # Matched capability
    kernel_op_id: str                # The actual operation to call
    provider: str                    # Provider prefix (e.g., "ghl_public")
    engine_module: str               # Python module path (e.g., "supr.kernel.engines.ghl")
    adapter_class: str               # Adapter class (e.g., "GHLPublicAdapter")
    effective_risk: float            # final_risk = max(risk_floor, risk_rule, risk_implied)
    effective_mutation: str          # "R" | "W" | "D" | "IRREVERSIBLE"
    resolved_at_stage: str           # Always "S5"
    selection_rank: int              # Tie-breaker rank (lower = selected)
```

### Binding Selection Algorithm (Deterministic, No Nondeterminism)

When multiple bindings match a capability, selection uses a strict tie-breaker:

```
1. priority ASC          (lower number = higher priority)
2. created_at ASC        (earlier = selected)
3. binding_id UUID ASC   (lexicographic)
```

The selected binding's `binding_id` is stored in `FrozenBindingIdentity.binding_id`.
S12 receives the frozen `FrozenBindingIdentity` and CANNOT re-resolve.

---

## 7. TaskProfile — Task Characterization

```python
@dataclass(frozen=True)
class TaskProfile:
    intent: str
    capabilities: list[Capability]
    graph_type: str         # "simple" | "chain" | "complex"
    steps_estimated: int
    mutations: list[str]    # Combined mutation types across all steps
    risk: float             # 0.0-1.0 (max of all step risks)
    cost: int               # Total budget cost
    requires_confirmation: bool
    resource_scope: str
    providers: list[str]
```

### Confirmation Requirements

| Condition | Requires Confirmation |
|-----------|----------------------|
| Any IRREVERSIBLE mutation | YES |
| Any D mutation with cost > 5 | YES |
| Total cost > 20 | YES |
| Total risk > 0.7 | YES |
| Cross-provider (3+ providers) | YES |

---

## 8. SafetyResult — Authorization Outcome

```python
@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    reason: str | None = None
    failed_check: str | None = None
```

### Safety Checks (all must pass)

```python
class SafetyGate:
    CHECKS = [
        "user_active",              # 1. User account is active and authenticated
        "tenant_active",            # 2. Tenant account is active
        "connection_active",        # 3. Connection is active and not expired
        "capability_granted",       # 4. User has the required capability (includes multi-workspace auth)
        "resource_scope",           # 5. Requested resource is within user's scope
        "circuit_breaker",          # 6. Provider circuit breaker is CLOSED (not OPEN)
        "budget_available",         # 7. Atomic budget reserve succeeds (row-level SQL)
        "mutation_safety",          # 8. Mutation is safe (includes binding_active, risk_within_tolerance, confirmation_required for D/IRREVERSIBLE)
    ]

    # Sub-checks within mutation_safety (check 8):
    SUB_CHECKS = {
        "mutation_safety": [
            "binding_active",          # Binding is_active=1
            "risk_within_tolerance",   # final_risk = max(risk_floor, risk_rule, risk_implied)
            "confirmation_required",   # D/IRREVERSIBLE has user confirmation token
        ]
    }
```

---

## 9. ExecutionResult — Execution Outcome

```python
@dataclass(frozen=True)
class ExecutionStatus(StrEnum):
    """Lifecycle state of an execution."""
    PENDING = "pending"
    RUNNING = "running"
    RECONCILING = "reconciling"     # Step(s) timed out, probing provider
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"

# NOTE: UNKNOWN is a StepState (§19), NOT an ExecutionStatus.
# When steps enter UNKNOWN, execution transitions to RECONCILING.

@dataclass(frozen=True)
class ExecutionOutcome(StrEnum):
    """Success/failure classification of completed steps."""
    SUCCESS = "success"           # All steps completed successfully
    PARTIAL = "partial"           # Some steps succeeded, some failed
    FAILURE = "failure"           # All steps failed

@dataclass(frozen=True)
class ReconciliationStatus(StrEnum):
    """UNKNOWN outcome resolution state."""
    NONE = "none"                 # No UNKNOWN outcomes
    PENDING_PROBE = "pending_probe"  # UNKNOWN outcomes awaiting probe
    CONFIRMED_SUCCESS = "confirmed_success"  # Probe confirmed execution
    CONFIRMED_FAILURE = "confirmed_failure"  # Probe confirmed no execution
    RECONCILING = "reconciling"   # Probe in progress

@dataclass(frozen=True)
class StepResult:
    step_id: str
    attempt_id: str
    status: ExecutionStatus
    outcome: ExecutionOutcome
    kernel_result: KernelResult | None = None
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.NONE
    budget_reservation_id: str | None = None
    duration_ms: int = 0

@dataclass(frozen=True)
class ExecutionResult:
    plan_id: str
    execution_status: ExecutionStatus  # lifecycle state
    outcome: ExecutionOutcome          # success/failure classification
    reconciliation_status: ReconciliationStatus  # UNKNOWN resolution state
    steps: dict[str, StepResult]       # step_id → StepResult
    budget_spent: int
    budget_reserved: int
    duration_ms: int
    started_at: float
    completed_at: float | None = None  # None if still running
```
### ExecutionResult Rules

| Rule | Description |
|------|-------------|
| `execution_status` | Lifecycle state of the execution |
| `outcome` | Aggregated outcome across all steps (SUCCESS/PARTIAL/FAILURE) |
| `reconciliation_status` | UNKNOWN resolution state (NONE if no UNKNOWN steps) |
| `budget_reserved` | Total budget units reserved (includes locked) |
| `steps` | Per-step results with attempt and reconciliation tracking |

---

## 10. ValidationResult — Adapter Parameter Validation

```python
@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: list[str]

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(is_valid=True, errors=[])

    @classmethod
    def error(cls, *errors: str) -> "ValidationResult":
        return cls(is_valid=False, errors=list(errors))
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | `bool` | True if params pass validation |
| `errors` | `list[str]` | Human-readable error messages when invalid |

**Rules**:
- Returned by `adapter.validate_params(kernel_op_id, params)`
- NEVER raises — returns ValidationResult.error() on validation failure
- Used by S11 (Validate Plan) to confirm plan parameters before execution

---

## 11. ProviderAdapter Contract

```python
class BaseAdapter(ABC):
    @abstractmethod
    async def call(self, kernel_op_id: str, params: dict,
                   binding: BindingRow, context: ExecutionContext) -> KernelResult:
        """Execute a kernel operation. Returns KernelResult, NEVER raises."""
        pass

    @abstractmethod
    async def validate_params(self, kernel_op_id: str,
                              params: dict) -> ValidationResult:
        """Validate params against the kernel's input schema."""
        pass

    @abstractmethod
    def get_kernel_meta(self, kernel_op_id: str) -> KernelMeta | None:
        """Return metadata for a kernel operation."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check if the provider API is reachable."""
        pass

    @abstractmethod
    def capabilities(self) -> list[str]:
        """List all kernel_op_ids this adapter supports."""
        pass
```

### Adapter Constraints
1. Adapters NEVER raise exceptions — always return `KernelResult(status="error", ...)`
2. Adapters NEVER call the control plane
3. Adapters NEVER make authorization decisions
4. Adapters NEVER modify ExecutionContext
5. Adapters NEVER call other adapters

---

## 12. Kernel Policy — Per-Operation Config

```yaml
# Defined in kernel_definitions.yaml
kernel_op_id: "ghl.contact_create"
mutation: "W"
cost: 3
risk_floor: 0.2
risk_rule: 0.2
risk_implied: 0.0
retry_safety: "safe"       # Idempotent with key
inverse: "ghl.contact_delete"
timeout: 30
rate_limit: 100            # Requests per minute
batch_size: 10             # Max operations per batch
```

### Mutation Cost Model

```python
MUTATION_COSTS = {
    "R": {
        "search": 1, "list": 1, "get": 1, "query": 1,
    },
    "W": {
        "create": 3, "update": 2, "patch": 2, "append": 2, "upsert": 3,
    },
    "D": {
        "delete": 5, "archive": 3, "remove": 4, "soft_delete": 3,
    },
    "IRREVERSIBLE": {
        "send_email": 3, "trigger_workflow": 5, "webhook": 3, "bulk_delete": 10,
    },
}
```

---

## 13. Confirmation — User Approval

```python
@dataclass(frozen=True)
class Confirmation:
    confirmation_id: str
    user_id: str
    conversation_id: str
    plan_id: str
    plan_hash: str          # CRIT-011: binds approval to specific plan
    operations: list[dict]   # Human-readable operation descriptions
    expires_at: float        # Unix timestamp
    consumed_at: float | None = None
```

### Confirmation Verification Contract

S10 (Confirmation) validates against the frozen Confirmation record. The check is:

```python
def verify_confirmation(confirmation: Confirmation, plan_hash: str) -> bool:
    """Verify confirmation is valid for this plan."""
    return (
        confirmation.consumed_at is None
        and confirmation.plan_hash == plan_hash
        and confirmation.expires_at > time.time()
    )
```

**Rules**:
1. `plan_hash` is SHA-256 of the frozen Plan object (computed at S9)
2. Confirmation is bound to a specific plan via `plan_hash` — plan mutation invalidates confirmation
3. `consumed_at` is set atomically at S11 before execution proceeds
4. Once consumed, a confirmation cannot be reused (single-use invariant)
5. If `plan_hash` changes after confirmation, the token is invalidated

### Confirmation Rules

| Rule | Implementation |
|------|---------------|
| Single-use | Token consumed atomically on first use |
| Time-limited | Expires after 5 minutes (300 seconds) |
| User-bound | Token tied to user_id + conversation_id |
| Specific | Message lists exact operations |

---

## 14. Error Hierarchy

```
SuprAgentsError (base)
├── ValidationError — input doesn't match schema
├── AuthorizationError — user lacks permission
├── ProviderError — external API failure
│   ├── RateLimitError — 429
│   ├── AuthError — 401/403
│   ├── NotFoundError — 404
│   └── ServerError — 5xx
├── BudgetError — budget insufficient or exceeded
├── CircuitOpenError — provider temporarily unavailable
├── TimeoutError — execution exceeded time limit
├── PlanError — plan is invalid or unexecutable
├── ExecutionError — step execution failed
├── InjectionError — prompt injection detected
├── UnmappedEngineError — kernel_op has no mapped engine
└── RegistryError — registry inconsistency detected
```

### Error Recovery Matrix

| Error Type | Recovery | User Sees |
|------------|----------|-----------|
| ValidationError | Return to clarify | "Please provide: [missing fields]" |
| AuthorizationError | No recovery | "You don't have permission for this" |
| ProviderError (rate limit) | Retry with backoff | "Service is busy, retrying..." |
| ProviderError (5xx) | Retry with circuit breaker | "Service temporarily unavailable" |
| CircuitOpenError | Wait for cooldown | "Service is down, try again in N minutes" |
| BudgetError | No recovery | "Budget exceeded. Current: X, needed: Y" |
| PlanError | Fall back to clarify | "I couldn't plan this, can you rephrase?" |
| ExecutionError (partial) | Consolidate results | "Partially completed: X of Y steps" |
| ExecutionError (permanent) | Dead letter | "This failed and needs manual attention" |

---

## 15. State Machines

### Execution States

```
PENDING → RUNNING → COMPLETED
            │
            ├─→ PARTIAL (some steps failed)
            │
            ├─→ FAILED (all steps failed)
            │
            ├─→ CANCELLED (user cancelled)
            │
            ├─→ TIMEOUT (exceeded time limit)
            │
            └─→ DEAD_LETTER (permanent failure, queued for retry)
```

### Confirmation States

```
PENDING ──[confirmed]──► CONSUMED ──→ execution proceeds
   │
   ├─[rejected]──► REJECTED ──→ execution cancelled
   │
   └─[expired]──► EXPIRED ──→ execution cancelled
```

### Circuit Breaker States

```
CLOSED ──[failures >= 5]──► OPEN ──[cooldown 60s]──► HALF_OPEN
  ▲                                    │                        │
  └────────── [success >= 3] ──────────┘                        │
                                                                   ▼
                                                        CLOSED (if success)
                                                        OPEN (if failure)
```

### Step States

```
PENDING → RUNNING → COMPLETED
            │
            ├─→ FAILED (after all retries exhausted)
            │
            ├─→ SKIPPED (dependency not met)
            │
            └─→ PARTIAL (some sub-operations failed)
```

---

## 16. Budget Reservation Lifecycle — Canonical Model

### 16.1 BudgetResult

```python
@dataclass(frozen=True)
class BudgetResult:
    allowed: bool
    reason: str | None = None
    reservation: BudgetReservation | None = None
```

### 16.2 BudgetReservation

```python
@dataclass(frozen=True)
class BudgetReservation:
    reservation_id: str           # UUID v4
    tenant_id: str                # Budget owner (RLS key — NOT user_id)
    user_id: str                  # Attribution only
    execution_id: str             # Parent execution
    step_id: str                  # Specific step
    cost: int                     # Minor units
    status: ReservationState      # reserved | locked | committed | released
    created_at: float
    committed_at: float | None = None
    released_at: float | None = None
    locked_at: float | None = None
```

### 16.3 ReservationState

```python
class ReservationState(StrEnum):
    RESERVED = "reserved"
    LOCKED = "locked"
    COMMITTED = "committed"
    RELEASED = "released"
```

### 16.4 ReservationStateValidator — Legal Transition Matrix

```python
class ReservationStateValidator:
    LEGAL_TRANSITIONS: dict[ReservationState, set[ReservationState]] = {
        ReservationState.RESERVED: {
            ReservationState.COMMITTED,
            ReservationState.RELEASED,
            ReservationState.LOCKED,
        },
        ReservationState.LOCKED: {
            ReservationState.COMMITTED,
            ReservationState.RELEASED,
            ReservationState.LOCKED,
        },
        ReservationState.COMMITTED: set(),    # terminal
        ReservationState.RELEASED: set(),     # terminal
    }

    def validate(self, from_state: ReservationState, to_state: ReservationState) -> None:
        if from_state not in self.LEGAL_TRANSITIONS:
            raise StateError(f"Unknown reservation state: {from_state}")
        if to_state not in self.LEGAL_TRANSITIONS[from_state]:
            raise StateError(f"Illegal reservation transition: {from_state} → {to_state}")
```

**Rules**:
1. Terminal states (COMMITTED, RELEASED) have no outgoing transitions
2. LOCKED is the only state with self-transition (probe inconclusive again)
3. Every transition must be atomic with the DB UPDATE (rowcount check)
4. Attempting illegal transition raises `StateError`

### 16.5 BudgetFlow — End-to-End Lifecycle

```
S12: BudgetTracker.reserve(tenant_id, user_id, execution_id, step_id, cost)
    │
    ├─► UPDATE budgets SET budget_pool = budget_pool - cost, reserved = reserved + cost
    │   WHERE tenant_id = :tid AND budget_pool >= :cost
    │
    ├─► INSERT budget_reservations (status='reserved')
    │
    └─► Returns BudgetResult(allowed=True, reservation=R1)
        OR BudgetResult(allowed=False, reason="Budget: X remaining, need Y")

    SUCCESS → BudgetTracker.commit(R1)
    │   UPDATE budget_reservations SET status='committed', committed_at=NOW()
    │   (budget_pool already deducted — no further change)
    │
    FAILURE → BudgetTracker.release(R1)
    │   UPDATE budget_reservations SET status='released', released_at=NOW()
    │   UPDATE budgets SET budget_pool = budget_pool + cost, reserved = reserved - cost
    │
    ├─► TIMEOUT (UNKNOWN) → BudgetTracker.lock(R1)
    │   UPDATE budget_reservations SET status='locked', locked_at=NOW()
    │   (budget_pool stays deducted — DO NOT release)
    │
    └─► PROBE RESULT:
        ├─► EXECUTED → BudgetTracker.commit(R1)
        ├─► NOT_EXECUTED → BudgetTracker.release(R1)
        └─► INCONCLUSIVE → BudgetTracker.lock(R1) again (stays locked)
```

### 16.6 BudgetLockSweeper

```python
class BudgetLockSweeper:
    """Auto-releases budget locks that exceeded timeout."""
    LOCK_TIMEOUT = 86400  # 24 hours

    def sweep_expired_locks(self) -> int:
        """Release locks older than LOCK_TIMEOUT. Returns count released."""
        cutoff = time.time() - self.LOCK_TIMEOUT
        expired = self._db.query(
            "SELECT reservation_id FROM budget_reservations "
            "WHERE status = 'locked' AND locked_at < :cutoff",
            {"cutoff": cutoff}
        ).fetchall()
        count = 0
        for row in expired:
            reservation = self._load_reservation(row.reservation_id)
            if reservation:
                self._budget.release(reservation)
                count += 1
        return count
```

### 16.7 Atomicity Rules

| Rule | Implementation |
|------|---------------|
| reserve uses atomic UPDATE | `UPDATE budgets SET budget_pool = budget_pool - :cost, reserved = reserved + :cost WHERE tenant_id = :tid AND budget_pool >= :cost` |
| commit checks status | `UPDATE budget_reservations SET status='committed' WHERE reservation_id = :rid AND status IN ('reserved', 'locked')` |
| release checks status | `UPDATE budget_reservations SET status='released' WHERE reservation_id = :rid AND status IN ('reserved', 'locked')` |
| release restores budget | `UPDATE budgets SET budget_pool = budget_pool + :cost, reserved = reserved - :cost WHERE tenant_id = :tid` |
| lock transitions only from reserved/locked | WHERE status IN ('reserved', 'locked') |
| All operations use rowcount | If rowcount == 0 → operation already completed → idempotent no-op |
| Budget locked on timeout | Reserved budget stays locked until probe resolves or sweeper fires |
| All operations return bool | True if state changed, False if already in target state (idempotent) |

### 16.8 BudgetTracker API

```python
class BudgetTracker:
    def reserve(self, tenant_id: str, user_id: str,
                execution_id: str, step_id: str, cost: int) -> BudgetResult:
        """Atomically reserve budget. Creates reservation row. Returns BudgetResult."""

    def commit(self, reservation: BudgetReservation) -> bool:
        """Transition reserved/locked → committed. Idempotent. Returns True if changed."""

    def release(self, reservation: BudgetReservation) -> bool:
        """Transition reserved/locked → released. Restores budget_pool. Idempotent."""

    def lock(self, reservation: BudgetReservation) -> None:
        """Transition reserved → locked (timeout, inconclusive probe)."""

    def sweep_expired_locks(self) -> int:
        """Release locks older than 24h. Returns count released."""
```

### 16.9 Budget Rules

1. Budget is per-tenant, not per-user — `budgets.budget_pool` is the tenant's shared pool
2. `user_id` in reservations is for attribution/audit only, not the budget gate key
3. Reserve at S12 (Execute) with full context: `(tenant_id, user_id, execution_id, step_id, cost)`. S8 performs informational affordability precheck only — the authoritative reservation happens atomically at S12.
3a. S8 performs an informational affordability precheck only. Its result does NOT guarantee budget availability at S12. The authoritative gate is the atomic reserve() at S12.
4. Timeout = LOCKED, not RELEASED — budget stays deducted until probe confirms outcome
5. Inconclusive probe = stays LOCKED — never auto-release without manual review or 24h sweep
6. Every reserve must have exactly one terminal state: COMMITTED or RELEASED
7. LOCKED is a transient state — must resolve to COMMITTED or RELEASED within 24 hours
8. `BudgetResult.allowed` is the ONLY budget gate — no separate preflight check

### 16.10 Budget Invariants

1. `SUM(reserved) + SUM(committed) + budget_pool = total_budget` (always holds)
2. Every `reserve()` creates exactly one row in `budget_reservations`
3. Every reservation reaches exactly one terminal state (COMMITTED or RELEASED)
4. `release()` never changes `budget_pool` if reservation is already RELEASED
5. `commit()` never changes `budget_pool` (already deducted at reserve time)
6. No reservation row is ever deleted — INSERT-only for audit trail

---

## 17. Idempotency

### Idempotency Key

**Canonical rule**: `request_id` (generated at S0) is the canonical idempotency key for duplicate detection. For provider-call level idempotency, use `provider_call_id`. Deterministic SHA-256 hashing is not used for request-level deduplication.

```python
def compute_provider_call_id(context: ExecutionContext, kernel_op_id: str, attempt: int) -> str:
    """Compute provider-call idempotency key (per attempt)."""
    return f"{context.request_id}:{kernel_op_id}:{attempt}"
```

### Idempotency Rules

| Mutation | Idempotency Key Required |
|----------|--------------------------|
| R | No |
| W | Yes |
| D | Yes (critical) |
| IRREVERSIBLE | Yes (critical) |

### Idempotency Ledger

```python
@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    kernel_op_id: str
    result: KernelResult
    created_at: float
    expires_at: float      # 24 hours from creation
```

### Rules
1. Every W/D/IRREVERSIBLE operation generates an idempotency key
2. Key is checked BEFORE execution
3. If key exists and not expired → return cached result
4. If key exists and expired → execute fresh, update record
5. Keys expire after 24 hours
6. Ledger is cleaned up periodically

---

## 18. Billing Data Contracts

### 18.1 BillingUsageRecord

```python
@dataclass(frozen=True)
class BillingUsageRecord:
    usage_id: str
    tenant_id: str
    user_id: str | None
    resource_id: str
    kernel_op_ref: str
    quantity: int
    unit: str
    provider: str
    timestamp: str          # ISO 8601 UTC
    billing_period: str     # D-BILL1: Derived from UTC timestamp at INSERT time as YYYY-MM
    idempotency_key: str
    status: str             # "pending" | "billed" | "adjusted" | "refunded"
    evidence_ref: str       # Links to trace_id (canonical) or execution_id
    metadata: dict | None   # Additional context (model name, tokens, etc.)
```

**Billing Record Rules**:
1. Every usage record links to an evidence_ref (trace_id or execution_id)
2. Quantity is always an integer (minor units for currency)
3. D-BILL1: Billing period is derived client-side from the UTC timestamp at INSERT time as `YYYY-MM`. No batch computation, no periodic job.
4. Idempotency key prevents duplicate billing: `hash(tenant_id + kernel_op_ref + params_hash + timestamp_truncated_to_minute)`
5. Status transitions: `pending` → `billed` → (adjusted/refunded)

### 18.2 ResourceMeter

```python
@dataclass(frozen=True)
class ResourceMeter:
    resource_id: str
    resource_type: str      # "api_call" | "token" | "storage" | "compute" | "bandwidth"
    provider: str
    resource_name: str
    kernel_op_ref: str | None
    unit: str
    unit_price: int         # Minor units (cents), always integer
    currency: str           # ISO 4217, default "USD"
    tier: str               # "standard" | "volume" | "enterprise"
    is_free: bool
    effective_from: str     # ISO 8601
    effective_to: str | None  # ISO 8601, null = active
    version: int
```

**Resource Meter Rules**:
1. Only ONE active pricing per resource at any time (effective_from <= now < effective_to)
2. Pricing changes are logged to pricing_history — never DELETE old pricing
3. A new kernel operation MUST have a meter entry before it can be used
4. Default tier is "standard" if not specified
5. unit_price = 0 + is_free = True = explicit free tier (not just price = 0)

### 18.3 BillingEvent

```python
@dataclass(frozen=True)
class BillingEvent:
    event_id: str
    event_type: str          # See §17.4
    tenant_id: str
    resource_id: str | None
    usage_id: str | None
    invoice_id: str | None
    amount: int | None       # Minor units
    currency: str            # ISO 4217
    metadata: dict | None
    timestamp: str           # ISO 8601 UTC
    actor: str               # "system" | "admin" | "api" | "user"
    reason: str | None
    idempotency_key: str
```

### 18.4 Event Types

| Event Type | Trigger | Effect |
|------------|---------|--------|
| `usage_recorded` | Resource consumed | Increments accrual |
| `usage_adjusted` | Admin correction | Adjusts quantity |
| `usage_refunded` | Refund issued | Marks as refunded, creates credit |
| `invoice_generated` | End of billing period | Locks usage, creates invoice |
| `invoice_paid` | Payment received | Marks invoice as paid |
| `invoice_overdue` | Payment past due | Marks overdue, triggers alert |
| `pricing_changed` | New pricing applied | Records pricing event |
| `subscription_changed` | Plan/tier change | Recalculates from effective date |
| `credit_applied` | Promotional credit | Creates credit balance entry |
| `dispute_opened` | Customer dispute | Freezes related charges |

### 18.5 Invoice

```python
@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    invoice_number: str     # e.g., "INV-2026-09-0001"
    tenant_id: str
    billing_period_start: str  # ISO date
    billing_period_end: str    # ISO date
    generated_at: str       # ISO 8601
    sent_at: str | None
    paid_at: str | None
    due_date: str           # ISO date
    status: str             # "draft" | "generated" | "sent" | "paid" | "overdue" | "void"
    subtotal: int           # Minor units
    discount_amount: int    # Minor units
    tax_amount: int         # Minor units
    credit_amount: int      # Minor units
    total: int              # Minor units
    currency: str           # ISO 4217
    version: int
    metadata: dict | None
```

### 18.6 InvoiceItem

```python
@dataclass(frozen=True)
class InvoiceItem:
    item_id: str
    invoice_id: str
    resource_name: str
    resource_id: str
    quantity: int
    unit: str
    unit_price: int         # Minor units
    line_total: int         # quantity × unit_price
    tier: str
    discount_pct: int       # 0-100
```

### 18.7 CreditBalance

```python
@dataclass(frozen=True)
class CreditBalance:
    credit_id: str
    tenant_id: str
    amount: int             # Minor units, positive = credit available
    currency: str
    source: str             # "promo" | "refund" | "dispute" | "adjustment"
    source_ref: str | None  # Reference to source event
    expires_at: str | None  # ISO 8601, null = no expiry
    applied_at: str | None
    status: str             # "available" | "applied" | "expired"
```

### 18.8 Cost Calculation Rules

```python
def calculate_total_cost(tenant_id, billing_period):
    """Calculate total cost for a tenant for a billing period."""

    # 1. Get all usage records for the period
    usage = db.query("""
        SELECT * FROM usage_records
        WHERE tenant_id = ? AND billing_period = ? AND status = 'billed'
    """, tenant_id, billing_period)

    # 2. For each usage record, get the applicable pricing
    subtotal = 0
    for record in usage:
        pricing = get_applicable_price(record.resource_id, record.timestamp)
        subtotal += record.quantity * pricing.unit_price

    # 3. Apply volume discounts
    discount = calculate_volume_discount(subtotal, total_calls)

    # 4. Apply credits (FIFO)
    credits = get_available_credits(tenant_id)
    credit_applied, remaining = apply_credits(subtotal - discount, credits)

    # 5. Calculate tax
    tax = calculate_tax(subtotal - discount - credit_applied)

    # 6. Final total
    total = subtotal - discount - credit_applied + tax

    return {
        "subtotal": subtotal,
        "discount": discount,
        "credits_applied": credit_applied,
        "tax": tax,
        "total": total,
    }
```

### 18.9 Billing Golden Rules

| Rule | Why |
|------|-----|
| Every charge traces to a usage record | No phantom charges |
| Usage records are never deleted | Audit trail required |
| All amounts in integer minor units | No floating-point arithmetic |
| All timestamps in UTC | No timezone ambiguity |
| Every pricing has effective range | No pricing without start/end dates |
| Invoice generation is idempotent | Same input → same invoice |
| Credits expire explicitly | Never silently extend |
| Billing events are immutable | INSERT-only, no UPDATE/DELETE |
| Every charge links to evidence | `evidence_ref` points to execution trace |
| Discounts never stack | One discount pass per calculation |

### 18.10 Billing Cautions

| Caution | Risk | Mitigation |
|---------|------|------------|
| Pricing change mid-month | Billing discontinuity | Use effective_from/effective_to timestamps |
| Floating-point rounding | $0.1 + $0.2 ≠ $0.3 | Use integer minor units throughout |
| Duplicate usage records | Double-billing | Idempotency key per tenant+kernel_op+time window |
| Usage from non-billable path | Internal calls billed | Billing metadata flag on ExecutionContext — internal exempt |
| Negative invoice totals | Free tier with tax | Tax = 0 if final_total <= 0; explicit `is_credit_invoice` flag |
| Timezone drift | Period boundaries shift | All timestamps UTC, periods = UTC calendar months |

### 18.11 Billing Possible Bugs

| Bug | Scenario | Detection | Fix |
|-----|----------|-----------|-----|
| Missing pricing for new kernel_op | New adapter kernel has no meter entry | CI: all registered kernel_ops have billing entries | Onboarding tool creates meter on kernel creation |
| Overlapping effective ranges | Two pricing entries active | DB constraint: at most 1 active pricing per resource | Unique constraint on active range |
| Token undercounting | Provider reports fewer tokens | Compare provider-reported vs estimated | Use provider-reported counts |
| Partial execution billed | Step failed mid-way | Only record on COMPLETED steps | Check step status before recording |
| Clock skew on timestamps | Different server times | Use UTC, server-side timestamp | Never trust client timestamps |
| Duplicate invoicing | Same usage billed twice | Unique constraint on (tenant, period) | Idempotent generation |

---

## 19. StepState — Execution State Enum

### 19.1 Definition

```python
from enum import StrEnum

class StepState(StrEnum):
    PENDING = "pending"           # Step created, not yet started
    RUNNING = "running"           # Currently executing
    COMPLETED = "completed"       # Successfully finished
    PARTIAL = "partial"           # Partial success (some sub-operations failed)
    FAILED = "failed"             # Hard failure, not retryable
    CANCELLED = "cancelled"       # Did not start or stopped: cancelled by the user or by the system (reason in terminal_reason, gate C22)
    SKIPPED = "skipped"           # Precondition not met, step skipped
    TIMEOUT = "timeout"           # Exceeded time limit → maps to UNKNOWN
    UNKNOWN = "unknown"           # Outcome uncertain (network drop, timeout)
    PENDING_PROBE = "pending_probe"  # Waiting for upstream probe (D-PIPE1)
    DEAD_LETTER = "dead_letter"   # Permanent failure, escalated to human

### 19.2 Legal Transitions

```python
# gate v9 repair (C24): aligned with STATE_TRANSITIONS §2 and
# S12_S15_EXECUTION_GATE Appendix A.2 (which also lists the reason codes and guards).
STEP_TRANSITIONS = {
    StepState.PENDING: {StepState.RUNNING, StepState.SKIPPED, StepState.CANCELLED},
    # PENDING → PENDING_PROBE removed: a step that never started has nothing to probe.
    StepState.RUNNING: {StepState.COMPLETED, StepState.PARTIAL, StepState.FAILED,
                        StepState.TIMEOUT, StepState.CANCELLED, StepState.PENDING_PROBE},
    # RUNNING → PARTIAL and RUNNING → CANCELLED are legal but not produced in S12–S15.
    StepState.TIMEOUT: {StepState.PENDING_PROBE},
    # Every timeout is probed (gate C6). TIMEOUT → UNKNOWN / DEAD_LETTER are illegal.
    StepState.UNKNOWN: {StepState.PENDING_PROBE, StepState.DEAD_LETTER},
    # UNKNOWN is never written in S12–S15 (gate C24). UNKNOWN → FAILED is illegal (C6).
    StepState.PENDING_PROBE: {StepState.COMPLETED, StepState.PENDING,
                              StepState.FAILED, StepState.DEAD_LETTER},
    # → FAILED only on a definitive failure (probe EXECUTED_FAILURE, ledger failure,
    #   verification FAIL); → PENDING only on NOT_EXECUTED / no dispatch marker /
    #   read_reexecution_safe (gate C6, C35).
    StepState.PARTIAL: set(),      # No outgoing edge; not produced.
    StepState.FAILED: set(),       # Terminal
    StepState.SKIPPED: set(),      # Terminal
    StepState.CANCELLED: set(),    # Terminal
    StepState.COMPLETED: set(),    # Terminal
    StepState.DEAD_LETTER: set(),  # Terminal
}
```

**Note**: FAILED is terminal for the step. Retries happen at the attempt level before the step enters FAILED state. The guard's retry loop (RELIABILITY.md §8) operates on attempts, not step states. Once a step enters FAILED state, all attempts are exhausted and no further retries are possible. Escalation to DEAD_LETTER happens at the execution level (LeaseRecovery), not via a step state transition.

### 19.2 Legal Transitions (Text)

```
PENDING → RUNNING          (step starts executing; its reservation is locked in the same transaction)
PENDING → SKIPPED          (dependency failed, step not needed — terminal_reason dependency_failed)
PENDING → CANCELLED        (did not start: cancelled by the user or by the system — terminal_reason required)

RUNNING → COMPLETED        (verified success)
RUNNING → FAILED           (non-retryable error, retries exhausted, or verification FAIL)
RUNNING → TIMEOUT          (timeout exceeded)
RUNNING → PENDING_PROBE    (outcome or verification uncertain; crash recovery)
RUNNING → PARTIAL          (legal, not produced in S12–S15)
RUNNING → CANCELLED        (legal, not produced: an in-flight step is resolved first)

TIMEOUT → PENDING_PROBE    (every timeout is probed)
UNKNOWN → PENDING_PROBE    (legal; UNKNOWN is never written in S12–S15)
UNKNOWN → DEAD_LETTER      (legal; UNKNOWN is never written in S12–S15)

PENDING_PROBE → COMPLETED  (probe confirms executed success; verification passed)
PENDING_PROBE → PENDING    (probe confirms not executed, or no dispatch marker — retry)
PENDING_PROBE → FAILED     (definitive failure only)
PENDING_PROBE → DEAD_LETTER (inconclusive after the bounded attempts)

COMPLETED, FAILED, CANCELLED, SKIPPED, DEAD_LETTER → (terminal)
PARTIAL → (no outgoing edge)
```

> **S12–S15 gate v9 repair (C24):** The previous text list also allowed RUNNING → DEAD_LETTER, RUNNING → SKIPPED, TIMEOUT → UNKNOWN and UNKNOWN → FAILED, and called TIMEOUT terminal. Those contradicted STATE_TRANSITIONS §2 and are removed. Retries happen inside RUNNING (attempt counter), not through state transitions.

**Note**: FAILED is terminal for the step. Retries happen at the attempt level before the step enters FAILED state. Once a step enters FAILED state, all attempts are exhausted and no further retries are possible. Escalation to DEAD_LETTER happens at the execution level (LeaseRecovery), not via a step state transition.

### 19.3 Illegal Transitions (raise StateError)

| From | To | Why Illegal |
|------|----|-------------|
| PENDING | COMPLETED | Skip RUNNING |
| PENDING | PARTIAL | Skip RUNNING |
| COMPLETED | RUNNING | Terminal state |
| COMPLETED | FAILED | Terminal state |
| FAILED | COMPLETED | Terminal state |
| CANCELLED | RUNNING | Terminal state |
| DEAD_LETTER | any | Terminal state |
| PENDING | PENDING_PROBE | Nothing to probe before start (gate C24) |
| RUNNING | DEAD_LETTER | Must pass through PENDING_PROBE (gate C24) |
| RUNNING | SKIPPED | SKIPPED is only for steps that never started (gate C22) |
| TIMEOUT | UNKNOWN / DEAD_LETTER | Every timeout is probed (gate C6) |
| UNKNOWN | FAILED | Must pass through PENDING_PROBE (gate C6) |

### 19.4 StepTerminalReason (gate C22, C23, C35)

```python
class StepTerminalReason(StrEnum):
    """Why a step ended CANCELLED or SKIPPED. Closed set; stored in
    execution_steps.terminal_reason (CHECK constraint). Values may be added, never
    removed or renamed."""
    USER_CANCELLED = "user_cancelled"
    ADMISSION_REJECTED = "admission_rejected"
    ADMISSION_EXHAUSTED = "admission_exhausted"
    NO_WORKER = "no_worker"
    LEASE_UNAVAILABLE = "lease_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PREFLIGHT_FAILED = "preflight_failed"
    NOT_EXECUTED_NO_RETRY = "not_executed_no_retry"
    DEPENDENCY_FAILED = "dependency_failed"
    RUN_DEAD_LETTERED = "run_dead_lettered"
    AUTHORIZATION_REVOKED = "authorization_revoked"
    KILL_SWITCH_ENGAGED = "kill_switch_engaged"
    BINDING_INVALID = "binding_invalid"
    CREDENTIAL_INVALID = "credential_invalid"
```

### 19.5 ProbeOutcome (gate §9, C32)

```python
class ProbeOutcome(StrEnum):
    EXECUTED_SUCCESS = "executed_success"
    EXECUTED_FAILURE = "executed_failure"
    NOT_EXECUTED = "not_executed"
    INCONCLUSIVE = "inconclusive"   # also the result of any exception, and the BaseAdapter default
```

---

---

## 20. BudgetTracker — Atomic Budget Operations (Deprecated — See §16)

> **NOTE**: The canonical budget reservation model is in **Section 16** above.
> This section is retained for historical reference only. Implement §16.

### 20.1 API (Deprecated)

```python
class BudgetTracker:
    def reserve(self, tenant_id: str, amount: int, execution_id: str) -> bool:
        """Atomically reserve budget. Returns True if reserved, False if insufficient."""
        pass

    def commit(self, tenant_id: str, execution_id: str, amount: int) -> bool:
        """Commit reserved budget as spent. Returns True if committed."""
        pass

    def release(self, tenant_id: str, execution_id: str, amount: int) -> bool:
        """Release reserved budget back. Returns True if released."""
        pass

    def get_available(self, tenant_id: str) -> int:
        """Get current available budget. Returns int (minor units)."""
        pass

    def is_healthy(self, tenant_id: str) -> bool:
        """Check if tenant has any budget remaining."""
        pass
```

**DEPRECATED**: This API uses `(tenant_id, execution_id, amount) → bool` signature.
The canonical API in §16 uses `(reservation: BudgetReservation) → bool` with full
step context and atomic reservation rows. Replace all references to this section
with §16.

---

### 20.3 Budget States

| State | Meaning |
|-------|---------|
| `available` | Unreserved budget |
| `reserved` | Budget reserved for in-flight execution |
| `spent` | Budget committed as spent |
| `released` | Budget returned from reservation |

---

## 20a. StageStatus — Pipeline Stage Status Enum

```python
class StageStatus(StrEnum):
    """Pipeline stage output status — maps to ENVELOPE status for user-facing output."""
    NORMAL = "normal"         # Stage completed, proceed to next
    CLARIFY = "clarify"       # Need more info → short-circuit to S15
    DENY = "deny"             # Safety/auth failure → short-circuit to S15
    ERROR = "error"           # Internal error → short-circuit to S15
    PROBE = "probe"           # Probe result from S13 → short-circuit to S15
```

**Cordon Points** (stages that can short-circuit):

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

## 21. PathDecision — Execution Path Enum

### 21.1 Definition

```python
class PathDecision(StrEnum):
    FAST = "fast"           # Single read, high confidence, no LLM in execution
    WORKFLOW = "workflow"   # 2-5 sequential steps, no LLM in execution
    AGENTIC = "agentic"     # 5+ steps, complex planning (LLM in execution)
    CLARIFY = "clarify"     # Low confidence / missing info → ask user
    DENY = "deny"           # Safety check failed → stop execution
```

### 21.2 Routing Rules (D-06)

| Graph Type | Step Count | Execution Path | M0/M1 Status |
|-----------|-----------|----------------|-------------|
| Simple | 1 step | FAST | Active |
| Chain | 2-5 steps | WORKFLOW | Active |
| Complex | 6+ steps | CLARIFY | Active (AGENTIC deferred to M2) |

**Note:** AGENTIC path (5+ steps with LLM-guided execution) is deferred to M2 per REVIEW_CORRECTIONS.md CORR-007. In M0/M1, Complex (6+ steps) routes to CLARIFY for user decomposition. Previous version incorrectly routed 5+ steps to AGENTIC and included confidence thresholds — confidence routing is handled at S7.

---

## 22. RetryDecision — Retry Action Enum

### 22.1 Definition

```python
class RetryDecision(StrEnum):
    RETRY = "retry"           # Retry with backoff
    NO_RETRY = "no_retry"     # Do not retry (succeeded or permanent failure)
    EXHAUSTED = "exhausted"   # Max retries reached, escalate to dead letter
```

### 22.2 Retry Rules by Mutation Type

**Ownership**: MUTATION_SAFETY defines the ceiling (whether retry is semantically allowed). RELIABILITY defines the mechanics (backoff, storm guard, circuit breaker). The effective max is `min(step_policy.max_attempts, mutation_safety_ceiling, reliability_ceiling, provider_limit)`.

| Mutation | Max Retries | Backoff | When |
|----------|-------------|---------|------|
| R (Read) | 3 | Exponential (1s, 2s, 4s) | On error/UNKNOWN |
| W (Write) | 2 (if idempotent) | Exponential | On error/UNKNOWN only if idempotent |
| D (Delete) | 2 (if idempotent) | Exponential | On error/UNKNOWN only if idempotent |
| IRREVERSIBLE | 0 | N/A | NEVER retry — go to dead letter |
| UNKNOWN | 0 (D/IRREVERSIBLE) | Probe only | D/IRREVERSIBLE: never retry. R/W: probe first |

### 22.3 Retry Storm Guard

| Rule | Value |
|------|-------|
| Max concurrent retries | 5 |
| Storm threshold exceeded | Block new retries, wait for cooldown |
| Cooldown period | 2x last retry delay |

---

## 23. DeadLetter — Permanent Failure Record

### 23.1 Definition

```python
@dataclass(frozen=True)
class DeadLetter:
    dead_letter_id: str       # UUID
    execution_id: str         # Parent execution
    step_id: str              # Failed step
    attempt_id: str           # Final attempt
    kernel_op_id: str         # Operation that failed
    error: str                # Error message
    error_type: str           # Error category
    mutation_type: str        # R, W, D, IRREVERSIBLE — CRIT-007: needed for retry decision
    is_idempotent: bool       # CRIT-007: needed for retry decision
    retry_count: int          # How many times retried
    max_retries: int          # Max allowed retries for this mutation type
    next_retry_at: float | None  # Next retry timestamp, None if exhausted
    failed_at: float          # Unix timestamp
    status: str               # DeadLetterStatus: "pending" | "retrying" | "resolved" | "abandoned" (STATE_TRANSITIONS §9)
    retry_mode: str           # "PROBE" | "VERIFY" | "NONE" — set at creation, never changed (gate C21, D5)
    origin: str               # "execution" | "rollback" (gate C27)
    tenant_id: str            # From the run (gate C29, C34)
    evidence: dict            # Attempts, probe results, verifier observations, classification (never empty)
    episode_id: str | None = None          # step_reconciliations episode that produced it
    resolution_outcome: str | None = None  # "EXECUTED" | "NOT_EXECUTED" | "UNDETERMINED"; required when resolved/abandoned
    resolution_notes: str | None = None
    resolved_at: float | None = None
    resolved_by: str | None = None
```


> **S12–S15 gate v9 repair (C29):** `escalation_status` (pending/escalated/resolved) is replaced by `status`, which follows the canonical dead-letter machine. Escalation is an alert event, not a state. `error_type` is one of `transient`, `permanent`, `data`, `unknown_unresolved`.

### 23.2 Escalation Flow

```
DEAD_LETTER created (S14)
  → status = "pending"; alert event recorded for permanent / unknown_unresolved
  → Retry per retry_mode (PROBE: probe only; VERIFY: verification only; NONE: none)
  → Human reviews and resolves
    → status = "resolved" (or "abandoned" after retries), resolution_outcome set
    → resolution_notes filled in
    → resolved_at, resolved_by set
```

---

## 24. ResponseFormatter — S15 Output

### 24.1 Definition

```python
class ResponseFormatter:
    def format(self, envelope: Envelope, context: ExecutionContext) -> str:
        """Format Envelope into user-facing message for Claude Code."""
        pass
    
    def format_error(self, envelope: EnvelopeError) -> str:
        """Format error for user display."""
        pass
    
    def format_confirm(self, plan: Plan, profile: TaskProfile) -> Envelope:
        """Format confirmation request with operation details."""
        pass
    
    def format_clarify(self, missing: list[str]) -> Envelope:
        """Format clarification request for missing info."""
        pass
```

### 24.2 Output Formats

| Envelope Status | Claude Code Output |
|----------------|-----------------|
| ok | Success message + results summary |
| partial | Partial success message + failed steps list |
| error | Error message + suggested action |
| clarify | Question asking for missing info |
| confirm | Description of what will happen + Yes/No buttons |

---

## 25. KernelMeta — Per-Operation Metadata

### 25.1 Definition

```python
@dataclass(frozen=True)
class KernelMeta:
    kernel_op_id: str
    mutation: str            # "R" | "W" | "D" | "IRREVERSIBLE"
    cost: int
    risk_floor: float        # Minimum risk (0.0-1.0)
    risk_rule: float         # Rule-based risk
    risk_implied: float      # Context-implied risk
    retry_safety: str        # "safe" | "idempotent" | "never"
    inverse: str | None      # Inverse kernel_op_id
    timeout: int             # Max seconds
    input_schema: dict       # JSON schema for params
    output_schema: dict      # JSON schema for results
    postcondition_verify: bool  # Requires read-back verification
    capabilities: list[str]  # Required capability_ids
```

### 25.2 KERNEL_MAP

```python
KERNEL_MAP: dict[str, KernelMeta] = {
    "ghl.contact_create": KernelMeta(...),
    "ghl.contact_update": KernelMeta(...),
    # ... all 94 kernels
}
```

---

## 26. StateTransitionValidator — Legal Transition Matrix

### 26.1 Definition

```python
class StateTransitionValidator:
    LEGAL_TRANSITIONS: dict[StepState, set[StepState]] = {
        StepState.PENDING: {StepState.RUNNING, StepState.CANCELLED, StepState.PENDING_PROBE},
        # CRIT-009: PENDING → PENDING_PROBE: step timed out before starting
        StepState.RUNNING: {
            StepState.COMPLETED,
            StepState.PARTIAL,
            StepState.FAILED,
            StepState.CANCELLED,
            StepState.TIMEOUT,
            StepState.DEAD_LETTER,
            StepState.PENDING_PROBE,   # CRIT-009: timeout → probe directly
        },
        StepState.TIMEOUT: set(),  # CRIT-009: TIMEOUT is terminal — no outgoing transitions
        StepState.UNKNOWN: {
            StepState.PENDING_PROBE,   # CRIT-009: UNKNOWN → probe
            StepState.DEAD_LETTER,
            StepState.FAILED,
        },
        StepState.PENDING_PROBE: {
            StepState.COMPLETED,       # Probe confirmed executed
            StepState.PENDING,         # Probe confirmed not executed
            StepState.DEAD_LETTER,     # Probe inconclusive
            StepState.FAILED,          # Probe error
        },
        # Terminal states — no outgoing transitions
        StepState.COMPLETED: set(),
        StepState.FAILED: set(),
        StepState.CANCELLED: set(),
        StepState.DEAD_LETTER: set(),
        StepState.SKIPPED: set(),
        StepState.PARTIAL: set(),
    }

    def validate(self, from_state: StepState, to_state: StepState) -> None:
        """Raise StateError if transition is illegal.

        CODE-009 fix: Handles all StepState values including terminal states.
        Terminal states have empty outgoing transition sets.
        """
        if from_state not in self.LEGAL_TRANSITIONS:
            raise StateError(f"Unknown from_state: {from_state}")
        if to_state not in self.LEGAL_TRANSITIONS[from_state]:
            raise StateError(f"Illegal transition: {from_state} → {to_state}")
```

### 26.2 Rules

1. Transition is legal if `to_state in LEGAL_TRANSITIONS[from_state]`
2. CODE-009 fix: Terminal states (COMPLETED, FAILED, CANCELLED, DEAD_LETTER, SKIPPED, PARTIAL) are in the dict with empty sets — no KeyError
3. Transition is atomic with side effect (DB update, checkpoint write)
4. Attempting illegal transition raises `StateError` with old_state and attempted new_state

---

---

## 27. ExecutionManifest — Frozen Execution Manifest

### 27.1 Definition

```python
@dataclass(frozen=True)
class ExecutionManifest:
    """ARCHITECTURE_AUDIT FIX 10 — Frozen execution manifest.

    S12 executes exactly this manifest. The manifest is stored in the
    execution_manifests table and is NEVER modified after creation.
    Any version change requires a new manifest and a new execution.
    """
    # ─── Identity ──────────────────────────────────────────────────────────
    execution_id: str        # Unique execution identifier
    trace_id: str            # Canonical correlation ID
    plan_hash: str           # SHA-256 hash of the plan at execution time

    # ─── Version chain ─────────────────────────────────────────────────────
    capability_version: str       # Capability definitions version
    binding_version: str          # Capability-to-adapter bindings version
    policy_version: str           # Kernel policy version
    risk_policy_version: str      # Risk policy version
    authorization_version: str    # Authorization rules version

    # ─── Runtime versions ──────────────────────────────────────────────────
    worker_runtime_version: str   # Worker/runtime version
    model_version: str            # LLM model version used for planning

    # ─── Metadata ──────────────────────────────────────────────────────────
    created_at: float         # Unix timestamp of manifest creation
```

### 27.2 Manifest Lifecycle

```
S0 → S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10 → S11 — Plan Validation
    │
    └─► S11 creates ExecutionManifest with ALL version snapshots
        │
        └─► Manifest stored in execution_manifests table (immutable)
            │
            └─► S12 reads manifest → executes against these EXACT versions
                │
                └─► Manifest NEVER modified after creation
```

**Canonical lifecycle rule**: ExecutionManifest is created at the end of S11, after plan validation confirms the plan is executable. S12 is the sole consumer. No stage before S11 creates a manifest.

### 27.3 Manifest Rules

| Rule | Description |
|------|-------------|
| S12 executes exactly this manifest | S12 cannot use a different version of anything |
| Stored in execution_manifests table | Permanent audit record of what was used |
| Never modified after creation | Immutable once stored |
| New manifest for any version change | Any version bump creates a new manifest |
| Full version capture | All capability, binding, policy, skill, artifact, worker, and model versions are frozen |

### 27.4 Validation

| Test | Purpose |
|------|---------|
| `test_execution_manifest_frozen()` | Verifies manifest is immutable after creation — attempts to modify any field raise FrozenInstanceError |
| `test_execution_manifest_all_versions()` | Verifies all version fields are captured and non-empty |
| `test_execution_manifest_new_on_version_change()` | Verifies a new manifest is generated when any version changes |

---

## 28. Outbox-Inbox Event Delivery Contract

### 28.1 OutboxEvent Definition

```python
@dataclass(frozen=True)
class OutboxEvent:
    """ARCHITECTURE_AUDIT FIX 27 — Outbox event for reliable delivery.

    Events are written to an outbox table in the same transaction as the
    state change that caused them. The dispatcher reads from the outbox and
    delivers to subscribers. Consumers receive events via their inbox.
    """
    # ─── Identity ──────────────────────────────────────────────────────────
    event_id: str             # UUID v4 — unique event identifier
    event_type: str           # e.g., "execution.started", "step.completed"
    aggregate_id: str         # ID of the aggregate (e.g., execution_id)
    aggregate_type: str       # Type of aggregate (e.g., "Execution", "Step")

    # ─── Payload ───────────────────────────────────────────────────────────
    payload: dict             # Serialized event data

    # ─── Causality ─────────────────────────────────────────────────────────
    causation_id: str | None  # Event that directly caused this event
    correlation_id: str       # Groups related events (trace_id)

    # ─── Ordering ──────────────────────────────────────────────────────────
    sequence_number: int      # Monotonically increasing per aggregate

    # ─── Delivery tracking ─────────────────────────────────────────────────
    created_at: float         # When event was created
    dispatched_at: float | None  # When event was dispatched
    dispatch_attempts: int    # Number of dispatch attempts
```

### 28.2 Dispatcher Rules

| # | Rule | Description |
|---|------|-------------|
| D1 | Atomic write | Event written to outbox in same transaction as state change — both succeed or both fail |
| D2 | At-least-once delivery | Events are dispatched until acknowledged; duplicates handled by consumer |
| D3 | Sequential per aggregate | Events for the same aggregate_id are dispatched in sequence_number order |
| D4 | Retry with backoff | Failed dispatches retry with exponential backoff, max 5 attempts |
| D5 | Dead letter after exhaustion | Events that exhaust all attempts go to event_dead_letter table for manual review |

### 28.3 Consumer Rules

| # | Rule | Description |
|---|------|-------------|
| C1 | Idempotent processing | Consumers must handle duplicate events (check event_id) |
| C2 | Out-of-order handling | Consumers may buffer events; process in sequence_number order per aggregate |
| C3 | Acknowledge after processing | Consumer sends ACK only after successfully processing the event |
| C4 | Late event detection | Events arriving after the consumer's current sequence are flagged for replay |

### 28.4 Validation

| Test | Purpose |
|------|---------|
| `test_outbox_inbox_delivery()` | End-to-end test: event written to outbox, dispatched, received by consumer, processed idempotently |

---

## 29. Event Ordering and Causality

### 29.1 EventIdentity Definition

```python
@dataclass(frozen=True)
class EventIdentity:
    """ARCHITECTURE_AUDIT FIX 28 — Event identity with ordering metadata.

    Every event in the system carries this identity to support causal
    ordering, deduplication, and late-arrival detection.
    """
    # ─── Identity ──────────────────���───────────────────────────────────────
    event_id: str             # UUID v4 — globally unique
    event_type: str           # Event type name (e.g., "execution.started")

    # ─── Ordering ──────────────────────────────────────────────────────────
    sequence_number: int      # Monotonically increasing within ordering_scope
    parent_event_id: str | None  # Immediate parent in causal chain
    causation_id: str | None  # Event that caused this event

    # ─── Grouping ──────────────────────────────────────────────────────────
    correlation_id: str       # Groups causally related events
    ordering_scope: str       # Scope of ordering (see §29.2)
    partition_key: str        # Partition key for sharded ordering

    # ─── Timestamp ─────────────────────────────────────────────────────────
    timestamp: float          # Unix timestamp of event creation
```

### 29.2 Ordering Scopes

| Scope | Partition Key | Sequence Scope | Use Case |
|-------|--------------|----------------|----------|
| `execution` | `execution_id` | Per execution | Order events within a single execution |
| `worker` | `worker_id` | Per worker | Order events from a single worker |
| `conversation` | `conversation_id` | Per conversation | Order events within a conversation thread |
| `a2a_stream` | `stream_id` | Per A2A stream | Order events in an Agent-to-Agent stream |
| `tenant` | `tenant_id` | Per tenant | Global ordering per tenant |

### 29.3 Ordering Rules

| Rule | Description |
|------|-------------|
| No global ordering | There is no single global event sequence — ordering is scoped per partition |
| Causation ID required | Every event (except root events) must carry a causation_id |
| Late events flagged | Events arriving with sequence_number behind the consumer's current position are flagged as late |
| Duplicates detected | Events with the same event_id are detected as duplicates and discarded |
| Out-of-order held | Events arriving ahead of the expected sequence are held until missing events arrive or timeout |

### 29.4 Event Flow Diagram

```
Event A (sequence=1, execution_id=E1)
  │
  └─► Event B (causation_id=A, sequence=2)
        │
        ├─► Event C (causation_id=B, sequence=3) ──► Normal path
        │
        └─► Event D (causation_id=B, sequence=4) ──► Normal path
              │
              └─► Late: Event E (causation_id=C, sequence=3, arrives late)
                    └─► Flagged as late, replayed if within tolerance window
```

### 29.5 Validation

| Test | Purpose |
|------|---------|
| `test_event_ordering()` | Verifies events are ordered correctly within scope, late events are flagged, duplicates are detected, and out-of-order events are held |

---

## 30. Configuration Versioning and Rollout

### 30.1 Configuration Lifecycle

```
Configuration Version N is active
    │
    ├─► Activate Version N+1
    │     │
    │     ├─► Running executions continue on Version N
    │     │     (they already captured N in their ExecutionManifest)
    │     │
    │     └─► New executions pick up Version N+1
    │           (new ExecutionManifest captures N+1)
    │
    ├─► Rollback to Version N-1
    │     │
    │     ├─► Running executions continue on Version N (no mid-flight switch)
    │     │
    │     └─► New executions pick up Version N-1
    │           (new ExecutionManifest captures N-1)
    │
    └─► Result: An execution never silently switches configuration versions
```

### 30.2 Core Rules

| Rule | Description |
|------|-------------|
| No mid-flight switch | An execution never silently switches configuration versions mid-flight |
| New executions only | Configuration changes affect new executions only |
| Immutable manifest | Once created, the ExecutionManifest locks in the exact versions used |
| Versioned rollout | Every configuration change produces a new versioned snapshot |

### 30.3 What Must Be Versioned

| Component | Version Field | Source |
|-----------|--------------|--------|
| Worker runtime | `worker_runtime_version` | Worker config store |
| Policies | `policy_version` | Policy store |
| Risk policies | `risk_policy_version` | Risk policy store |
| Artifacts | `artifact_versions` dict | Artifact store |
| Models | `model_version` | Model registry |
| Capability versions | `capability_version` | Capability registry |
| Provider bindings | `binding_version` | Binding store |
| Authorization rules | `authorization_version` | Authorization store |

### 30.4 Rollback Procedure

1. Identify the target version to roll back to (e.g., N-1)
2. Set the active configuration pointer to N-1
3. All subsequent executions capture N-1 in their ExecutionManifest
4. Currently running executions continue on N (their manifest-locked version)
5. No manual intervention needed for running executions — they self-terminate with their manifest

### 30.5 Validation

| Test | Purpose |
|------|---------|
| `test_configuration_snapshot()` | Verifies that each execution captures a complete configuration snapshot in its ExecutionManifest, and that the snapshot matches the active configuration at creation time |

---

## 31. Outbox-Inbox Event Delivery Contract

### 31.1 OutboxRecord

```python
@dataclass(frozen=True)
class OutboxRecord:
    outbox_id: str           # UUID v4
    tenant_id: str           # RLS key
    aggregate_type: str      # "execution" | "plan" | "step" | "budget"
    aggregate_id: str        # execution_id, plan_id, step_id, or reservation_id
    event_type: str          # "created" | "updated" | "deleted" | "state_changed"
    event_data: dict         # JSON payload
    idempotency_key: str     # Duplicate detection
    delivery_status: str     # "pending" | "delivered" | "failed" | "dead_letter"
    delivery_attempts: int   # Retry count
    created_at: float
    delivered_at: float | None = None
    error: str | None = None
```

### 31.2 InboxRecord

```python
@dataclass(frozen=True)
class InboxRecord:
    inbox_id: str            # UUID v4
    tenant_id: str           # RLS key
    source_tenant_id: str    # Originating tenant (for cross-tenant events)
    outbox_id: str           # Source outbox record
    event_type: str
    event_data: dict
    processed: bool          # False = not yet processed
    idempotency_key: str     # Must match outbox idempotency_key
    received_at: float
    processed_at: float | None = None
```

### 31.3 Delivery Guarantees

| Property | Guarantee |
|----------|-----------|
| At-least-once | Outbox entries are delivered at least once |
| Idempotency | Consumer deduplicates via idempotency_key |
| Ordering | Per-aggregate ordering (same aggregate_id = same order) |
| Tenant isolation | Each outbox record carries tenant_id; consumer RLS enforced |
| Dead letter | After 5 failed delivery attempts → dead_letter status |
| Retention | Outbox entries retained for 7 days then archived |


*End of Data Contracts.*

---

## 31. WorkerIdentity — Durable Worker Identity

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §3
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class WorkerIdentity:
    """Durable worker identity. Persisted in DB. Survives restarts.

    This is WHO executes. It is NOT where, NOT what version, NOT a process.
    See WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §1 for state machine.
    """
    worker_id: str                    # UUID v4 — immutable
    tenant_id: str                    # Isolation boundary
    workspace_id: str                 # Workspace scope
    worker_class: str                 # Classification (e.g., "execution", "scheduler")
    capability_profile: frozenset[str]  # Capability IDs this worker can execute
    state: WorkerIdentityState        # Current lifecycle state
    capacity: int                     # Max concurrent executions
    current_load: int                 # Current in-flight executions
    lease_epoch: int                  # Current fencing token
    heartbeat_at: float | None        # Last heartbeat timestamp
    last_assignment_at: float | None  # Last execution assignment
    created_at: float                 # Registration timestamp
    updated_at: float                 # Last state change timestamp
```

### Invariants

1. `current_load <= capacity` at all times
2. `lease_epoch` changes on every lease renewal — stale workers cannot commit
3. `state` transitions must pass `WorkerIdentityStateValidator` (defined in WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §1)
4. `capability_profile` is set at registration and never changes

---

## 32. WorkerVersion — Worker Code Version

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §2, §4
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class WorkerVersion:
    """A specific version of a WorkerIdentity's code.

    Immutable once registered. The hash is the identity — if the hash changes,
    it is a new WorkerVersion.
    """
    version_id: str                   # UUID v4
    worker_id: str                    # Parent WorkerIdentity
    version: str                      # Semver string (e.g., "1.5.0")
    artifact_hash: str                # SHA-256 of deployed artifact
    state: WorkerVersionState         # Current rollout state
    canary_percentage: int            # 0-100, traffic percentage
    rollout_config: dict | None       # Gate thresholds, ramp schedule
    deployed_at: float | None         # When deployed to CANARY
    promoted_at: float | None         # When promoted to CURRENT
    deprecated_at: float | None       # When superseded
    drained_at: float | None          # When drain completed
    created_at: float                 # Registration timestamp
```

### Invariants

1. `artifact_hash` is immutable — a new hash creates a new WorkerVersion row
2. Exactly one version per WorkerIdentity can be `CURRENT` at any time
3. `canary_percentage` is 0 for all states except `CANARY` and `RAMPING`

---

## 33. WorkerDeployment — Runtime Instance

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §5
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class WorkerDeployment:
    """Links a WorkerIdentity to a specific runtime instance.

    Ephemeral — created when a worker process starts, removed when it stops.
    This is WHERE execution physically runs.
    """
    deployment_id: str                # UUID v4
    worker_id: str                    # Parent WorkerIdentity
    version_id: str                   # WorkerVersion this instance runs
    runtime_instance_id: str          # Unique per process (pod ID, container ID)
    host: str                         # Machine/host identifier
    port: int                         # Listening port
    capacity: int                     # Max concurrent for this instance
    current_load: int                 # Current in-flight
    health_status: str                # healthy | degraded | unhealthy
    last_heartbeat_at: float          # Last heartbeat
    started_at: float                 # When this instance started
    terminated_at: float | None       # When this instance stopped
```

### Relationship to Existing Tables

`worker_deployments` extends the `workers` table's runtime tracking. The
`workers` table holds the durable identity. `worker_deployments` holds
ephemeral runtime instances. The scheduler queries `worker_deployments` for
capacity and health, then writes leases against `workers.worker_id`.

---

## 34. Verifier — Independent Post-Execution Verifier

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §7
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class Verifier:
    """Independent post-execution verifier.

    Does not consume worker self-reports as evidence.
    Observes actual provider state via read operations.
    Built at S11, executed at S13.
    """
    verifier_id: str                 # UUID v4 — generated per verification
    step_id: str                     # Step being verified
    execution_id: str                # Parent execution
    kernel_op_id: str                # Operation that was executed
    binding_id: str                  # Binding that was used
    expected_state: dict             # Expected post-execution state (from step definition)
    observation_method: str          # How to observe (e.g., "get_resource")
    observation_params: dict         # Params for observation call
    max_attempts: int                # Max verification attempts
    attempt_delay_ms: int            # Delay between attempts
```

### Construction Rule

The Verifier is constructed at S11 (Freeze Manifest) from the step definition.
It is NOT constructed at S13 — S13 only executes the pre-built verifier.
This ensures the verifier cannot be influenced by the adapter's self-report.

---

## 35. VerificationResult — Independent Verification Outcome

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §8
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class VerificationResult:
    """Outcome of independent verification."""
    verifier_id: str                 # Links to Verifier
    step_id: str
    execution_id: str
    verdict: Literal["PASS", "FAIL", "UNKNOWN"]
    observations: list[Observation]  # Each observation attempt
    decided_at: float                # Timestamp
    decided_at_attempt: int          # Which attempt produced the verdict
    duration_ms: int                 # Total verification time


@dataclass(frozen=True)
class Observation:
    """Single observation attempt."""
    attempt: int                     # 1-based
    observed_at: float               # Timestamp
    provider_response_code: int      # HTTP status or provider-specific
    observed_state: dict | None      # Actual state observed
    matches_expected: bool | None    # Comparison result
    error: str | None                # If observation failed
```

### Verdict Rules

| Verdict | Condition | Next Step |
|---------|-----------|-----------|
| `PASS` | Observation matches expected state | Step → COMPLETED |
| `FAIL` | Observation contradicts expected state | Step → FAILED, dead-letter record (`data`, retry_mode NONE); never retried (gate §8 step 9, C29) |
| `UNKNOWN` | Observation inconclusive | Retry observation (up to max_attempts); still UNKNOWN → VERIFICATION episode (gate C19), never the provider probe |

---

## 36. AdmissionDecision — Admission Control Outcome

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §11
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class AdmissionDecision:
    """Outcome of admission control evaluation."""
    status: Literal["ACCEPT", "QUEUE", "DELAY", "REJECT", "DEGRADE"]
    reason: str | None = None         # Machine-readable reason code
    detail: str | None = None         # Human-readable explanation
    retry_after_ms: int | None = None # For QUEUE/DELAY — when to retry
    degraded_features: list[str] | None = None  # For DEGRADE
    gate_failed: str | None = None    # Which gate rejected (for REJECT)
```

### Key Rule: Admission Is Stateless

Admission checks are snapshots — they do not reserve resources.
Resource reservation (budget, lease) happens AFTER admission passes.
This means admission can be retried without cleanup.

---


---

## 38. IntentSpecification

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §39
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
from dataclasses import dataclass, field
from enum import StrEnum

class AutonomyLevel(StrEnum):
    FULLY_AUTONOMOUS = "fully_autonomous"
    SUPERVISED = "supervised"
    CONFIRM_ALL = "confirm_all"
    READ_ONLY = "read_only"

class ConstraintType(StrEnum):
    HARD = "hard"              # Cannot be violated — kernel blocks
    SOFT = "soft"              # Prefer to satisfy — Worker weighs in planning
    TEMPORAL = "temporal"      # Time-bound — expires after deadline
    SCOPED = "scoped"          # Resource-limited — budget/resource enforcement

@dataclass(frozen=True)
class Constraint:
    constraint_id: str
    type: ConstraintType
    description: str
    enforcement: str           # How the kernel enforces this

@dataclass(frozen=True)
class BudgetConstraint:
    max_units: float | None
    max_cost_usd: float | None
    currency: str = "USD"

@dataclass(frozen=True)
class TimeConstraint:
    deadline: str | None       # ISO 8601 UTC
    max_duration_seconds: int | None

@dataclass(frozen=True)
class RiskRequirement:
    max_risk: float            # 0.0-1.0
    require_human_above: float # Threshold for human approval

@dataclass(frozen=True)
class IntentSpecification:
    """Immutable specification of what the user actually wants."""

    # ─── Core ─────────────────────────────────────────────────────────
    intent_id: str              # UUID v4
    objective: str              # What the user wants (in their terms)
    normalized_intent: str      # Canonical capability name
    constraints: list[Constraint]
    acceptance_criteria: list[str]
    autonomy_level: AutonomyLevel

    # ─── Execution ──────────────────────────────────────────────────
    required_capabilities: list[str]
    risk_requirements: RiskRequirement
    budget_constraints: BudgetConstraint
    time_constraints: TimeConstraint | None

    # ─── Traceability ───────────────────────────────────────────────
    trace_id: str
    task_id: str | None
    created_at: str             # ISO 8601 UTC
    created_by: str             # user_id or worker_id
```

**Rules**:
1. IntentSpecification is frozen at S3 (Capability Discovery).
2. It is NEVER modified by any LLM output after creation.
3. Execution success is measured against `acceptance_criteria`, not just "API returned success."
4. `constraints` with `type=HARD` are enforced by the kernel — Workers cannot violate them.

---

## 39. ExecutionLedgerEvent

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §40
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
class LedgerEventType(StrEnum):
    """Every event type in the execution ledger."""
    REQUEST_RECEIVED = "RequestReceived"
    INTENT_CREATED = "IntentCreated"
    CAPABILITY_RESOLVED = "CapabilityResolved"
    BINDING_FROZEN = "BindingFrozen"
    PLAN_CREATED = "PlanCreated"
    CONFIRMATION_GRANTED = "ConfirmationGranted"
    MANIFEST_FROZEN = "ManifestFrozen"
    EXECUTION_STARTED = "ExecutionStarted"
    STEP_STARTED = "StepStarted"
    PROVIDER_CALLED = "ProviderCalled"
    PROVIDER_RETURNED = "ProviderReturned"
    VERIFICATION_STARTED = "VerificationStarted"
    VERIFICATION_COMPLETED = "VerificationCompleted"
    EXECUTION_COMPLETED = "ExecutionCompleted"
    OUTCOME_DELIVERED = "OutcomeDelivered"
    WORKER_WAITING = "WorkerWaiting"

@dataclass(frozen=True)
class LedgerEvent:
    """Append-only execution event. Never updated, never deleted."""

    event_id: str              # UUID v4
    event_type: LedgerEventType
    execution_id: str | None   # NULL for pre-execution events
    trace_id: str              # Always present
    tenant_id: str             # Always present — RLS enforced
    actor_id: str              # Who/what triggered this event
    actor_type: str            # "user", "worker", "system"
    payload: dict              # Event-specific data
    evidence_ref: str | None   # Reference to evidence blob
    created_at: str            # ISO 8601 UTC — server-authoritative
```

**Rules**:
1. Ledger events are APPEND ONLY.
2. Every significant transition MUST produce a LedgerEvent.
3. Given a `trace_id`, all events for that execution can be retrieved in order.
4. The ledger is the forensic truth — it does not depend on application logs.

---

## 40. AcceptanceCriteria

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §44
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
class ConditionType(StrEnum):
    RESOURCE_EXISTS = "resource_exists"
    RESOURCE_MATCHES = "resource_matches"
    SIDE_EFFECT_PRESENT = "side_effect_present"
    STATE_TRANSITION = "state_transition"
    COUNT_THRESHOLD = "count_threshold"
    CUSTOM = "custom"

@dataclass(frozen=True)
class Condition:
    condition_id: str
    type: ConditionType
    description: str
    target_resource: str | None  # What to verify
    expected_state: dict         # Expected values
    verification_method: str     # provider_state, semantic, human

@dataclass(frozen=True)
class AcceptanceCriteria:
    """Formal definition of what 'success' means."""

    criteria_id: str
    intent_id: str               # Links to IntentSpecification
    conditions: list[Condition]
    verification_method: str     # Which verification layer(s)
    verification_timeout_seconds: int
    max_verification_attempts: int
```

**Rules**:
1. "API returned 200" is NOT sufficient for W/D/IRREVERSIBLE mutations.
2. The kernel must independently verify each condition against the provider's actual state.
3. For IRREVERSIBLE mutations, at least one condition must be of type `provider_state`.

---

## 41. AutonomyBounds

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §45
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class AutonomyBounds:
    """Hard limits for autonomous execution loops."""

    bounds_id: str
    max_iterations: int           # Default: 5
    max_budget: float             # Default: 10.0 units
    max_duration_seconds: int     # Default: 300
    max_tool_calls: int           # Default: 20
    max_risk: float               # Default: 0.5
    termination_criteria: list[str]
    escalation_criteria: list[str]
```

**Rules**:
1. Every Worker execution has AutonomyBounds frozen in the ExecutionManifest.
2. If any bound is reached, the loop terminates immediately.
3. If escalation_criteria are met, a human is notified before termination.
4. AutonomyBounds cannot be widened by LLM output.

---

## 42. RuntimeRoutingDecision

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §46
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class RuntimeRoutingDecision:
    """Determines which runtime and model to use."""

    decision_id: str
    trace_id: str
    task_complexity: str          # simple, moderate, complex
    risk: float
    latency_requirement_ms: int | None
    budget_available: float
    selected_runtime: str         # Runtime adapter class name
    selected_model: str           # Model identifier
    routing_factors: dict         # Decision factors for audit
    decided_at: str               # ISO 8601 UTC
```

**Rules**:
1. Routing is determined at S7 (Path Routing) based on IntentSpecification.
2. Routing is frozen in ExecutionManifest — no mid-execution switching.
3. Simple deterministic tasks must not consume expensive reasoning models.

---

## 43. ReplayContext

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §47
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
class ReplayMode(StrEnum):
    DRY_RUN = "dry_run"           # No side effects
    ISOLATED = "isolated"         # Isolated environment
    PRODUCTION = "production"     # With idempotency protection

@dataclass(frozen=True)
class ReplayContext:
    """Context for replaying an execution."""

    replay_id: str                # UUID v4
    original_execution_id: str
    replay_reason: str
    mode: ReplayMode
    isolation_scope: str          # test, staging, production
    requested_by: str
    created_at: str               # ISO 8601 UTC
```

**Rules**:
1. Replay uses the exact ExecutionManifest from the original execution.
2. Idempotency keys are preserved — provider adapters honor them.
3. External side effects are NOT blindly repeated — acceptance criteria are verified first.
4. Replay evidence is compared to original evidence for correctness.

---

## 44. CorrelationRule

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §41
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
class AggregationType(StrEnum):
    SUM = "sum"
    COUNT = "count"
    LATEST = "latest"
    FIRST = "first"
    CUSTOM = "custom"

@dataclass(frozen=True)
class CorrelationRule:
    """Defines how events are correlated and aggregated."""

    rule_id: str
    name: str
    tenant_id: str
    event_types: list[str]
    window_seconds: int
    group_by: list[str]
    aggregation: AggregationType
    filter_expression: str | None  # JMESPath
    min_events: int                # Minimum events before emitting
    max_events: int                # Maximum in one aggregate
    is_active: bool
    created_at: str
```

**Rules**:
1. Correlation is deterministic: same input events in same order → same output.
2. This enables replay correctness.
3. Aggregation happens BEFORE S0 entry — the Worker never sees individual raw events.

---

## 45. ProcessorDefinition

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §42
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
class ProcessorType(StrEnum):
    PYTHON = "python"
    SQL = "sql"
    WASM = "wasm"
    VISUAL = "visual"
    CUSTOM = "custom"

@dataclass(frozen=True)
class ProcessorDefinition:
    """Definition of a sandboxed processor."""

    processor_id: str
    name: str
    processor_type: ProcessorType
    input_schema: dict           # JSON Schema
    output_schema: dict          # JSON Schema
    code: str | None             # Python/WASM source
    allowed_modules: list[str]   # Python module allowlist
    resource_limits: dict        # CPU, memory, time, size
    timeout_seconds: int
    tenant_id: str
    version: str                 # Semver
    created_at: str
```

**Rules**:
1. Processors run as `system` actor_type with restricted permissions.
2. Processors cannot access other tenants' data, make network calls (unless explicitly allowed), or persist state between executions.
3. Processor code is versioned and frozen per execution.
4. WASM processors are preferred when available (stronger isolation).

---

## 46. EventEnvelope

**Owner**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — §4
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class EventEnvelope:
    """Immutable wrapper for externally-triggered events."""

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

**Rules**:
1. `tenant_id` and `workspace_id` come from the Event Gateway authentication context.
2. They are NEVER extracted from the event payload.
3. EventEnvelope is immutable after creation.

---

## 47. WorkerSubscription

**Owner**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — §9
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class WorkerSubscription:
    """Worker's declaration of event interest."""

    subscription_id: str             # UUID v4
    worker_id: str                   # Which worker
    tenant_id: str                   # Isolation boundary
    workspace_id: str                # Workspace context
    event_types: list[str]           # ["workflow.completed", "contact.created"]
    source_systems: list[str]        # ["ghl", "notion", "google"]
    filter_expression: str | None    # JMESPath filter
    priority: int                    # Lower = higher priority
    max_concurrent: int              # Max concurrent executions
    is_active: bool
    matched_count: int
    last_matched_at: str | None
    created_at: str
    created_by: str
```

**Rules**:
1. Subscriptions are tenant/workspace-scoped.
2. Subscriptions are durable — they survive worker restarts.
3. Subscriptions are versioned — changes create new versions, not mutations.
4. The Event Gateway uses subscriptions to route events to Workers.

---

## 48. ConfigurationVersion

**Owner**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §37a Principle 6
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class ConfigurationVersion:
    """All configuration versions frozen at execution start."""

    execution_id: str
    capability_version: str
    binding_version: str
    policy_version: str
    risk_policy_version: str
    adapter_version: str
    kernel_version: str
    runtime_version: str
    model_version: str
    processor_version: str | None
    skill_versions: dict[str, str]  # skill_name → version
    frozen_at: str                   # S11 timestamp
```

**Rules**:
1. ConfigurationVersion is part of ExecutionManifest.
2. An execution ALWAYS uses the versions frozen at S11.
3. Configuration changes affect new executions only (I-017).
4. No mid-execution configuration drift is possible.

---

## 49. LayerResult — Single Verification Layer Outcome

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §8
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class LayerResult:
    """Result of a single verification layer within progressive verification."""

    verification_id: str
    execution_id: str
    layer: VerificationLayer
    status: VerificationStatus
    evidence: dict
    error: str | None
    duration_ms: int
    attempted_at: str
```

**Rules**:
1. S13 runs all required verification layers (determined by mutation type and risk).
2. All layers must PASS for the execution to be marked COMPLETED.
3. Any layer that returns INCONCLUSIVE triggers additional attempts.
4. FAILED at any layer routes to DEAD_LETTER with full evidence.

## 37. ExecutionOwnership — Execution Ownership Tracking

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §14
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

```python
@dataclass(frozen=True)
class ExecutionOwnership:
    """Tracks who owns an execution at every point in its lifecycle.

    Answers: Who is executing this? Where is its state? Can they proceed?
    """
    execution_id: str                 # UUID v4
    worker_id: str | None             # Current owner (None = not assigned)
    worker_version: str | None        # Version running this execution
    runtime_instance_id: str | None   # Specific process/container
    lease_id: str | None              # Current lease
    fencing_token: int | None         # Lease epoch — monotonic, never decreases
    checkpoint_sequence: int          # Last checkpoint number
    state_location: str | None        # Host where checkpoints reside
    owner_acquired_at: float | None   # When current owner acquired
    lease_expires_at: float | None    # When lease expires
```

### Ownership Transfer Rule

Fencing tokens are strictly monotonically increasing. A stale worker
with an old token cannot commit any state change. The `worker_leases.fence_token`
table is the authoritative source for the current token.
