# State Transitions

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §8 Resolution, §10 Execution Safety, §12 Reliability, §13 Worker Lifecycle, §6a Event Gateway. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §19 StepState, §9 ExecutionStatus, §9 ExecutionOutcome, §22 ReconciliationStatus, §22 RetryDecision, §20 BudgetStates, §30 EventEnvelope, §31 WorkerSubscription. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S12–S14. [MUTATION_SAFETY.md](MUTATION_SAFETY.md) — mutation safety rules, confirmation requirements. [RELIABILITY.md](RELIABILITY.md) — lease management, circuit breaker states. [DATABASE.md](DATABASE.md) — state column constraints. [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — §8 EventEnvelope states, §9 WorkerSubscription states. [ADAPTABILITY_PRINCIPLES.md](ADAPTABILITY_PRINCIPLES.md) — §3 event-sourced execution.
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY
**Purpose**: The single authoritative source for all state machines in the system. Every state transition not listed here is ILLEGAL and must be rejected.

---

## Table of Contents

1. [ExecutionRun States](#1-executionrun-states)
2. [Step States](#2-step-states)
3. [BudgetReservation States](#3-budgetreservation-states)
4. [Worker States](#4-worker-states)
5. [Lease States](#5-lease-states)
6. [Capability States](#6-capability-states)
7. [Binding States](#7-binding-states)
8. [Confirmation States](#8-confirmation-states)
9. [DeadLetter States](#9-deadletter-states)
10. [Reconciliation States](#10-reconciliation-states)
11. [CircuitBreaker States](#11-circuitbreaker-states)
12. [Cross-State Invariants](#12-cross-state-invariants)

---

## 1. ExecutionRun States

### State Definitions

| State | Meaning | Terminal? |
|-------|---------|-----------|
| `PENDING` | Execution created, not yet started | No |
| `RUNNING` | Actively executing steps | No |
| `RECONCILING` | Step(s) timed out, probing provider for actual outcome | No |
| `COMPLETED` | All steps completed successfully | Yes |
| `PARTIAL` | Some steps completed, some failed | Yes |
| `FAILED` | Unrecoverable error | Yes |
| `CANCELLED` | User or system cancelled | Yes |
| `DEAD_LETTER` | Exhausted retries, unrecoverable | Yes |

### Transition Matrix

```
Valid Transitions:
  PENDING     ──→ RUNNING      (S12 starts execution)
  PENDING     ──→ CANCELLED    (cancelled before execution starts)
  RUNNING     ──→ COMPLETED    (all steps COMPLETED)
  RUNNING     ──→ PARTIAL      (some COMPLETED, some FAILED after all steps terminal)
  RUNNING     ──→ FAILED       (unrecoverable error, no steps completed)
  RUNNING     ──→ CANCELLED    (user cancelled or budget exhausted mid-execution)
  RUNNING     ──→ DEAD_LETTER  (all steps DEAD_LETTER or STILL_UNKNOWN after max probes)
  RUNNING     ──→ RECONCILING  (one or more steps UNKNOWN, probing provider)
  RECONCILING ──→ COMPLETED   (all UNKNOWN steps resolved CONFIRMED_SUCCESS)
  RECONCILING ──→ PARTIAL     (some CONFIRMED_SUCCESS, some CONFIRMED_FAILURE)
  RECONCILING ──→ FAILED      (all CONFIRMED_FAILURE or DEAD_LETTER)
  RECONCILING ──→ DEAD_LETTER (STILL_UNKNOWN after max probes)
  RECONCILING ──→ CANCELLED   (user cancelled during reconciliation)

Illegal Transitions (MUST be rejected):
  COMPLETED   ──→ any non-terminal (terminal states are final)
  PARTIAL     ──→ any non-terminal (terminal states are final)
  FAILED      ──→ RUNNING     (must create new execution)
  CANCELLED   ──→ RUNNING     (must create new execution)
  DEAD_LETTER ──→ RUNNING     (must create new execution)
  RECONCILING ──→ RUNNING    (must resolve to terminal state first)
  Any terminal ──→ PENDING   (terminal states are final)
  PENDING     ──→ COMPLETED  (must go through RUNNING first)
  PENDING     ──→ PARTIAL    (must go through RUNNING first)
  PENDING     ──→ FAILED     (must go through RUNNING first)
  PENDING     ──→ DEAD_LETTER (must go through RUNNING first)
  PENDING     ──→ RECONCILING (must go through RUNNING first)
```

### Implementation Contract

```python
VALID_TRANSITIONS = {
    "PENDING":     {"RUNNING", "CANCELLED", "PENDING_PROBE"},
    "RUNNING":     {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "DEAD_LETTER", "RECONCILING", "PENDING_PROBE", "TIMEOUT"},
    "RECONCILING": {"COMPLETED", "PARTIAL", "FAILED", "DEAD_LETTER", "CANCELLED"},
    "COMPLETED":   set(),      # Terminal — no transitions
    "PARTIAL":     set(),      # Terminal — no transitions
    "FAILED":      set(),      # Terminal — no transitions
    "CANCELLED":   set(),      # Terminal — no transitions
    "DEAD_LETTER": set(),      # Terminal — no transitions
}

def transition_execution(current_state: str, new_state: str) -> bool:
    """Validate an execution state transition."""
    if new_state not in VALID_TRANSITIONS.get(current_state, set()):
        raise IllegalStateTransition(
            f"Cannot transition execution from {current_state} to {new_state}"
        )
    return True
```

---

## 2. Step States

**Owner**: [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §19 StepState
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

### Canonical Definition

The canonical StepState enum is defined in DATA_CONTRACTS.md §19. STATE_TRANSITIONS.md
defines only the transition matrix and cross-state invariants.

```
StepState members (DATA_CONTRACTS §19.1):
  PENDING, RUNNING, COMPLETED, PARTIAL, FAILED, CANCELLED,
  SKIPPED, TIMEOUT, UNKNOWN, PENDING_PROBE, DEAD_LETTER

Note: PROBE is NOT a StepState member. It is a transient concept:
  UNKNOWN → PENDING_PROBE → (probe executes) → COMPLETED/FAILED/DEAD_LETTER
There is no persistent PROBE state in the step state machine.
```

### Transition Matrix

```
Valid Transitions:
  PENDING       ──→ RUNNING          (step starts executing)
  PENDING       ──→ SKIPPED          (dependency failed, step not needed)
  PENDING       ──→ CANCELLED        (user cancelled before start)
  RUNNING       ──→ COMPLETED        (successful execution)
  RUNNING       ──→ PARTIAL          (partial success — some sub-operations failed)
  RUNNING       ──→ FAILED           (execution failed)
  RUNNING       ──→ CANCELLED        (user cancelled mid-execution)
  RUNNING       ──→ TIMEOUT          (exceeded time limit)
  RUNNING       ──→ PENDING_PROBE    (timeout detected, probe queued directly)
  TIMEOUT       ──→ PENDING_PROBE    (timeout, probe queued to determine outcome)
  TIMEOUT       ──→ UNKNOWN          (timeout confirmed — outcome indeterminate)
  TIMEOUT       ──→ DEAD_LETTER      (timeout, no recovery possible)
  UNKNOWN       ──→ PENDING_PROBE    (probe initiated)
  UNKNOWN       ──→ DEAD_LETTER      (max probes exhausted)
  UNKNOWN       ──→ FAILED           (terminal-state invariant timeout)
  PENDING_PROBE ──→ COMPLETED        (probe confirmed executed)
  PENDING_PROBE ──→ PENDING          (probe confirmed not started — retry)
  PENDING_PROBE ──→ FAILED           (probe error — cannot determine)
  PENDING_PROBE ──→ DEAD_LETTER      (probe inconclusive, max attempts)

Terminal states (no outgoing transitions):
  COMPLETED, FAILED, CANCELLED, SKIPPED, DEAD_LETTER

Illegal Transitions (MUST be rejected):
  COMPLETED    ──→ any non-terminal   (terminal states are final)
  FAILED       ──→ RUNNING           (must create new attempt)
  FAILED       ──→ COMPLETED         (cannot retroactively succeed)
  SKIPPED      ──→ RUNNING           (skipped is terminal)
  DEAD_LETTER  ──→ RUNNING           (must create new execution)
  UNKNOWN      ──→ COMPLETED         (must go through PENDING_PROBE first)
  UNKNOWN      ──→ FAILED            (must go through PENDING_PROBE first)
  PENDING      ──→ COMPLETED         (must go through RUNNING first)
  PENDING      ──→ FAILED            (must go through RUNNING first)
  RUNNING      ──→ PENDING           (running cannot regress)
```

### NO SILENT SUCCESS Rule

**UNKNOWN → COMPLETED is ILLEGAL.** A step in UNKNOWN state MUST complete the full probe phase:
```
UNKNOWN → PENDING_PROBE → COMPLETED   (probe confirms success)
UNKNOWN → PENDING_PROBE → FAILED      (probe confirms failure)
UNKNOWN → PENDING_PROBE → DEAD_LETTER (probe inconclusive, max attempts)
```
There is no shortcut path from UNKNOWN to any terminal state without going through PENDING_PROBE.

---

## 3. BudgetReservation States

**Owner**: [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §16.3 ReservationState
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

### State Definitions

| State | DB Value | Meaning |
|-------|----------|---------|
| `PENDING` | `pending` | Budget reservation requested, not yet committed |
| `RESERVED` | `reserved` | Budget atomically reserved (funds set aside) |
| `LOCKED` | `locked` | Budget locked for execution (between reserve and commit/release) |
| `COMMITTED` | `committed` | Budget permanently deducted (execution succeeded) |
| `RELEASED` | `released` | Budget returned to pool (execution failed or cancelled) |

### Transition Matrix

```
Valid Transitions:
  PENDING     ──→ RESERVED      (S12 atomic reserve succeeds)
  PENDING     ──→ RELEASED      (reserve failed, nothing to return)
  RESERVED    ──→ LOCKED        (step begins execution)
  RESERVED    ──→ RELEASED      (cancelled before execution)
  LOCKED      ──→ COMMITTED     (step completed successfully)
  LOCKED      ──→ RELEASED      (step failed, return budget)
  COMMITTED   ──→ (terminal)    # No further transitions
  RELEASED    ──→ (terminal)    # No further transitions

Illegal Transitions (MUST be rejected):
  COMMITTED   ──→ RELEASED      (committed is final — cannot undo)
  PENDING     ──→ COMMITTED     (must go through RESERVED → LOCKED first)
  RESERVED    ──→ COMMITTED     (must go through LOCKED first)
  LOCKED      ──→ RESERVED      (LOCKED cannot regress)
  RELEASED    ──→ any state     (released is terminal)
  COMMITTED   ──→ any state     (committed is terminal)
```

### Implementation Contract

```python
# Canonical enum (DATA_CONTRACTS §16.3):
class ReservationState(StrEnum):
    PENDING = "pending"
    RESERVED = "reserved"
    LOCKED = "locked"
    COMMITTED = "committed"
    RELEASED = "released"

VALID_BUDGET_TRANSITIONS = {
    "pending":    {"reserved", "released"},
    "reserved":   {"locked", "released"},
    "locked":     {"committed", "released"},
    "committed":  set(),   # Terminal
    "released":   set(),   # Terminal
}
```

---

## 4. Worker States (WorkerIdentity)

**Owner**: [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §1
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

### State Definitions

| State | Meaning | Accepts New Work | In-Flight Work | Lease Status |
|-------|---------|-----------------|----------------|--------------|
| `REGISTERED` | Created in DB, not yet running | No | No | None |
| `ACTIVE` | Running, healthy, accepting work | Yes | Runs | Acquired |
| `DRAINING` | Finishing in-flight, rejecting new | No | Runs to completion | Held, not renewed |
| `DRAINED` | All work complete, ready to terminate | No | None | Released |
| `TERMINATED` | Removed from pool | No | None | Released |

### Transition Matrix

```
Valid Transitions:
  REGISTERED ──→ ACTIVE       (worker process starts, leases acquired)
  REGISTERED ──→ TERMINATED   (cancelled before start)
  ACTIVE     ──→ DRAINING     (drain signal received)
  ACTIVE     ──→ TERMINATED   (force kill)
  DRAINING   ──→ DRAINED      (all in-flight reached terminal state)
  DRAINING   ──→ ACTIVE       (drain cancelled, resume)
  DRAINED    ──→ TERMINATED   (leases released, process terminating)
  DRAINED    ──→ ACTIVE       (restart before terminate)
  TERMINATED ──→ (terminal)   # No transitions

Illegal Transitions (MUST be rejected):
  TERMINATED ──→ any state    (terminal workers cannot resume)
  DRAINING   ──→ TERMINATED   (must drain first)
  ACTIVE     ──→ DRAINED      (must drain first)
  REGISTERED ──→ DRAINING     (must be ACTIVE first)
```

### Transient Sub-States (in-memory only, not persisted)

`UNHEALTHY` and `RECOVERING` are transient sub-states, not persisted in the
`workers.state` column. They exist only in the scheduler's in-memory view.
The database only sees: ACTIVE → (heartbeat gap) → ACTIVE (new lease epoch).

---

## 5. Lease States

### State Definitions

| State | Meaning |
|-------|---------|
| `pending` | Lease acquisition requested |
| `active` | Lease held and valid |
| `expired` | Lease TTL exceeded, not renewed |
| `released` | Lease voluntarily released |

### Transition Matrix

```
Valid Transitions:
  pending   ──→ active    (lease acquired)
  pending   ──→ expired   (acquisition timeout)
  active    ──→ active    (lease renewed — fence_token increments)
  active    ──→ expired   (TTL exceeded, no renewal)
  active    ──→ released  (voluntary release after work complete)
  expired   ──→ (terminal)
  released  ──→ (terminal)

Illegal Transitions (MUST be rejected):
  expired   ──→ active    (expired leases cannot be renewed — must acquire new)
  released  ──→ active    (released leases cannot be reactivated)
  expired   ──→ released  (expired is already terminal)
```

---

## 6. Capability States

### State Definitions

| State | Meaning |
|-------|---------|
| `discovered` | Capability found in registry, not yet tested |
| `LIVE_VERIFIED` | Tested against live provider, functional |
| `certified` | Live-verified + reviewed by human |
| `PRODUCTION_ENABLED` | Certified + enabled for user-facing execution |
| `disabled` | Temporarily unavailable |
| `retired` | Permanently removed, replacement available |

### Transition Matrix

```
Valid Transitions:
  discovered       ──→ LIVE_VERIFIED        (live test passes)
  discovered       ──→ disabled             (known broken)
  LIVE_VERIFIED    ──→ certified            (human review)
  LIVE_VERIFIED    ──→ discovered           (live test fails — regression)
  certified        ──→ PRODUCTION_ENABLED   (enable for execution)
  certified        ──→ LIVE_VERIFIED        (re-test needed)
  PRODUCTION_ENABLED ──→ disabled           (taken offline)
  PRODUCTION_ENABLED ──→ retired            (replaced by newer capability)
  disabled         ──→ LIVE_VERIFIED        (fixed, re-test)
  disabled         ──→ retired              (will not be fixed)
  retired          ──→ (terminal)            # No transitions

Illegal Transitions (MUST be rejected):
  retired          ──→ any state            (retired is permanent)
  PRODUCTION_ENABLED ──→ discovered         (must go through disabled first)
  certified        ──→ PRODUCTION_ENABLED   (must go through LIVE_VERIFIED)
  discovered       ──→ PRODUCTION_ENABLED   (must go through LIVE_VERIFIED → certified)
  retired          ──→ discovered           (cannot un-retire)
```

---

## 7. Binding States

### State Definitions

| State | Meaning |
|-------|---------|
| `active` | Binding is valid and can be used |
| `stale` | Underlying capability or provider changed, binding needs refresh |
| `invalid` | Binding cannot be used (expired, revoked, deleted) |

### Transition Matrix

```
Valid Transitions:
  active   ──→ stale    (capability/provider updated, binding may be invalid)
  active   ──→ invalid  (connection revoked, token expired)
  stale    ──→ active   (re-resolved against current registry)
  stale    ──→ invalid  (re-resolution fails, or source deleted)
  invalid  ──→ (terminal)  # Cannot be used; must re-resolve

Illegal Transitions (MUST be rejected):
  invalid  ──→ active   (must re-resolve to get new binding)
  invalid  ──→ stale    (invalid cannot become stale)
  stale    ──→ active without re-resolution (must re-validate against registry)
```

### Frozen Binding Invariant

Once a binding is frozen at S5 (Provider Resolution), its state is locked for the duration of the execution. A frozen binding CANNOT transition from `active` to any other state during execution. If the underlying binding becomes stale or invalid, the execution is marked `STALE_BINDING` and routed to DEAD_LETTER for operator review.

---

## 8. Confirmation States

### State Definitions

| State | Meaning |
|-------|---------|
| `pending` | Confirmation token created, awaiting user response |
| `consumed` | User confirmed (YES), token atomically consumed |
| `rejected` | User rejected (NO), token invalidated |
| `expired` | TTL exceeded, token no longer valid |

### Transition Matrix

```
Valid Transitions:
  pending   ──→ consumed    (user responds YES, atomic consume)
  pending   ──→ rejected    (user responds NO)
  pending   ──→ expired     (5-minute TTL exceeded)

Illegal Transitions (MUST be rejected):
  consumed  ──→ any state   (single-use — cannot be reused)
  rejected  ──→ consumed    (rejected cannot be reversed)
  expired   ──→ consumed    (expired cannot be consumed)
  consumed  ──→ rejected    (already consumed)
```

---

## 9. DeadLetter States

### State Definitions

| State | Meaning |
|-------|---------|
| `pending` | Dead letter created, awaiting retry or review |
| `retrying` | Dead letter retry in progress |
| `resolved` | Dead letter resolved (retry succeeded or human action taken) |
| `abandoned` | Dead letter permanently abandoned (max retries + human review) |

### Transition Matrix

```
Valid Transitions:
  pending   ──→ retrying   (retry scheduled)
  pending   ──→ resolved   (no retry needed, or human resolved)
  retrying  ──→ resolved   (retry succeeded)
  retrying  ──→ pending    (retry failed, re-schedule)
  retrying  ──→ abandoned  (max retries exceeded)
  resolved  ──→ (terminal)
  abandoned ──→ (terminal)

Illegal Transitions (MUST be rejected):
  resolved  ──→ any state  (resolved is terminal)
  abandoned ──→ any state  (abandoned is terminal)
```

---

## 10. Reconciliation States

**Owner**: [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §22 ReconciliationStatus
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

### Canonical Definition

The canonical ReconciliationStatus enum is defined in DATA_CONTRACTS.md §22.
STATE_TRANSITIONS.md defines only the transition matrix.

```
ReconciliationStatus members (DATA_CONTRACTS §22):
  NONE, PENDING_PROBE, CONFIRMED_SUCCESS, CONFIRMED_FAILURE, RECONCILING

Note: UNKNOWN is a StepState (§2), NOT a ReconciliationStatus.
  When a step enters UNKNOWN, the execution's reconciliation_status
  changes from NONE → PENDING_PROBE.
  STILL_UNKNOWN is NOT a ReconciliationStatus — it is a transient
  condition that resolves to DEAD_LETTER.
```

### Transition Matrix

```
Valid Transitions:
  NONE           ──→ PENDING_PROBE     (UNKNOWN step detected, probe queued)
  PENDING_PROBE  ──→ RECONCILING       (probe phase starts)
  RECONCILING    ──→ CONFIRMED_SUCCESS (provider confirms execution succeeded)
  RECONCILING    ──→ CONFIRMED_FAILURE (provider confirms execution failed)
  RECONCILING    ──→ PENDING_PROBE     (probe inconclusive, retry)

Terminal states (no outgoing transitions):
  CONFIRMED_SUCCESS ──→ resolves step.state to COMPLETED
  CONFIRMED_FAILURE ──→ resolves step.state to FAILED

Illegal Transitions (MUST be rejected):
  NONE           ──→ RECONCILING      (must go through PENDING_PROBE first)
  NONE           ──→ CONFIRMED_SUCCESS (must have UNKNOWN step first)
  NONE           ──→ CONFIRMED_FAILURE (must have UNKNOWN step first)
  CONFIRMED_SUCCESS ──→ any state     (terminal — resolves to COMPLETED)
  CONFIRMED_FAILURE ──→ any state     (terminal — resolves to FAILED)
```

---

## 11. CircuitBreaker States

### State Definitions

| State | Meaning |
|-------|---------|
| `CLOSED` | Normal operation — requests flow through |
| `OPEN` | Circuit tripped — requests are rejected immediately |
| `HALF_OPEN` | Testing recovery — limited requests allowed through |

### Transition Matrix

```
Valid Transitions:
  CLOSED   ──→ OPEN      (failure threshold exceeded)
  OPEN     ──→ HALF_OPEN (recovery timeout elapsed)
  HALF_OPEN ──→ CLOSED   (test request succeeds)
  HALF_OPEN ──→ OPEN     (test request fails)

Illegal Transitions (MUST be rejected):
  CLOSED   ──→ HALF_OPEN (must go through OPEN first)
  OPEN     ──→ CLOSED    (must go through HALF_OPEN first)
```

---

## 12. Cross-State Invariants

These invariants must hold across ALL state machines simultaneously:

| Invariant | Rule |
|-----------|------|
| **I-1**: Terminal execution → terminal steps | If `execution.status ∈ {COMPLETED, FAILED, CANCELLED, DEAD_LETTER}`, ALL steps must be in terminal states (`completed`, `failed`, `skipped`, `DEAD_LETTER`). No step can be in `running`, `UNKNOWN`, or `PENDING_PROBE` when execution is terminal. |
| **I-2**: RECONCILING execution → at least one UNKNOWN step | If `execution.status = RECONCILING`, at least one step must be in `UNKNOWN` or `PENDING_PROBE` state. RECONCILING cannot exist without an active reconciliation target. |
| **I-3**: Budget locked ↔ step running | A step in `running` state MUST have a corresponding `budget_reservations` row in `locked` status. A step cannot execute without locked budget. |
| **I-4**: Dead letter → execution terminal | A dead_letters row can only be created for an execution in `RUNNING` or `RECONCILING` state. Dead letters cannot be created for terminal executions. |
| **I-5**: Confirmation consumed → plan frozen | A `pending_confirmations` row can only transition to `consumed` if the associated plan has the S9-authoritative `plan_hash`, which S11 verifies before manifest creation. |
| **I-6**: Worker TERMINATED → lease expired | A worker can only transition to `TERMINATED` state after its lease expires (or is forcibly released). A worker with an active lease cannot be TERMINATED. |
| **I-7**: Frozen binding → no state change | A binding frozen at S5 cannot transition to `stale` or `invalid` during the execution. If the underlying binding changes, the execution is marked with `STALE_BINDING` and routed to dead letter. |
| **I-8**: Budget committed → step completed | A `budget_reservations` row can only transition to `committed` if the associated step is in `completed` state. Budget cannot be committed for failed or pending steps. |

---

## 13. Implementation Requirements

1. Every state transition MUST be validated against this document before execution.
2. Illegal transitions MUST raise `IllegalStateTransition` exception — they are never silently ignored.
3. State changes MUST be atomic with their side effects (e.g., transitioning step to `completed` and committing budget must be in the same transaction).
4. State machines are defined in code as `Enum` classes matching the state names in this document.
5. All state fields in the database use TEXT columns with CHECK constraints matching the valid states.
6. State transition validation is implemented in `StateTransitionValidator` (DATA_CONTRACTS §26) and must be called before every state change.

---

## 14. EventEnvelope Processing States

**Owner**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — §8
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

### State Definitions

| State | Meaning |
|-------|---------|
| `RECEIVED` | Event received at gateway, awaiting authentication |
| `AUTHENTICATED` | HMAC/JWT validated, credential resolved |
| `VALIDATED` | Schema validated, deduplication passed |
| `NORMALIZED` | Converted to EventEnvelope |
| `ROUTED` | Matched subscription(s), S0 execution(s) created |
| `FAILED` | Authentication or validation failed |
| `REJECTED` | Duplicate, replay, or policy violation |

### Transition Matrix

```
Valid Transitions:
  RECEIVED      ──→ AUTHENTICATED  (HMAC valid)
  RECEIVED      ──→ FAILED         (HMAC invalid)
  AUTHENTICATED ──→ VALIDATED      (schema valid, not duplicate)
  AUTHENTICATED ──→ FAILED         (schema invalid)
  AUTHENTICATED ──→ REJECTED       (duplicate nonce/sequence)
  VALIDATED     ──→ NORMALIZED     (converted to EventEnvelope)
  VALIDATED     ──→ REJECTED       (replay detected)
  NORMALIZED    ──→ ROUTED         (subscription matched)
  ROUTED        ──→ (terminal)     # Routing complete

Illegal Transitions (MUST be rejected):
  FAILED        ──→ any state      (terminal)
  REJECTED      ──→ any state      (terminal)
  ROUTED        ──→ RECEIVED      (cannot re-process)
```

## 15. WorkerSubscription States

**Owner**: [EVENT_GATEWAY_AND_ROUTER.md](EVENT_GATEWAY_AND_ROUTER.md) — §9
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY

### State Definitions

| State | Meaning |
|-------|---------|
| `active` | Subscription is active, receiving events |
| `paused` | Subscription paused, events queued but not processed |
| `draining` | Finishing current batch, rejecting new events |
| `disabled` | Subscription disabled, events discarded |

### Transition Matrix

```
Valid Transitions:
  active      ──→ paused        (admin pause)
  active      ──→ disabled      (admin disable)
  active      ──→ draining      (worker shutting down)
  paused      ──→ active        (admin resume)
  paused      ──→ disabled      (admin disable while paused)
  draining    ──→ active        (drain cancelled)
  draining    ──→ disabled      (drain complete, then disable)
  disabled    ──→ active        (admin re-enable)

Illegal Transitions (MUST be rejected):
  disabled    ──→ paused        (must enable before pausing)
  draining    ──→ paused        (draining cannot be paused)
```

---

## 16. Orphaned State Definitions — Migration Note

The following state values appear in legacy code or older documents but are NOT valid in the canonical model:

| Deprecated Value | Replacement | Where Found |
|-----------------|-------------|-------------|
| `TIMEOUT` (as execution state) | `RECONCILING` + UNKNOWN step | PIPELINE_STAGES §20 (legacy), now reconciled |
| `ok` / `partial` / `failed` (envelope status) | `ExecutionStatus.COMPLETED/PARTIAL/FAILED` | DATA_CONTRACTS §22 |
| `success` / `error` (step result) | `ExecutionOutcome.SUCCESS/FAILURE` | DATA_CONTRACTS §22 |
| `phantom` (capability status) | `discovered` | DATA_CONTRACTS §19, DATABASE.md |
| `pending_verification` (capability status) | `LIVE_VERIFIED` | DATA_CONTRACTS §19 |
| `ok` / `error` / `clarify` / `confirm` (Envelope.status) | `EnvelopeStatus` enum | DATA_CONTRACTS §4 |
| `probe` (step state) | `PROBE` (upper case, enum member) | DATA_CONTRACTS §19 |
| `reserved` / `committed` / `released` (budget as raw strings) | `BudgetStates` enum | DATA_CONTRACTS §20 |

Engineers implementing the system MUST use the canonical enum values defined in DATA_CONTRACTS. Any code using deprecated values must be updated during migration.
