# Mutation Safety, Confirmation & Idempotency

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §9 Mutation Control, §10 Execution Safety, §12 Reliability, §13 Worker Lifecycle. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §9 ExecutionResult, §9 ExecutionStatus, §9 ExecutionOutcome, §22 RetryDecision, §22 RetryPolicy, §19 StepState, §17 IdempotencyKey. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S8, S9, S10, S11, S12, S13, S14. [STATE_TRANSITIONS.md](STATE_TRANSITIONS.md) — Step States, BudgetReservation States. [SECURITY.md](SECURITY.md) — §10 Guardrail Precedence Level 7. [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §6-9 (independent verification for mutations).
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

**Purpose**: The complete rules for safe execution of write/delete operations. This is the most safety-critical part of the system. Every mutation must be traceable, reversible (where possible), and user-confirmed (for dangerous operations).

---

## Table of Contents

1. [Mutation Taxonomy](#1-mutation-taxonomy)
2. [Mutation Safety Rules](#2-mutation-safety-rules)
3. [Retry Decision Matrix](#3-retry-decision-matrix)
4. [Confirmation Flow](#4-confirmation-flow)
5. [Idempotency System](#5-idempotency-system)
6. [Inverse Operations](#6-inverse-operations)
7. [Checkpoint & Resume](#7-checkpoint--resume)
8. [Dead Letter Handling](#8-dead-letter-handling)
9. [Safety Contracts](#9-safety-contracts)

---

## 1. Mutation Taxonomy

Every operation is classified by its mutation type. This classification drives retry behavior, confirmation requirements, and safety checks.

### The Four Mutation Levels

```
R (READ)          W (WRITE)          D (DELETE)    IRREVERSIBLE
Safe to retry     Retry with care    Retry w/ care NEVER retry
No confirmation   No confirmation   ALWAYS confirm ALWAYS confirm
No inverse        Has inverse        Has inverse    No inverse
Cost: 1 unit      Cost: 2-3 units   Cost: 3-5      Cost: 5+ units
```

### Mutation Level Details

| Level | Meaning | Examples | Retry | Confirm | Inverse |
|-------|---------|----------|-------|---------|---------|
| `R` | Read-only — no side effects | search, list, get, query | Yes | No | N/A |
| `W` | Write — reversible change | create, update, append, patch | Yes | No | Yes |
| `D` | Delete — reversible removal | delete, archive, remove | Idempotent only | Yes | Yes |
| `IRREVERSIBLE` | Permanent action | send_email, trigger_workflow, webhook | Never | Always | No |

### Cost Model

```python
MUTATION_COSTS = {
    # Read operations
    "R": {
        "search": 1, "list": 1, "get": 1, "query": 1,
    },
    # Write operations
    "W": {
        "create": 3, "update": 2, "patch": 2, "append": 2, "upsert": 3,
    },
    # Delete operations
    "D": {
        "delete": 5, "archive": 3, "remove": 4, "soft_delete": 3,
    },
    # Irreversible operations
    "IRREVERSIBLE": {
        "send_email": 3, "trigger_workflow": 5, "webhook": 3, "bulk_delete": 10,
    },
}
```

---

## 2. Mutation Safety Rules

### The Six Rules

Every mutation operation MUST satisfy these rules in order:

```
Rule 1: Is the mutation implemented? (registry check)
    NO → STOP: "Capability not yet implemented"
Rule 2: Is the mutation enabled? (registry check)
    NO → STOP: "Capability is currently disabled"
Rule 3: Is the mutation retired? (registry check)
    YES → STOP: "Capability retired. Use: {replacement}"
Rule 4: Was the user authorized at S8? (cached auth check)
    NO → STOP: "Authorization was denied at safety gate"
Rule 5: Does the user have budget? (budget check — atomic reserve)
    NO → STOP: "Insufficient budget"
Rule 6: Is the user confirmed? (confirmation check, for D/IRREVERSIBLE)
    NO → PAUSE: "Please confirm this action"
ALL PASS → PROCEED with execution
```

**D-AUTH1**: Rule 4 does NOT re-evaluate authorization. It checks the cached `auth_result_id`
from S8 Safety Gate. S8 is the sole authorization checkpoint. This eliminates duplicate
authorization work and prevents inconsistent results from mid-pipeline permission changes.

### Implementation

```python
class MutationSafetyGate:
    def check(self, step: Step, context: ExecutionContext,
              registry: CapabilityRegistry) -> SafetyResult:
        # Rule 1: Implemented?
        cap = registry.get(step.kernel_op_id)
        if cap is None or not cap.is_implemented:
            return SafetyResult(False, "not_implemented", "This capability is not yet implemented")

        # Rule 2: Enabled?
        if not cap.is_enabled:
            return SafetyResult(False, "disabled", "This capability is currently disabled")

        # Rule 3: Retired?
        if cap.status == "retired":
            return SafetyResult(False, "retired",
                f"This capability has been retired. Use: {cap.replacement}")

        # Rule 4: S8 authorization cached result (D-AUTH1)
        if not context.auth_passed:
            return SafetyResult(False, "unauthorized",
                "Authorization was denied at safety gate (S8)")

        # Rule 5: Budget?
        budget_check = budget.check(user.user_id, step.est_cost)
        if not budget_check.allowed:
            return SafetyResult(False, "budget", budget_check.reason)

        # Rule 6: Confirmation?
        if step.mutation in ("D", "IRREVERSIBLE"):
            if not step.requires_confirmation:
                step = dataclasses.replace(step, requires_confirmation=True)
            if not user.has_confirmed(step.id):
                return SafetyResult(False, "needs_confirmation",
                    f"This {step.mutation} operation requires your confirmation")

        return SafetyResult(True)
```

---

## 3. Retry Decision Matrix

**Ownership**: MUTATION_SAFETY defines the CEILING (whether retry is semantically allowed based on mutation type). RELIABILITY defines the mechanics (backoff, storm guard, circuit breaker). DATA_CONTRACTS §22 RetryDecision + `max_attempts` field carry the definitive values. The effective max is `min(step_policy.max_attempts, mutation_safety_ceiling, reliability_ceiling, provider_limit)`.

### Retry Rules by Mutation Type

| Mutation | Retry? | Max Attempts | Condition | Backoff |
|----------|--------|-------------|-----------|---------|
| R | YES | 3 | Any retryable error | Exponential |
| W (safe) | YES | 2 | retry_safe=true | Exponential |
| W (idempotent) | Conditional | 2 | retry_safe=idempotent AND params identical | Exponential |
| D (idempotent) | YES | 2 | Only idempotent errors | Fixed |
| D (non-idempotent) | NEVER | 1 | Never | N/A |
| IRREVERSIBLE | NEVER | 1 | Never | N/A |

### Retryable Errors

| HTTP Status | Error Type | Retry? | Reason |
|-------------|-----------|--------|--------|
| 429 | Rate Limit | YES | Back off and retry |
| 500 | Server Error | YES | Transient server issue |
| 502 | Bad Gateway | YES | Transient proxy issue |
| 503 | Service Unavailable | YES | Transient overload |
| 504 | Gateway Timeout | YES | Transient timeout |
| 401 | Unauthorized | NO | Credentials invalid |
| 403 | Forbidden | NO | Permission denied |
| 404 | Not Found | NO | Resource doesn't exist |
| 422 | Validation Error | NO | Input is wrong |
| N/A | CircuitBreakerOpen | NO | Provider down |
| N/A | BudgetExceeded | NO | Budget issue |

### Retry Implementation

```python
class RetryPolicy:
    def should_retry(self, step: Step, error: Exception, attempt: int) -> bool:
        # Rule 1: NEVER retry IRREVERSIBLE mutations
        if step.mutation == "IRREVERSIBLE":
            return False

        # Rule 2: Only retry if binding says it's safe
        if step.retry_safety == "never":
            return False

        # Rule 3: Only retry retryable errors
        if not self._is_retryable(error):
            return False

        # Rule 4: Within max attempts
        if attempt >= step.retry_policy.get("max_attempts", 3):
            return False

        # Rule 5: For D mutations, verify object still exists before retry
        if step.mutation == "D":
            if not self._verify_object_exists(step):
                return False

        return True
```

---

## 4. Confirmation Flow

### When Confirmation is Required

| Condition | Requires Confirmation |
|-----------|----------------------|
| Any IRREVERSIBLE mutation | YES |
| Any D mutation with cost > 5 | YES |
| Total cost > 20 | YES |
| Total risk > 0.7 | YES |
| Cross-provider (3+ providers) | YES |

CRIT-010 fix: Confirmation check moved from S8 to S11. S8 checks authorization + budget only.
S10 creates the token and waits for user YES. S11 consumes the token and verifies.

```
S9: Plan Created
    │
    ▼
Contains D/IRREVERSIBLE or high-risk?
    │
    ├── NO ──→ S11: Plan Validation (skip confirmation)
    │
    └── YES ──→ S10: Generate confirmation token
                    │
                    ▼
                Store token + plan_hash (5 min TTL)
                    │
                    ▼
                Return Envelope(status="confirm")
                    │
                    ▼
                ┌─────────────────────┐
                │   Wait for user     │
                │   (YES / NO)        │
                └─────────────────────┘
                    │
         ┌────────┴────────┐
         │                 │
         ▼                 ▼
    User: YES         User: NO
         │                 │
         ▼                 ▼
    CRIT-012: Re-run    Mark rejected
    S8 auth + budget    │
    checks (stale       ▼
    permissions?)   Return error
         │         ("Cancelled")
         ▼
    Consume token
    (atomic)
    Verify plan_hash
    matches
         │
         ▼
    S11: Validate
    Plan + Confirmation
         │
         ▼
    S12: Execute
```

### Confirmation Rules

| Rule | Implementation |
|------|---------------|
| Single-use | Token consumed atomically on first use |
| Time-limited | Expires after 5 minutes (300 seconds) |
| User-bound | Token tied to user_id + conversation_id + plan_hash |
| Specific | Message lists exact operations |
| Re-verify | S8 auth + budget re-checked after YES (stale permissions) |

---

## 5. Idempotency System

### Purpose

Prevent duplicate mutations when the same request is submitted multiple times (user retry, network retry, double-click).

### Idempotency Key Computation

**Canonical rule**: `request_id` (generated at S0) is the canonical idempotency key for duplicate detection. Deterministic SHA-256 hashing is not used for request-level deduplication.

```python
def compute_provider_call_id(context: ExecutionContext, attempt: int) -> str:
    """Compute provider-call idempotency key (per attempt)."""
    return f"{context.request_id}:{attempt}"
```

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

### Idempotency Rules

| Mutation | Idempotency Key Required |
|----------|--------------------------|
| R | No |
| W | Yes |
| D | Yes (critical) |
| IRREVERSIBLE | Yes (critical) |

### Flow

```
Before executing a step:
    1. Compute idempotency key
    2. Check ledger:
       - Key exists, not expired → return cached result
       - Key exists, expired → execute fresh, update record
       - Key doesn't exist → execute, store result with key
    3. TTL: 24 hours
    4. Cleanup: periodic deletion of expired keys
```

---

## 6. Inverse Operations

### Purpose

Enable rollback of completed W/D operations when a plan fails mid-execution.

### Inverse Verification (CRITICAL — from forensic audit)

**The inverse MUST verify the original operation executed before running the compensating action.**

```python
async def rollback(self, completed_steps: list[Step]) -> None:
    """Rollback completed steps in reverse order."""
    for step in reversed(completed_steps):
        if step.inverse and step.mutation in ("W", "D"):
            # CRITICAL: Verify the original operation actually executed
            provider_state = await self._verify_operation_state(step, binding)
            if provider_state == "EXECUTED":
                try:
                    await self._execute_inverse(step)
                except Exception:
                    pass  # Best effort — log and continue
            elif provider_state == "UNKNOWN":
                # Never executed or UNKNOWN — escalate to human
                # BUDGET-001: Include reservation_id for budget tracking
                self._escalate_to_dead_letter(step, "Cannot verify operation state for rollback")
            else:
                # NOT_EXECUTED — skip inverse
                logger.info(f"Skipped inverse for {step.id} — operation was never executed")
```

**Cautions**:
- **NEVER run inverse without verifying the original executed first**
- If provider state is UNKNOWN → dead letter, human escalation
- If provider state is NOT_EXECUTED → skip inverse (nothing to undo)
- Rollback failures are logged but don't block error response
- Rollback runs in reverse order (last created, first deleted)

### Inverse Kernel Mapping

Every W/D kernel operation MUST have an inverse defined:

| Kernel Operation | Inverse | Notes |
|-----------------|---------|-------|
| `ghl.contact_create` | `ghl.contact_delete` | Delete the created contact |
| `ghl.contact_update` | `ghl.contact_update` (restore) | Restore previous values |
| `notion.page_create` | `notion.page_delete` | Archive the created page |
| `google.calendar.event_create` | `google.calendar.event_delete` | Cancel the event |
| `airtable.record_create` | `airtable.record_delete` | Delete the created record |

### Rules

1. Every W/D kernel MUST have an inverse defined
2. IRREVERSIBLE operations have NO inverse (hence the name)
3. Rollback failures are logged but don't block error response
4. Rollback runs in reverse order (last created, first deleted)
5. **NEVER run inverse without verifying original operation state first**

---

## 7. Checkpoint & Resume

### Purpose

Save execution progress so that if the system crashes, it can resume from where it left off instead of starting over.

### Checkpoint Structure

```python
@dataclass(frozen=True)
class Checkpoint:
    execution_id: str
    plan_id: str
    completed_steps: list[str]       # Step IDs that completed
    failed_steps: list[str]          # Step IDs that failed
    pending_steps: list[str]         # Step IDs not yet started
    current_step: str | None         # Currently executing step
    context_snapshot: dict           # ExecutionContext snapshot
    budget_remaining: int
    created_at: float
```

### Checkpoint Write Pattern

```python
def write_checkpoint(checkpoint: Checkpoint) -> None:
    """Atomic checkpoint write — crash-safe."""
    tmp_path = f"{checkpoint_path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(checkpoint.to_dict(), f)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp_path, checkpoint_path)  # Atomic on most filesystems
```

### Resume Flow

```
On system start:
    1. Check for existing checkpoint (max 24h TTL)
    2. If found:
       a. Load execution state from DB (source of truth, not checkpoint file)
       b. Probe the in-flight step first (Bug #7 fix):
          - current_step (if RUNNING/UNKNOWN) → probe provider BEFORE anything else
          - RUNNING/PENDING_PROBE/UNKNOWN steps are in-flight, not pending
       c. For each step in checkpoint.pending_steps:
          - If step.state == PENDING: execute normally
          - If step.state == RUNNING: CRIT-008 — mark UNKNOWN, probe provider
            ├─ Probe EXECUTED → mark COMPLETED, commit budget
            ├─ Probe NOT_EXECUTED → mark PENDING, re-execute
            └─ Probe inconclusive → mark DEAD_LETTER, manual review
       d. For each step in checkpoint.failed_steps:
          - Check if already dead-lettered (idempotency)
          - If not: retry or dead-letter per policy
       e. Resume from first PENDING step
    3. If not found: normal execution
```

### Rules

1. CRIT-008: In-flight steps (RUNNING) are NEVER re-executed blindly
2. CRIT-008: RUNNING steps become UNKNOWN → probe → resolve before re-execution
3. Write to `.tmp` file, then `fsync`, then `os.rename` (atomic)
4. Checkpoint after EVERY step
5. Expire checkpoints after 24 hours
6. Checkpoint includes budget state for correct resume
7. Execution state in DB is the source of truth; checkpoint is a hint

---

## 8. Dead Letter Handling

### Purpose

Handle permanent failures that cannot be retried.

### Dead Letter Record

```python
@dataclass(frozen=True)
class DeadLetter:
    id: str
    execution_id: str
    step_id: str
    kernel_op_id: str
    reservation_id: str | None = None     # BUDGET-001: link to budget reservation
    error: str
    error_type: str         # "transient" | "permanent" | "data"
    mutation_type: str      # R, W, D, IRREVERSIBLE — CRIT-007: required for retry decision
    is_idempotent: bool     # CRIT-007: required for retry decision
    retry_count: int
    max_retries: int
    next_retry_at: float | None
    context: dict
```

### Failure Classification

| Error Type | Classification | Action |
|-----------|---------------|--------|
| Network timeout | Transient | Retry with backoff |
| Rate limit (429) | Transient | Retry with backoff |
| Server error (5xx) | Transient | Retry with backoff |
| Auth error (401/403) | Permanent | Alert admin |
| Not found (404) | Permanent | Alert admin (or skip step) |
| Validation error (422) | Data | Alert admin with details |
| Circuit open | Transient | Wait for recovery |
| Budget exceeded | Permanent | Alert admin |

### Dead Letter Retry

CRIT-007 fix: Dead letter retry MUST check mutation type. IRREVERSIBLE and
non-idempotent D mutations are NEVER retried, regardless of error type.

```python
class DeadLetterRetryScheduler:
    def should_retry(self, dead_letter: DeadLetter) -> bool:
        # Never retry IRREVERSIBLE mutations
        if dead_letter.mutation_type == "IRREVERSIBLE":
            return False
        # Never retry non-idempotent D mutations
        if dead_letter.mutation_type == "D" and not dead_letter.is_idempotent:
            return False
        # MC-027 fix: Never retry non-idempotent W mutations (duplicate creates)
        if dead_letter.mutation_type == "W" and not dead_letter.is_idempotent:
            return False
        # Only retry transient errors
        if dead_letter.error_type != "transient":
            return False
        # Within max retries
        if dead_letter.retry_count >= dead_letter.max_retries:
            return False
        return True

    def get_next_retry_delay(self, dead_letter: DeadLetter) -> float:
        if not self.should_retry(dead_letter):
            return None
        delays = [5.0, 30.0, 300.0]  # 5s, 30s, 5min
        idx = min(dead_letter.retry_count, len(delays) - 1)
        return delays[idx]
```

### Cautions
- Dead letters should NEVER be silently dropped
- Transient failures should be retried with backoff
- Permanent failures should trigger alerts
- Dead letter records should include enough context for debugging

---

## 9. Safety Contracts

### Contract 1: Mutation Safety

```
Every mutation MUST pass ALL six rules before execution.
If any rule cannot make a decision → DENY (fail-closed).
```

### Contract 2: Retry Safety

```
IRREVERSIBLE mutations are NEVER retried.
D mutations are ONLY retried if retry_safety is "idempotent".
W mutations are retried only if retry_safety is "safe" or "idempotent".
R mutations are always safe to retry.
```

### Contract 3: Confirmation Safety

```
Every D mutation requires user confirmation.
Every IRREVERSIBLE mutation requires user confirmation.
Confirmation tokens are single-use and time-limited (5 minutes).
Confirmation tokens are user-bound (tied to user_id + conversation_id).
```

### Contract 4: Rollback Safety

```
Every W/D operation MUST have an inverse defined.
Rollback runs in reverse order of execution.
Rollback failures are logged but don't block error response.
IRREVERSIBLE operations have no inverse (by definition).
```

### Contract 5: Idempotency Safety

```
Every W/D/IRREVERSIBLE operation generates an idempotency key.
Keys expire after 24 hours.
Duplicate keys within TTL return cached results.
Keys are computed from immutable context fields.
```

---

*End of Mutation Safety.*
