# Reliability

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §10 Execution Safety, §12 Reliability, §13 Worker Lifecycle. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §22 RetryDecision, §22 RetryPolicy, §20 BudgetStates, §19 StepState. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S12 (5-layer guard), S13 (reconciliation), S14 (dead letter). [MUTATION_SAFETY.md](MUTATION_SAFETY.md) — retry ceilings, inverse verification. [PROVIDER_ADAPTERS.md](PROVIDER_ADAPTERS.md) — UNKNOWN propagation, error classification. [DATABASE.md](DATABASE.md) — lease, checkpoint, budget tables. [WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md](WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md) — §10-11 (admission control), §13 (state locality).
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY — inherits FINAL_ARCHITECTURE.md status
**Purpose**: The 5-layer reliability guard that wraps every execution. Ensures that external API failures don't cascade, budgets are enforced, retries are safe, and the system degrades gracefully.

---

## Table of Contents

1. [5-Layer Reliability Guard](#1-5-layer-reliability-guard)
2. [Circuit Breaker](#2-circuit-breaker)
3. [Retry Storm Guard](#3-retry-storm-guard)
4. [Budget Tracker](#4-budget-tracker)
5. [Timeout Manager](#5-timeout-manager)
6. [Bulkhead](#6-bulkhead)
7. [Health Monitor](#7-health-monitor)
8. [Reliability Guard Wrapper](#8-reliability-guard-wrapper)
9. [Execution Semantics](#execution-semantics)
10. [Backpressure and Admission Control](#backpressure-and-admission-control)

---

## Execution Semantics

The kernel provides durable **at-least-once** execution semantics.

- A step may execute more than once (retries, worker failover, lease recovery).
- Idempotency and verification provide effective duplicate protection — not a guarantee of zero duplicates, but sufficient for correct operation.
- We do not claim "exactly once" for external APIs unless the provider itself guarantees it (e.g., idempotency keys with confirmed provider support).
- All external API calls must tolerate re-execution without corrupting state.

> **Validation**: `test_at_least_once_semantics()` confirms duplicate execution does not produce corrupt state.

---

### Billing Ownership (CRITICAL — from architecture review)

**Ownership rule**: The Reliability Guard Layer 5 records API call billing. No other component records per-call billing.

| Component | Billing Responsibility |
|-----------|----------------------|
| Reliability Guard Layer 5 | **Records** API call billing (atomic with adapter call) |
| PIPELINE_STAGES S12 | Must NOT duplicate billing — guard handles it |
| PROVIDER_ADAPTERS | Must NOT record billing — adapters are execution leaves |
| DATABASE | Provides `billing_records` table for the guard to write to |

**Why this matters**: If multiple components record the same API call, costs are double-counted. If no component records it, usage is under-counted. The Reliability Guard is the single point because it wraps every adapter call atomically.

**Implementation**: Layer 5 of the 5-layer guard calls `billing.record_api_call()` AFTER the adapter returns (whether success, failure, or UNKNOWN). This is the ONLY place in the pipeline where per-call billing is recorded.

---

## Failover Policy

Failover is recovery, not redirection. A frozen binding cannot change during failover.

| Scenario | Behavior |
|----------|----------|
| Worker dies mid-step | Lease expires, new worker picks up via `worker_leases`, binding is frozen, step retries |
| Worker fails during result commit | Lease expires, result is discarded, step retries from last checkpoint |
| Frozen binding is invalidated externally | Execution marked `STALE_BINDING`, moves to DEAD_LETTER, operator review required |

**Rules**:
1. Frozen binding identity (`CapabilityResolution`) is immutable after S5. Failover does not recompute it.
2. The new worker inherits the original binding. If the binding is invalid, execution is aborted, not redirected.
3. Lease epoch is checked on every heartbeat. A stale worker cannot commit state.
4. Failover is NOT an authorization change. The original principal chain is preserved.

---

## Backpressure and Admission Control

Every execution request passes through an admission gate before reaching the 5-layer reliability guard. This prevents cascading failures under overload by rejecting or degrading work before resources are consumed.

### Admission States

| State | Meaning |
|-------|---------|
| **ACCEPT** | Execute immediately — all gates pass |
| **QUEUE** | Capacity temporarily unavailable; hold for retry |
| **DELAY** | Backpressure detected; wait before retrying |
| **REJECT** | Permanently denied — quota exceeded or system overloaded |
| **DEGRADE** | Accepted with reduced capabilities (non-critical features disabled) |

### Admission Decision Tree

```
┌─────────────────────────────────────────────────────────────────────┐
│  INCOMING EXECUTION REQUEST                                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
               ┌──────────────▼──────────────┐
               │  1. Kill switch check       │
               │     System-wide halt?        │
               └──────────────┬──────────────┘
                              │
                  ┌───────────┴────────────┐
                  │                        │
               YES │                        │ NO
                  ▼                        ▼
           ┌──────────┐          ┌────────────────┐
           │ REJECT   │          │ 2. Tenant quota │
           │ (halted) │          │    check        │
           └──────────┘          └────────┬───────┘
                                         │
                            ┌────────────┴────────────┐
                            │                         │
                         EXCEEDED                    OK
                            ▼                         ▼
                     ┌──────────┐          ┌────────────────┐
                     │ REJECT   │          │ 3. Worker       │
                     │ (quota)  │          │    capacity     │
                     └──────────┘          └────────┬───────┘
                                                      │
                                           ┌──────────┴────────────┐
                                           │                       │
                                        AT CAP                   AVAILABLE
                                           ▼                       ▼
                                    ┌──────────┐          ┌────────────────┐
                                    │ QUEUE    │          │ 4. Provider     │
                                    │ (wait)   │          │    circuit      │
                                    └──────────┘          └────────┬───────┘
                                                                   │
                                                    ┌──────────────┴────────────┐
                                                    │                           │
                                                  OPEN                         CLOSED
                                                    ▼                           ▼
                                             ┌──────────┐              ┌────────────────┐
                                             │ REJECT   │              │ 5. DB pool      │
                                             │(circuit) │              │    utilization  │
                                             └──────────┘              └────────┬───────┘
                                                                              │
                                                                   ┌──────────┴────────────┐
                                                                   │                       │
                                                                HIGH (>85%)               NORMAL
                                                                   ▼                       ▼
                                                            ┌──────────┐          ┌────────────────┐
                                                            │ QUEUE    │          │ 6. Budget       │
                                                            │ (delay)  │          │    remaining    │
                                                            └──────────┘          └────────┬───────┘
                                                                                           │
                                                                                ┌──────────┴────────────┐
                                                                                │                       │
                                                                             DEPLETED                    OK
                                                                                ▼                       ▼
                                                                         ┌──────────┐          ┌────────────────┐
                                                                         │ REJECT   │          │ 7. System       │
                                                                         │(budget)  │          │    load         │
                                                                         └──────────┘          └────────┬───────┘
                                                                                                        │
                                                                                             ┌──────────┴────────────┐
                                                                                             │                       │
                                                                                          HIGH (>90%)                NORMAL
                                                                                             ▼                       ▼
                                                                                      ┌──────────┐          ┌────────────────┐
                                                                                      │ DEGRADE  │          │ ACCEPT         │
                                                                                      │ (reduce) │          │ (execute)      │
                                                                                      └──────────┘          └────────────────┘
```

### Backpressure Signals

| Signal | Source | Threshold | Action |
|--------|--------|-----------|--------|
| `tenant_queue_depth` | Scheduler | > 100 pending | QUEUE |
| `provider_circuit_open` | CircuitBreaker | Any open | REJECT for that provider |
| `db_pool_utilization` | ConnectionPool | > 85% | QUEUE |
| `worker_capacity` | WorkerPool | At max concurrent | QUEUE |
| `budget_remaining` | BudgetTracker | < estimated cost | REJECT |
| `system_load` | HealthMonitor | CPU/memory > 90% | DEGRADE |

### Degrade Mode Rules

When system load exceeds the threshold, the system enters DEGRADE mode with these rules:

1. **Non-critical features disabled**: Analytics, non-essential notifications, and optional post-processing are suspended. Core execution path remains fully functional.
2. **Timeout reduction**: Step timeouts are reduced by 50% to free capacity faster. Failing fast is preferable to holding resources.
3. **Priority queuing**: Tenant priority is enforced — higher-priority tenants preempt lower-priority queued work.
4. **Graceful recovery**: When system load drops below 70% for 60 consecutive seconds, degrade mode is lifted and all features are restored.

### Admission Implementation

```python
class AdmissionController:
    """Distributed admission control for execution requests."""

    def __init__(self, db, config):
        self._db = db                # PostgreSQL for all state
        self._kill_switch = False
        self._system_load = 0.0

    async def admit(self, request: ExecutionRequest) -> AdmissionDecision:
        """Apply admission decision tree. Returns ACCEPT, QUEUE, DELAY, REJECT, or DEGRADE."""

        # 1. Kill switch
        if self._kill_switch:
            return AdmissionDecision(status="REJECT", reason="system_halted")

        # 2. Tenant quota
        tenant_usage = await self._db.get_tenant_usage(request.tenant_id)
        if tenant_usage.exceeded:
            return AdmissionDecision(status="REJECT", reason="tenant_quota_exceeded")

        # 3. Worker capacity
        if not await self.has_worker_capacity():
            return AdmissionDecision(status="QUEUE", reason="worker_at_capacity")

        # 4. Provider circuit
        if await self.is_circuit_open(request.provider, request.operation):
            return AdmissionDecision(status="REJECT", reason="provider_circuit_open")

        # 5. DB pool utilization
        if await self.get_db_pool_utilization() > 0.85:
            return AdmissionDecision(status="QUEUE", reason="db_pool_pressure")

        # 6. Budget
        if not await self._db.can_afford(request.tenant_id, request.estimated_cost):
            return AdmissionDecision(status="REJECT", reason="budget_exhausted")

        # 7. System load
        if self._system_load > 0.90:
            return AdmissionDecision(
                status="DEGRADE",
                reason="high_system_load",
                degraded_features=["analytics", "notifications", "post_processing"],
            )

        return AdmissionDecision(status="ACCEPT")
```

> **Validation**: `test_backpressure_admission()` confirms the full decision tree — kill switch, quota, capacity, circuit, DB pool, budget, and load — with correct state transitions and no deadlocks.

### Outbox-Inbox Contract

All cross-component messages follow an outbox-inbox pattern. No component writes directly to another component's inbox.

| Component | Writes to | Reads from |
|-----------|-----------|------------|
| Scheduler | Outbox (execution_queue) | Inbox (worker_ready, provider_status) |
| Worker | Outbox (execution_result) | Inbox (task_assignment, kill_signal) |
| Control Plane | Outbox (policy_update) | Inbox (execution_outcome, worker_heartbeat) |
| Verification Plane | Outbox (verification_result) | Inbox (execution_complete) |

**Rules**:
1. A component never calls another component's method directly. All communication is via durable outbox tables.
2. The outbox entry is written atomically with the state change it describes (same transaction).
3. The inbox is polled by the receiving component. No push notifications.
4. Message ordering is guaranteed by `sequence_number` within each inbox.
5. Duplicate messages are detected by `message_id` and silently discarded.

```python
class OutboxWriter:
    async def write(self, inbox: str, message: dict) -> None:
        async with self._db.transaction() as tx:
            await tx.execute("""
                INSERT INTO outbox (outbox_id, inbox, message_id, sequence_number, payload)
                VALUES ($1, $2, $3,
                    (SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM outbox WHERE inbox = $2),
                    $4)
            """, gen_uuid(), inbox, message["id"], json.dumps(message))
```

---

## 1. 5-Layer Reliability Guard

Every execution passes through all 5 layers. Layers wrap from outside in — Layer 1 is checked first, Layer 5 is checked last (closest to the adapter).

```
Layer 1: CircuitBreaker    ── Per-provider failure tracking (checked first)
    │
Layer 2: RetryStormGuard   ── Prevent retry storms (checked on retry)
    │
Layer 3: BudgetTracker     ── Atomic budget reserve/deduct/refund
    │
Layer 4: TimeoutManager    ── Per-step and per-plan timeouts
    │
Layer 5: Bulkhead          ── Provider isolation via semaphores (closest to adapter)
    │
    ▼
    Adapter.call()

HealthMonitor runs alongside all layers — records scores after every result.
```

### Logical Policy Order vs Resource Acquisition Order

The 5 layers have two distinct ordering concepts:

**POLICY EVALUATION ORDER** (which checks run first conceptually):
```
Circuit → Retry → Budget → Timeout → Bulkhead
```
This is the order in which policy decisions are evaluated. Circuit breaker rejects first (cheapest check), budget reserves next (requires DB), timeout wraps the call, bulkhead isolates providers.

**RESOURCE ACQUISITION ORDER** (what must be locked before proceeding):
```
Bulkhead → Circuit → Budget → Retry → Timeout
```
The implementation acquires Bulkhead FIRST (Layer 5) to reserve the connection slot before any other checks — this prevents deadlocks where a blocked Layer 1 check holds a slot that another request needs. See Section 8 for the implementation that reflects this ordering.

### How It Works

The guard is a single class (`ReliabilityGuard`, defined in Section 8) that composes five specialized components. Execution flow:

1. **Bulkhead** — acquire per-provider semaphore (resource acquisition, FIRST)
2. **CircuitBreaker** — if open, return error immediately (no adapter call)
3. **RetryStormGuard** — on retry, check if rate is within limits
4. **BudgetTracker** — reserve budget before execution, commit or release after
5. **TimeoutManager** — wrap adapter call in `asyncio.wait_for`
6. **HealthMonitor** — record success/failure after every result

> **Note**: `BudgetTracker.reserve()` returns `BudgetResult` (never raises). The guard checks `reservation.allowed` and returns `KernelResult(status="error")` if False. The "never raise" rule applies to adapters only. BudgetTracker follows the same pattern — return-value-based error handling, no exceptions.

---

## 2. Circuit Breaker

### Keying: Per-(Provider, Operation)

Circuit breakers are keyed on `(provider, operation)` pairs — e.g., `("ghl", "ghl.contact_create")`. An outage on one endpoint does NOT block healthy operations on the same provider.

```python
class CircuitBreakerRegistry:
    """Manages per-(provider, operation) circuit breakers."""

    def __init__(self):
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}

    def get(self, provider: str, operation: str) -> CircuitBreaker:
        key = (provider, operation)
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(provider, operation)
        return self._breakers[key]

    def get_provider_health(self, provider: str) -> str:
        """Aggregate health across all operations for a provider."""
        breakers = [b for (p, _), b in self._breakers.items() if p == provider]
        if not breakers:
            return "closed"
        open_count = sum(1 for b in breakers if b.state == "open")
        return "degraded" if open_count > 0 else "closed"
```

### States

```
CLOSED ──[failures >= 5]──► OPEN ──[cooldown 60s]──► HALF_OPEN
  ▲                                    │                        │
  └────────── [success >= 3] ──────────┘                        │
                                                                   ▼
                                                        CLOSED (if success)
                                                        OPEN (if failure)
```

### Implementation

```python
class CircuitBreaker:
    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT = 60  # seconds
    SUCCESS_THRESHOLD = 3

    def __init__(self, provider: str, operation: str):
        self.provider = provider
        self.operation = operation
        self.failures = 0
        self.successes = 0
        self.state = "closed"  # closed | open | half_open
        self.last_failure_time = 0
        self._half_open_in_progress = False  # Track probe request

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        elif self.state == "open":
            if time.time() - self.last_failure_time > self.RECOVERY_TIMEOUT:
                self.state = "half_open"
                self.successes = 0
                self._half_open_in_progress = True
                return True  # Allow ONE probe request
            return False
        else:  # half_open
            if not self._half_open_in_progress:
                return True  # Allow ONE probe request
            return False  # Block others until probe completes

    def record_success(self) -> None:
        if self.state == "half_open":
            self._half_open_in_progress = False
            self.successes += 1
            if self.successes >= self.SUCCESS_THRESHOLD:
                self.state = "closed"
                self.failures = 0
                logger.info(f"Circuit CLOSED for {self.provider}:{self.operation}")
        else:
            self.failures = 0

    def record_failure(self) -> None:
        self._half_open_in_progress = False
        self.failures += 1
        if self.state == "half_open":
            self.state = "open"
            self.last_failure_time = time.time()
        elif self.failures >= self.FAILURE_THRESHOLD:
            self.state = "open"
            self.last_failure_time = time.time()
            logger.warning(f"Circuit OPEN for {self.provider}:{self.operation}")
```

### Local vs Distributed State

The circuit breaker subsystem operates across two distinct reliability domains:

**LOCAL (in-process):**
- `asyncio.Semaphore` — per-provider concurrency limit (Bulkhead, Layer 5)
- Per-step timeout — `asyncio.wait_for` deadline per execution step
- Per-provider timeout — adapter-level HTTP timeout (httpx)
- Local concurrency limit — max 10 concurrent per provider

**DISTRIBUTED (shared across workers, stored in fast ephemeral store):**
- Provider circuit state — open/half_open/closed per (provider, operation)
- Rate-limit counters — per-(provider, operation) retry window tracking
- Retry budget — global retry count across all workers
- Global provider quota — rate limit shared across the cluster
- Distributed admission control — coordinated accept/reject decisions

> **Storage**: PostgreSQL for all durable state (execution records, budget reservations, audit trail, circuit breaker state). PostgreSQL with advisory locks or lightweight tables for fast ephemeral state (circuit breakers, rate counters, retry budget). Redis is NOT used as a message bus or queue authority. PostgreSQL + pg_cron is the canonical queue.

### Rules
1. One circuit breaker per (provider, operation) pair — NOT per provider
2. Circuit breaker state is checked at the admission controller (S8 precheck context) AND at execution time (S12)
3. HALF_OPEN allows exactly one probe request; requires 3 consecutive successes to return to CLOSED
4. Circuit state is logged on every transition
5. A failure on `("ghl", "ghl.contact_create")` does NOT affect `("ghl", "ghl.contact_search")`

---

## 3. Retry Storm Guard

### Purpose

Prevent retry storms when a provider goes down — 100 concurrent retry attempts would overwhelm recovery.

### Keying: Per-(Provider, Operation)

```python
class RetryStormGuard:
    """Prevents retry storms by tracking retry rates per (provider, operation)."""

    def __init__(self, db: Database):
        self._db = db
        self._retry_window = 60  # seconds
        self._max_retries_per_window = 10

    def should_retry(self, provider: str, operation: str) -> bool:
        recent_retries = self._db.execute("""
            SELECT COUNT(*) as count
            FROM retry_log
            WHERE provider = ? AND operation = ? AND timestamp > ?
        """, (provider, operation, time.time() - self._retry_window)).fetchone()

        # Database must use row_factory=sqlite3.Row for dict-style access
        retry_count = recent_retries["count"] if recent_retries else 0
        return retry_count < self._max_retries_per_window
```

### Mutation-Aware Retry Policy

| Mutation Type | Max Attempts | Backoff | Retry Conditions |
|---------------|-------------|---------|-----------------|
| R (Read) | 3 | Exponential with jitter | Always retryable on transient errors |
| W (Write) | 2 | Exponential with jitter | Only if operation is `retry_safe` or idempotent |
| D (Delete) | 2 | Exponential with jitter | Only if operation is idempotent AND object still exists |
| IRREVERSIBLE | 1 (no retry) | N/A | Never retried under any circumstances |

```python
def get_max_attempts(mutation: str, retry_safety: str, is_idempotent: bool) -> int:
    """Determine max retry attempts based on mutation type."""
    if mutation == "IRREVERSIBLE":
        return 1  # Never retry
    elif mutation == "R":
        return 3  # Safe to retry reads
    elif mutation == "W":
        return 2 if (retry_safety == "safe" or is_idempotent) else 1
    elif mutation == "D":
        return 2 if is_idempotent else 1
    return 1

def calculate_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with jitter: min(cap, base * 2^attempt) + random jitter."""
    import random
    delay = min(cap, base * (2 ** (attempt - 1)))
    jitter = random.uniform(0, delay * 0.1)  # 10% jitter
    return delay + jitter
```

### Rules
1. Track retries per (provider, operation) in a rolling 60-second window
2. Max 10 retries per (provider, operation) per window
3. If retry rate exceeds threshold, block further retries and log
4. IRREVERSIBLE mutations never retry — not even once
5. W and D mutations only retry if explicitly marked retry_safe/idempotent
6. All retries use exponential backoff with jitter

---

## 4. Budget Tracker

### Canonical Model

See `DATA_CONTRACTS.md §16` for the full canonical definition:
- `BudgetResult` — frozen dataclass (allowed, reason, reservation)
- `BudgetReservation` — frozen dataclass (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status, timestamps)
- `ReservationState` — StrEnum (reserved, locked, committed, released)
- `BudgetLockSweeper` — auto-releases locks older than 24h

**Key rule**: Budget is per-tenant, not per-user. `budgets.budget_pool` is the tenant's shared pool. `user_id` in reservations is for attribution only.

### Atomic DB Operations

Budget operations use atomic SQL row-level operations to prevent race conditions during concurrent executions:

```python
class BudgetTracker:
    """Atomic budget enforcement via DB-level operations.

    D-BUD1/D-BUD2: preflight_check and reserve are merged into a single atomic
    operation. There is no separate preflight step — reserve() is the only budget
    gate, and it atomically checks-and-deducts in one SQL statement.

    BUDGET-001 fix: All methods accept full BudgetReservation context with
    tenant_id, execution_id, and step_id for per-step tracking and recovery.
    """

    def __init__(self, db: Database):
        self._db = db

    def reserve(self, tenant_id: str, user_id: str,
                execution_id: str, step_id: str, cost: int) -> BudgetResult:
        """Atomically reserve budget. This is the ONLY budget gate.

        Creates a BudgetReservation row. Deducts from tenant's budget_pool.
        Returns BudgetResult (never raises) — consistent with D-CAP2.

        - If budget_pool >= cost: deduct, insert reservation, return BudgetResult(allowed=True)
        - If budget_pool < cost: return BudgetResult(allowed=False)
        """
        with self._db.session() as s:
            # Atomic check-and-deduct
            result = s.execute(
                "UPDATE budgets SET budget_pool = budget_pool - :cost, "
                "                     reserved = reserved + :cost "
                "WHERE tenant_id = :tid AND budget_pool >= :cost "
                "RETURNING budget_pool",
                {"cost": cost, "tenant_id": tenant_id}
            )
            row = result.fetchone()
            if row is None:
                remaining = s.execute(
                    "SELECT budget_pool FROM budgets WHERE tenant_id = :tid",
                    {"tid": tenant_id}
                ).fetchone()
                pool = remaining["budget_pool"] if remaining else 0
                return BudgetResult(
                    allowed=False,
                    reason=f"Budget: {pool} remaining, need {cost}",
                )
            # Create reservation record
            reservation = BudgetReservation(
                reservation_id=generate_reservation_id(),
                tenant_id=tenant_id,
                user_id=user_id,
                execution_id=execution_id,
                step_id=step_id,
                cost=cost,
                status=ReservationState.RESERVED,
                created_at=time.time(),
            )
            s.execute(
                "INSERT INTO budget_reservations "
                "(reservation_id, tenant_id, user_id, execution_id, step_id, cost, status, created_at) "
                "VALUES (:rid, :tid, :uid, :eid, :sid, :cost, 'reserved', :ts)",
                {
                    "rid": reservation.reservation_id,
                    "tid": tenant_id,
                    "uid": user_id,
                    "eid": execution_id,
                    "sid": step_id,
                    "cost": cost,
                    "ts": time.time(),
                }
            )
            return BudgetResult(allowed=True, reservation=reservation)

    def commit(self, reservation: BudgetReservation) -> bool:
        """Commit reserved budget after confirmed success (COMPLETED).

        MC-051 fix: Only accepts 'reserved' status. Locked reservations
        must go through resolve_locked() — nothing else may touch 'locked'.
        Idempotent — second call is a no-op.
        Returns True if state changed, False if already committed.
        """
        with self._db.session() as s:
            result = s.execute(
                "UPDATE budget_reservations SET status = 'committed', committed_at = :ts "
                "WHERE reservation_id = :rid AND status = 'reserved'",
                {"ts": time.time(), "rid": reservation.reservation_id}
            )
            if result.rowcount == 0:
                return False  # Already committed or not in reserved state
            # Decrement reserved counter — budget_pool was already reduced in reserve()
            s.execute(
                "UPDATE budgets SET reserved = reserved - :cost WHERE tenant_id = :tid",
                {"cost": reservation.cost, "tenant_id": reservation.tenant_id}
            )
            return True

    def release(self, reservation: BudgetReservation) -> bool:
        """Release reserved budget after confirmed failure (FAILED).

        Restores budget_pool. Idempotent — second call is a no-op.
        Returns True if state changed, False if already released.
        """
        with self._db.session() as s:
            # Only release if still reserved or locked
            result = s.execute(
                "UPDATE budget_reservations SET status = 'released', released_at = :ts "
                "WHERE reservation_id = :rid AND status IN ('reserved', 'locked')",
                {"ts": time.time(), "rid": reservation.reservation_id}
            )
            if result.rowcount == 0:
                return False  # Already released
            # Restore budget_pool
            s.execute(
                "UPDATE budgets SET budget_pool = budget_pool + :cost, "
                "                     reserved = reserved - :cost "
                "WHERE tenant_id = :tid",
                {"cost": reservation.cost, "tenant_id": reservation.tenant_id}
            )
            return True

    def lock(self, reservation: BudgetReservation) -> None:
        """Lock budget on inconclusive timeout (UNKNOWN outcome).

        Budget stays deducted. Status → 'locked'. Do NOT restore budget_pool.
        """
        with self._db.session() as s:
            s.execute(
                "UPDATE budget_reservations SET status = 'locked', locked_at = :ts "
                "WHERE reservation_id = :rid AND status IN ('reserved', 'locked')",
                {"ts": time.time(), "rid": reservation.reservation_id}
            )

    def resolve_locked(self, reservation: BudgetReservation, probe_outcome: str) -> bool:
        """Resolve a locked reservation after probe completes.

        BUDGET-002/MC-051 fix: Only method that may transition 'locked' -> anything.
        - probe_outcome='executed' -> commit (budget permanently deducted)
        - probe_outcome='not_executed' -> release (budget restored)
        - probe_outcome='inconclusive' -> keep locked (sweeper will handle later)
        Returns True if state changed.
        """
        with self._db.session() as s:
            if probe_outcome == 'executed':
                result = s.execute(
                    "UPDATE budget_reservations SET status = 'committed', committed_at = :ts "
                    "WHERE reservation_id = :rid AND status = 'locked'",
                    {"ts": time.time(), "rid": reservation.reservation_id}
                )
                if result.rowcount > 0:
                    s.execute(
                        "UPDATE budgets SET reserved = reserved - :cost WHERE tenant_id = :tid",
                        {"cost": reservation.cost, "tenant_id": reservation.tenant_id}
                    )
                    return True
            elif probe_outcome == 'not_executed':
                result = s.execute(
                    "UPDATE budget_reservations SET status = 'released', released_at = :ts "
                    "WHERE reservation_id = :rid AND status = 'locked'",
                    {"ts": time.time(), "rid": reservation.reservation_id}
                )
                if result.rowcount > 0:
                    s.execute(
                        "UPDATE budgets SET budget_pool = budget_pool + :cost, "
                        "                     reserved = reserved - :cost "
                        "WHERE tenant_id = :tid",
                        {"cost": reservation.cost, "tenant_id": reservation.tenant_id}
                    )
                    return True
            return False  # inconclusive or already resolved

    def sweep_expired_locks(self) -> int:
        """Release budget locks older than 24 hours.

        BUDGET-002 fix: This is a SAFETY NET ONLY. It should rarely fire
        because the probe path should resolve most locks. Auto-releasing
        a lock means we are unsure if the provider executed the operation.
        Returns count of locks released.
        """
        cutoff = time.time() - 86400  # 24 hours
        with self._db.session() as s:
            expired = s.execute(
                "SELECT reservation_id, tenant_id, cost FROM budget_reservations "
                "WHERE status = 'locked' AND locked_at < :cutoff",
                {"cutoff": cutoff}
            ).fetchall()
            count = 0
            for row in expired:
                # Release each expired lock
                result = s.execute(
                    "UPDATE budget_reservations SET status = 'released', released_at = :ts "
                    "WHERE reservation_id = :rid AND status = 'locked'",
                    {"ts": time.time(), "rid": row.reservation_id}
                )
                if result.rowcount > 0:
                    s.execute(
                        "UPDATE budgets SET budget_pool = budget_pool + :cost, "
                        "                     reserved = reserved - :cost "
                        "WHERE tenant_id = :tid",
                        {"cost": row.cost, "tenant_id": row.tenant_id}
                    )
                    count += 1
            return count
```

### Timeout Lock Rule (CRITICAL)

```python
def handle_timeout(self, reservation: BudgetReservation) -> None:
    """On timeout: transition to LOCKED via lock().

    Why: The remote operation may have succeeded. We don't know.
    Budget is released only after provider probe confirms outcome:
    - Probe confirms EXECUTED → commit()
    - Probe confirms NOT_EXECUTED → release()
    - Probe inconclusive → lock() again (stays locked)
    - 24h sweeper → auto-release as safety net
    """
    self._budget.lock(reservation)
```

### Execution Flow

```
S8 Precheck:      affordability_check(tenant_id, estimated_cost)
                  ├─ Affordable → proceed to S12 (no reservation created)
                  └─ Not affordable → DENY

S12 Execution:    guard.execute_step()
                  ├─ reserve(tenant_id, user_id, execution_id, step_id, cost)
                  │   └─ BudgetResult(allowed=True, reservation=R1) → proceed
                  │   └─ BudgetResult(allowed=False) → DENY
                  ├─ SUCCESS → commit(R1) → status=committed, reserved--
                  ├─ FAILURE → release(R1) → status=released, budget_pool++, reserved--
                  ├─ TIMEOUT → lock(R1) → status=locked
                  └─ PROBE RESULT:
                      ├─ EXECUTED → resolve_locked(R1, 'executed') → commit
                      ├─ NOT_EXECUTED → resolve_locked(R1, 'not_executed') → release
                      └─ INCONCLUSIVE → stays locked (sweeper safety net)

Lease Recovery:   For each in-flight step:
                  ├─ Probe EXECUTED → resolve_locked(R, 'executed')
                  ├─ Probe NOT_EXECUTED → resolve_locked(R, 'not_executed')
                  └─ Probe inconclusive → stays locked (sweeper safety net)

Sweeper:           Every 1h: release locks older than 24h (safety net only)
```

### Rules
1. `reserve()` is the ONLY budget gate — no separate preflight check
2. Atomic reserve via `UPDATE ... WHERE budget_pool >= cost` (no race conditions)
3. Budget is per-tenant (`budgets.budget_pool`), not per-user
4. `user_id` is attribution only — not the budget gate key
5. Timeout = LOCKED, never RELEASED — budget stays deducted until probe confirms
6. Inconclusive probe = stays LOCKED — never auto-release without manual review or 24h sweep
7. All commit/release/lock operations are idempotent (WHERE status IN (...))
8. Every operation returns bool indicating whether state actually changed
9. BudgetLockSweeper runs hourly, releases locks older than 24h
10. `reservation_id` in `execution_steps` links steps to their budget reservations

---

## 5. Timeout Manager & UNKNOWN Outcome Reconciliation

### Execution Boundary

Wraps adapter calls in a strict `asyncio.wait_for` timeout. **Timeout does NOT mean failure.**

### UNKNOWN Classification (CRITICAL)

A network timeout means we don't know what happened. The remote write may have succeeded before the response timed out. Treating timeout as failure could cause duplicate mutations.

```python
class TimeoutOutcome(Enum):
    EXECUTED = "executed"          # Provider confirmed operation succeeded
    NOT_EXECUTED = "not_executed"  # Provider confirmed operation never ran
    UNKNOWN = "unknown"            # Provider cannot confirm — escalate
```

### Implementation

```python
class TimeoutManager:
    """Per-step timeout enforcement with UNKNOWN outcome."""

    def __init__(self):
        self._step_timeouts: dict[str, float] = {}  # step_id → deadline
        self._plan_deadline: float | None = None

    def set_step_timeout(self, step_id: str, timeout_seconds: int) -> None:
        self._step_timeouts[step_id] = time.time() + timeout_seconds

    def set_plan_timeout(self, timeout_seconds: int) -> None:
        self._plan_deadline = time.time() + timeout_seconds

    async def execute_with_timeout(self, coro, step_id: str, timeout: int) -> KernelResult:
        """Execute with timeout. Returns UNKNOWN on timeout — never 'error'."""
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return KernelResult(
                status="UNKNOWN",
                error="Timeout — outcome unknown, probe required",
                kernel=step_id,
                metadata={"timeout": True, "requires_probe": True},
            )

    async def probe_provider(self, step: ExecutionStep, binding: ProviderBinding) -> ProbeResult:
        """Query provider to determine actual outcome of timed-out operation."""
        # Load adapter from binding
        adapter = load_adapter(binding.adapter_class)

        try:
            # Read-back query to check current state
            state = await adapter.read_state(step.kernel_op_id, step.params, binding)
            if state == "EXECUTED":
                return ProbeResult(outcome=TimeoutOutcome.EXECUTED)
            elif state == "NOT_STARTED":
                return ProbeResult(outcome=TimeoutOutcome.NOT_EXECUTED)
            else:
                return ProbeResult(outcome=TimeoutOutcome.UNKNOWN)
        except Exception as e:
            logger.error(f"Provider probe failed: {e}")
            return ProbeResult(outcome=TimeoutOutcome.UNKNOWN)
```

### Probe Sequence After Timeout

| Probe Result | Action |
|-------------|--------|
| EXECUTED | Commit budget, mark step COMPLETED |
| NOT_EXECUTED | Release budget, allow retry/rollback |
| UNKNOWN (inconclusive) | Escalate to DEAD_LETTER (S14) for manual review |

### Rules
1. Each step has its own timeout (from kernel policy)
2. The entire plan has a maximum timeout (default: 5 minutes)
3. **Timeout produces `KernelResult(status="UNKNOWN")` — NOT "error", NOT "failed"**
4. No automatic retry on timeout — provider probe determines next action
5. Budget reservation is NEVER released on timeout — remains locked until probe
6. If probe is inconclusive → DEAD_LETTER (S14) for manual review

---

## 6. Bulkhead

### Purpose

Isolate provider failures. If GHL goes down, Notion should still work. Bulkhead is Layer 5 — closest to the adapter, enforced last.

### Implementation

```python
class Bulkhead:
    """Isolate provider failures with per-provider semaphores."""

    def __init__(self):
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._max_concurrent = 10  # Configurable per provider

    def get_semaphore(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._semaphores:
            self._semaphores[provider] = asyncio.Semaphore(self._max_concurrent)
        return self._semaphores[provider]

    async def acquire(self, provider: str) -> AsyncContextManager:
        """Acquire semaphore for provider. Blocks if at capacity."""
        semaphore = self.get_semaphore(provider)
        await semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()
```

### Rules
1. Each provider has its own semaphore
2. Max concurrent operations per provider is configurable
3. When a provider's circuit is open, requests are blocked before reaching the bulkhead (Layer 1 check)
4. Bulkhead prevents one provider from consuming all connection slots

---

## 7. Health Monitor

### Purpose

Track provider health scores and enable automatic degradation.

### Implementation

```python
class HealthMonitor:
    """Track provider health scores."""

    def __init__(self):
        self._scores: dict[str, float] = {}  # provider → health score (0.0-1.0)

    def record_success(self, provider: str, latency_ms: float) -> None:
        score = self._scores.get(provider, 1.0)
        # Boost score on success, weighted by latency
        boost = max(0.01, 1.0 - (latency_ms / 10000))  # Cap boost at 0.01
        self._scores[provider] = min(1.0, score + boost * 0.1)

    def record_failure(self, provider: str) -> None:
        score = self._scores.get(provider, 1.0)
        self._scores[provider] = max(0.0, score - 0.2)

    def get_health(self, provider: str) -> HealthStatus:
        score = self._scores.get(provider, 1.0)
        if score > 0.8:
            return HealthStatus.HEALTHY
        elif score > 0.5:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNHEALTHY

    def is_available(self, provider: str) -> bool:
        return self.get_health(provider) != HealthStatus.UNHEALTHY
```

### Health Scores

| Score | Status | Behavior |
|-------|--------|----------|
| > 0.8 | HEALTHY | Normal operation |
| 0.5 - 0.8 | DEGRADED | Increased retry backoff |
| < 0.5 | UNHEALTHY | Prefer alternative providers |

---

## 8. Reliability Guard Wrapper

### Complete Integration

```python
class ReliabilityGuard:
    """The complete 5-layer reliability guard.

    Layers wrap from outside in: Layer 1 checked first, Layer 5 closest to adapter.
    Bulkhead (Layer 5) is acquired FIRST to reserve the connection slot before
    any other checks — this prevents deadlocks where a blocked Layer 1 check
    holds a slot that another request needs.
    """

    def __init__(self, db: Database):
        self._circuit_breakers = CircuitBreakerRegistry()  # per (provider, operation)
        self._retry_guard = RetryStormGuard(db)
        self._budget = BudgetTracker(db)
        self._timeout = TimeoutManager()
        self._bulkhead = Bulkhead()
        self._health = HealthMonitor()

    async def execute_step(self, step: ExecutionStep,
                           adapter: BaseAdapter) -> KernelResult:
        """Execute a single step with all 5 reliability layers."""
        provider = step.provider
        operation = step.kernel_op_id

        # Layer 5 FIRST: Bulkhead — reserve connection slot
        semaphore = self._bulkhead.get_semaphore(provider)
        async with semaphore:
            return await self._execute_internal(step, adapter)

    async def _execute_internal(self, step: ExecutionStep,
                                adapter: BaseAdapter) -> KernelResult:
        """Execute with Layers 1-4 inside the bulkhead."""
        provider = step.provider
        operation = step.kernel_op_id
        breaker = self._circuit_breakers.get(provider, operation, step.context.tenant_id)

        # Layer 1: Circuit breaker (per provider+operation)
        if not breaker.allow_request():
            return KernelResult(
                status="error",
                error=f"Circuit open for {provider}:{operation}",
                kernel=operation,
                metadata={"circuit_open": True, "provider": provider, "operation": operation},
            )

        # Layer 3: Budget reserve (ONLY reservation point — per step-attempt at S12)
        # BUDGET-002 fix: No preflight at S8. S12 is the only reservation point.
        reservation = self._budget.reserve(
            tenant_id=step.context.tenant_id,
            user_id=step.context.user_id,
            execution_id=step.context.execution_id,
            step_id=step.id,
            cost=step.cost,
        )
        if not reservation.allowed:
            return KernelResult(status="error", error=reservation.reason, kernel=operation)

        # Determine max attempts from mutation policy
        max_attempts = get_max_attempts(
            step.mutation, step.retry_safety, step.is_idempotent
        )
        last_result = None

        for attempt in range(1, max_attempts + 1):
            # Layer 2: Retry storm guard (skip on first attempt)
            if attempt > 1 and not self._retry_guard.should_retry(provider, operation):
                self._budget.release(reservation)
                return KernelResult(
                    status="error",
                    error="Retry storm prevention — too many retries",
                    kernel=operation,
                    attempt=attempt,
                )

            # Layer 4: Timeout wrapper
            # CRIT-006: step timeout must be < client timeout (35s) so guard wins the race
            # Default 25s gives 10s buffer below adapter's 35s httpx timeout
            step_timeout = step.timeout_seconds or 25
            result = await self._timeout.execute_with_timeout(
                adapter.call(step.kernel_op_id, step.params, step.binding, step.context),
                step.id, step_timeout,
            )

            if result.status == "UNKNOWN":
                # Bug #3 fix: Timeout — lock budget, initiate probe
                logger.warning(f"Timeout on {provider}:{operation} — initiating probe")
                self._budget.lock(reservation)
                probe_result = await self._timeout.probe_provider(step, step.binding)

                if probe_result.outcome == TimeoutOutcome.EXECUTED:
                    # Bug #4 fix: Use probe data, not timed-out call's None data
                    self._budget.resolve_locked(reservation, 'executed')
                    breaker.record_success()
                    self._health.record_success(provider, 0)
                    return KernelResult(
                        status="ok",
                        data=probe_result.data,
                        kernel=operation,
                        metadata={"reconciled": True, "probe": "executed"},
                    )
                elif probe_result.outcome == TimeoutOutcome.NOT_EXECUTED:
                    # Provider confirms never ran — release and retry
                    self._budget.resolve_locked(reservation, 'not_executed')
                    breaker.record_failure()
                    self._health.record_failure(provider)
                    if attempt < max_attempts:
                        # BUDGET-002: re-reserve for retry (release old, create new)
                        self._budget.release(reservation)
                        reservation = self._budget.reserve(
                            tenant_id=step.context.tenant_id,
                            user_id=step.context.user_id,
                            execution_id=step.context.execution_id,
                            step_id=step.id,
                            cost=step.cost,
                        )
                        if not reservation.allowed:
                            return KernelResult(status="error", error=reservation.reason, kernel=operation)
                        delay = calculate_backoff(attempt)
                        await asyncio.sleep(delay)
                        continue
                    return KernelResult(
                        status="error",
                        error="Operation not executed (confirmed by probe)",
                        kernel=operation,
                        metadata={"probe": "not_executed"},
                    )
                else:
                    # Bug #3 fix: Inconclusive -> DEAD_LETTER (not FAILED)
                    # Budget stays locked for manual review
                    self._health.record_failure(provider)
                    return KernelResult(
                        status="dead_letter",
                        error="Timeout probe inconclusive — budget locked pending manual review",
                        kernel=operation,
                        metadata={"probe": "inconclusive", "step_id": step.id, "budget_locked": True},
                    )

            if result.status == "ok":
                breaker.record_success()
                self._budget.commit(reservation)
                self._health.record_success(provider, result.duration_ms or 0)
                return result

            # MC-063 fix: PARTIAL is terminal — commit budget, do NOT retry
            # Partial means some sub-operations succeeded; the step is done
            if result.status == "partial":
                breaker.record_success()
                self._budget.commit(reservation)
                self._health.record_success(provider, result.duration_ms or 0)
                return result

            # Failed — record and check retry
            breaker.record_failure()
            last_result = result

            if not self._should_retry(step, result, attempt, max_attempts):
                self._budget.release(reservation)
                self._health.record_failure(provider)
                return result

            # Wait before retry
            delay = calculate_backoff(attempt)
            await asyncio.sleep(delay)

        # All attempts exhausted
        self._budget.release(reservation)
        self._health.record_failure(provider)
        return last_result

    def _should_retry(self, step: ExecutionStep, result: KernelResult,
                      attempt: int, max_attempts: int) -> bool:
        """Determine if step should be retried based on mutation policy."""
        if attempt >= max_attempts:
            return False
        if step.mutation == "IRREVERSIBLE":
            return False
        if step.retry_safety == "never":
            return False
        if not self._is_retryable_error(result.error):
            return False
        if step.mutation == "D" and not step.is_idempotent:
            return False
        # MC-027 fix: Non-idempotent W mutations must not be retried (duplicate creates)
        if step.mutation == "W" and not step.is_idempotent:
            return False
        return True

    def _is_retryable_error(self, error: str | None) -> bool:
        """Check if error type is retryable."""
        if not error:
            return False
        retryable = ["timeout", "connection", "rate_limit", "502", "503", "504"]
        return any(pattern in error.lower() for pattern in retryable)
```

---

*End of Reliability.*

---

## Appendix A: Timeout → UNKNOWN Outcome (CRITICAL — from forensic audit)

The current design incorrectly treats timeout as "failure." This is **wrong**. When a step times out, we don't know what happened. The adapter may have succeeded, partially succeeded, or completely failed.

### The Bug

**Wrong** (current code):
```python
# BUG: Timeout treated as failure
result = await asyncio.wait_for(step.execute(), timeout=timeout)
except asyncio.TimeoutError:
    # This is WRONG — we don't know if the operation succeeded
    self._mark_step_failed(step_id)
    self._trigger_retry(step_id)
```

**Correct** (what to build):
```python
# CORRECT: Timeout = UNKNOWN outcome
result = await asyncio.wait_for(step.execute(), timeout=timeout)
except asyncio.TimeoutError:
    # Timeout = UNKNOWN — do NOT mark as failed, do NOT retry blindly
    self._mark_step_unknown(step_id)
    self._initiate_probe(step_id, binding)  # Verify with the provider
```

### Rules for Timeout Handling

| Rule | Implementation |
|------|---------------|
| Timeout ≠ Failure | A timed-out step is UNKNOWN, not FAILED |
| No automatic retry | Do NOT retry on timeout — probe first |
| Must probe provider | Always verify with provider whether operation succeeded |
| Budget is locked | Timeout reservation is NOT released until probe confirms |
| Rollback only after probe | Do NOT rollback until we know the actual outcome |

### Probe Sequence After Timeout

```python
class TimeoutProbe:
    """Probe provider after timeout to determine actual outcome."""
    
    async def probe(self, step: ExecutionStep, binding: ProviderBinding) -> ProbeResult:
        """Check with provider what actually happened."""
        # 1. Query provider for current state
        provider_state = await self._check_provider_state(step, binding)
        
        if provider_state == "SUCCEEDED":
            # Provider confirms the operation succeeded
            return ProbeResult(outcome="COMPLETED", state=provider_state)
        
        elif provider_state == "NOT_STARTED":
            # Provider confirms the operation never executed
            return ProbeResult(outcome="FAILED", state=provider_state)
        
        elif provider_state == "UNKNOWN":
            # Provider can't tell us — we're in a blind spot
            # This is a safety issue — escalate to manual review
            return ProbeResult(outcome="DEAD_LETTER", state=provider_state)
        
        else:
            # Partial state — depends on operation type
            return ProbeResult(outcome="PARTIAL", state=provider_state)
```

### Budget Handling for Timeout

The `reserve → commit/release` pattern must account for UNKNOWN:

```python
def handle_timeout(self, reservation: BudgetReservation, step: ExecutionStep):
    """Budget must stay locked until outcome is known."""
    # DO NOT release the reservation
    # Mark it as "uncertain" — the commit/release decision
    # is made by the probe result
    self._mark_budget_uncertain(reservation)
    
    # When probe returns:
    if probe_result.outcome == "COMPLETED":
        self._commit(reservation)  # Operation actually succeeded
    elif probe_result.outcome == "FAILED":
        self._release(reservation)  # Operation never happened
    elif probe_result.outcome == "PARTIAL":
        self._commit_partial(reservation, probe_result.actual_cost)
    else:  # DEAD_LETTER
        # Escalate to manual review — budget locked until human decides
        self._escalate_for_review(reservation, step)
```

---

## Appendix B: Circuit Breaker Per-Operation (CRITICAL — from forensic audit)

The original design had a circuit breaker per **provider** only. This is **wrong** for a multi-tenant, multi-operation system.

**Wrong** (old design):
```python
# OLD: One circuit breaker per provider
circuit_breakers = {
    "ghl": CircuitBreaker(),     # One breaker for ALL GHL operations
    "notion": CircuitBreaker(),  # One breaker for ALL Notion operations
}
```

**Correct** (new design):
```python
# NEW: One circuit breaker per (provider, kernel_op_id) pair
circuit_breakers = {
    ("ghl", "ghl.contact_search"): CircuitBreaker(),
    ("ghl", "ghl.contact_create"): CircuitBreaker(),
    ("notion", "notion.page_search"): CircuitBreaker(),
    ("notion", "notion.page_create"): CircuitBreaker(),
}
```

### Rules

| Rule | Why |
|------|-----|
| One breaker per (provider, kernel_op_id) | Isolate failures to specific operations |
| Provider-level health still tracked | For display/degradation decisions |
| CircuitBreaker state is persistent | Survives process restarts |
| Break state transitions are logged | For debugging cascading failures |

---

## Appendix C: Retry with Exponential Backoff + Jitter

```python
def calculate_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """Exponential backoff with full jitter."""
    exponential = base_delay * (2 ** (attempt - 1))
    capped = min(exponential, max_delay)
    jittered = random.uniform(0, capped)
    return jittered
```

Max delay cap: 60 seconds. Max attempts: 3.

---

## Appendix D: Failure Injection Test Matrix

| Failure | Expected Behavior |
|---------|-------------------|
| 429 (rate limit) | Backoff + retry, respect Retry-After |
| 500 (server error) | Retry with backoff |
| 503 (service unavailable) | Retry with backoff, then circuit opens |
| Timeout | UNKNOWN → probe provider → commit/release based on probe |
| Credential failure (401/403) | No retry — fail permanently |
| Duplicate request | Idempotency key returns cached result |
| Process crash | Resume from last checkpoint |
| Partial provider success | PARTIAL status, per-item validation |
| Permanent error | Dead letter, human escalation |
| Budget exceeded | Execution stops, budget denied |
| User cancellation | Remaining steps stop gracefully |
| Circuit open | Request blocked, error returned |

---
---

## 9. Worker Heartbeat & Recovery (CODE-PROVEN)

**Source evidence**: Xagent heartbeat-driven autonomous worker loop; AgentsMesh Relay for data plane reliability

### Heartbeat Protocol

```python
class WorkerHeartbeat:
    """Periodic heartbeat to detect worker failure."""

    def __init__(self, worker_id: WorkerId, registry: WorkerRegistry):
        self.worker_id = worker_id
        self.registry = registry
        self._interval = 30  # seconds
        self._miss_count = 0
        self._max_miss = 3   # 3 missed heartbeats = worker considered dead

    async def start(self) -> None:
        """Start heartbeat loop."""
        while self.is_active():
            await self.send_heartbeat()
            await asyncio.sleep(self._interval)

    async def send_heartbeat(self) -> None:
        """Send heartbeat to registry."""
        try:
            await self.registry.record_heartbeat(
                worker_id=self.worker_id,
                timestamp=time.time(),
                metrics=self.get_metrics()
            )
            self._miss_count = 0
        except Exception as e:
            self._miss_count += 1
            if self._miss_count >= self._max_miss:
                self.on_worker_failure()

    def on_worker_failure(self) -> None:
        """Worker missed too many heartbeats — trigger recovery."""
        logger.warning(f"Worker {self.worker_id} heartbeat failure — triggering recovery")
        # Trigger lease recovery for all in-flight executions
        for execution_id in self.get_in_flight_executions():
            self.trigger_recovery(execution_id)
```

### Lease Recovery Pattern (SystemOneHarness / Xagent)

```python
class LeaseRecovery:
    """Recover in-flight executions from dead workers."""

    async def recover(self, execution_id: str, dead_worker_id: WorkerId) -> RecoveryResult:
        """Recover execution from dead worker."""
        # 1. Load execution state
        execution = await self.db.get_execution(execution_id)
        if not execution or execution.status in ("COMPLETED", "FAILED", "DEAD_LETTER"):
            return RecoveryResult(status="no_recovery_needed")

        # 2. Load checkpoint
        checkpoint = await self.db.get_latest_checkpoint(execution_id)
        if not checkpoint:
            # No checkpoint — execution must restart from S0
            return RecoveryResult(status="restart_required")

        # 3. Restore execution context
        context = ExecutionContext.from_dict(checkpoint.context_snapshot)

        # 4. Determine recovery action
        if execution.status == "PENDING":
            return RecoveryResult(status="resume", context=context, step=checkpoint.current_step)
        elif execution.status == "RUNNING":
            # Check which steps completed before crash
            completed = json.loads(checkpoint.completed_steps)
            failed = json.loads(checkpoint.failed_steps)
            pending = [s for s in execution.steps if s.id not in completed and s.id not in failed]
            return RecoveryResult(status="resume_from_checkpoint", context=context, pending_steps=pending)
        elif execution.status == "RECONCILING":
            # Re-run probe for timed-out steps
            return RecoveryResult(status="reconcile", context=context)
        else:
            return RecoveryResult(status="unknown_state_escalate")
```

### Relay Data Plane Pattern (AgentsMesh)

```python
class RelayBuffer:
    """WebSocket relay buffer for terminal data plane.

    AgentsMesh pattern: Browser/Desktop/iOS ↔ Relay ↔ Runner.
    Backend never touches PTY bytes.
    """

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._buffers: dict[str, deque] = {}  # session_id → message buffer
        self._buffer_size = 1000

    async def forward(self, session_id: str, message: bytes) -> None:
        """Forward PTY bytes to connected client."""
        if session_id not in self._connections:
            # Buffer for later delivery
            if session_id not in self._buffers:
                self._buffers[session_id] = deque(maxlen=self._buffer_size)
            self._buffers[session_id].append(message)
            return

        try:
            await self._connections[session_id].send_bytes(message)
        except ConnectionClosed:
            # Buffer for reconnect
            self._buffers[session_id].append(message)
            self._connections.pop(session_id, None)

    async def on_reconnect(self, session_id: str, ws: WebSocket) -> None:
        """Send buffered messages on reconnect."""
        self._connections[session_id] = ws
        buffer = self._buffers.get(session_id, deque())
        for msg in buffer:
            try:
                await ws.send_bytes(msg)
            except ConnectionClosed:
                break
        self._buffers.pop(session_id, None)
```

---

## 10. Scheduler Patterns (CODE-PROVEN)

**Source evidence**: AIOS FIFO/RR scheduler with LLM request batching; SystemOneHarness token-budget scheduler

### FIFO Scheduler

```python
class FIFOScheduler:
    """First-in, first-out execution order."""

    def __init__(self):
        self._queue: deque[QueuedTask] = deque()
        self._running: set[str] = set()

    async def submit(self, task: ExecutionTask) -> str:
        task_id = generate_task_id()
        self._queue.append(QueuedTask(id=task_id, task=task, submitted_at=time.time()))
        self._process_queue()
        return task_id

    async def _process_queue(self) -> None:
        while self._queue and len(self._running) < self._max_concurrent:
            queued = self._queue.popleft()
            self._running.add(queued.id)
            asyncio.create_task(self._execute(queued))
```

### Round-Robin Scheduler

```python
class RoundRobinScheduler:
    """Round-robin across worker pools."""

    def __init__(self, worker_pools: list[WorkerPool]):
        self._pools = worker_pools
        self._current = 0

    async def submit(self, task: ExecutionTask) -> str:
        # Try each pool in round-robin order
        for _ in range(len(self._pools)):
            pool = self._pools[self._current]
            self._current = (self._current + 1) % len(self._pools)

            if await pool.has_capacity():
                return await pool.submit(task)

        # No capacity — queue or reject
        raise NoCapacityError("All worker pools at capacity")
```

### LLM Request Batching (AIOS pattern)

```python
class LLMRequestBatcher:
    """Batch multiple LLM requests for efficiency."""

    def __init__(self, batch_size: int = 10, batch_timeout: float = 0.1):
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._pending: list[LLMRequest] = []

    async def submit(self, request: LLMRequest) -> LLMResponse:
        future = asyncio.Future()
        request.future = future
        self._pending.append(request)

        if len(self._pending) >= self._batch_size:
            await self._flush()
        else:
            asyncio.get_event_loop().call_later(self._batch_timeout, self._flush)

        return await future

    async def _flush(self) -> None:
        """Send batched requests to LLM provider."""
        if not self._pending:
            return

        batch = self._pending[:self._batch_size]
        self._pending = self._pending[self._batch_size:]

        # Send batch to provider
        responses = await self._llm.batch_complete(
            prompts=[r.prompt for r in batch],
            max_tokens=[r.max_tokens for r in batch],
        )

        for request, response in zip(batch, responses):
            request.future.set_result(response)
```

---

## 11. Connection Management Under Failure

### Connection Pool Resilience

```python
class ResilientConnectionPool:
    """Connection pool with automatic recovery."""

    def __init__(self, url: str, max_retries: int = 3):
        self._url = url
        self._max_retries = max_retries
        self._pool = None
        self._reconnecting = False

    async def get_connection(self) -> Connection:
        """Get connection with retry and recovery."""
        for attempt in range(self._max_retries):
            try:
                if self._pool is None:
                    await self._create_pool()
                conn = await self._pool.acquire()
                # Validate connection
                await conn.execute("SELECT 1")
                return conn
            except (ConnectionError, OperationalError) as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                await self._recover_pool()
                if attempt == self._max_retries - 1:
                    raise

    async def _recover_pool(self) -> None:
        """Recreate pool after failure."""
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            if self._pool:
                self._pool.close()
            await self._create_pool()
        finally:
            self._reconnecting = False
```

### Graceful Degradation

```python
class GracefulDegradation:
    """Degrade gracefully under load or failure."""

    def __init__(self):
        self._features: dict[str, Feature] = {}
        self._degraded: set[str] = set()

    def register(self, name: str, feature: Feature) -> None:
        self._features[name] = feature

    def degrade(self, name: str, reason: str) -> None:
        """Degrade a feature."""
        feature = self._features.get(name)
        if feature:
            feature.disable()
            self._degraded.add(name)
            logger.warning(f"Feature degraded: {name} — {reason}")

    def restore(self, name: str) -> None:
        """Restore a degraded feature."""
        feature = self._features.get(name)
        if feature:
            feature.enable()
            self._degraded.discard(name)
            logger.info(f"Feature restored: {name}")
```

---

## 12. Chaos Testing Patterns

### Failure Injection Framework

```python
class ChaosInjector:
    """Inject failures for resilience testing."""

    def __init__(self):
        self._injectors: dict[str, Callable] = {}

    def register(self, name: str, injector: Callable) -> None:
        self._injectors[name] = injector

    async def inject(self, name: str, **kwargs) -> None:
        """Inject a specific failure."""
        injector = self._injectors.get(name)
        if injector:
            await injector(**kwargs)

    @staticmethod
    def latency(latency_ms: int, jitter_ms: int = 0):
        """Inject network latency."""
        async def _inject():
            delay = latency_ms / 1000.0
            if jitter_ms:
                delay += random.uniform(0, jitter_ms / 1000.0)
            await asyncio.sleep(delay)
        return _inject

    @staticmethod
    def error(error_type: type, probability: float = 1.0):
        """Inject random errors."""
        async def _inject():
            if random.random() < probability:
                raise error_type("Chaos injected")
        return _inject

    @staticmethod
    def kill_worker(worker_id: str):
        """Simulate worker crash."""
        async def _inject():
            worker = get_worker(worker_id)
            if worker:
                await worker.crash()
        return _inject
```

### Chaos Test Matrix

| Failure | Injected | Expected Behavior |
|---------|----------|-------------------|
| Provider 500 | `ChaosInjector.error(ProviderError(500))` | Retry with backoff, then circuit opens |
| Provider timeout | `ChaosInjector.latency(35000)` | UNKNOWN outcome, probe provider |
| Worker crash | `ChaosInjector.kill_worker(worker_id)` | Lease recovery, resume from checkpoint |
| Network partition | Disconnect worker from registry | Heartbeat failure, recovery trigger |
| Database overload | `ChaosInjector.error(OperationalError)` | Connection pool recovery, graceful degradation |
| Memory pressure | Limit worker memory | OOM protection, task eviction |
| Disk full | Fill disk during write | Write failure, dead letter, alert |

---

## 13. Adaptive Timeout Configuration

### Dynamic Timeout Adjustment

```python
class AdaptiveTimeout:
    """Adjust timeouts based on historical performance."""

    def __init__(self):
        self._base_timeouts: dict[str, float] = {}
        self._history: dict[str, deque] = {}

    def get_timeout(self, operation: str) -> float:
        """Get adaptive timeout for operation."""
        base = self._base_timeouts.get(operation, 30.0)
        history = self._history.get(operation, deque())

        if not history:
            return base

        # Use P95 of recent completions + safety margin
        recent = list(history)[-20:]  # Last 20 completions
        if recent:
            p95 = sorted(recent)[int(len(recent) * 0.95)]
            return min(max(p95 * 2, base), 120.0)  # Cap at 120s

        return base

    def record_completion(self, operation: str, duration: float) -> None:
        """Record completion time for adaptive adjustment."""
        if operation not in self._history:
            self._history[operation] = deque(maxlen=100)
        self._history[operation].append(duration)
```

---

## 14. Multi-Tenant Resource Isolation

### Tenant-Aware Rate Limiting

```python
class TenantRateLimiter:
    """Per-tenant rate limiting."""

    def __init__(self):
        self._limits: dict[str, RateLimit] = {}
        self._usage: dict[str, deque] = {}

    def configure(self, tenant_id: str, max_rps: int, burst: int) -> None:
        self._limits[tenant_id] = RateLimit(max_rps=max_rps, burst=burst)
        self._usage[tenant_id] = deque(maxlen=burst)

    def check(self, tenant_id: str) -> bool:
        """Check if tenant is within rate limit."""
        limit = self._limits.get(tenant_id)
        if not limit:
            return True

        usage = self._usage.get(tenant_id, deque())
        now = time.time()

        # Remove old entries
        while usage and usage[0] < now - 1.0:
            usage.popleft()

        if len(usage) >= limit.max_rps:
            return False

        usage.append(now)
        return True
```

---

*End of Reliability.*