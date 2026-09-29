# Worker Lifecycle, Independent Verification & Admission Control

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §12 Execution Kernel, §13 Worker Lifecycle, §22 Scheduler. [IDENTITY_AND_TENANCY.md](IDENTITY_AND_TENANCY.md) — Worker Lifecycle section. [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §9 ExecutionResult, §9 ExecutionStatus, §22 RetryDecision. [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S12 Execute, S13 Verify. [RELIABILITY.md](RELIABILITY.md) — Backpressure and Admission Control, 5-layer guard. [DATABASE.md](DATABASE.md) — workers, worker_leases tables.
**Status**: DESIGN_LOCKED, IMPLEMENTATION_NOT_READY
**Worker-management update (2026-09-29)**: §16 added and §3, §10, §11, §13, §15 amended per gate v10 C39 and rulings RD-1…RD-18 (`WORKER_MGMT_SPEC_REVIEW.md` Part E). Each changed passage carries a `Worker-management repair (RD-n)` marker.
**Purpose**: Three P0 additions to close the gaps identified in the architecture review.
  - Item 1: Worker state machines split into two axes (Identity vs Version)
  - Item 2: Independent verification contract for S13
  - Item 3: Admission control sequenced before worker selection inside S12

These are additive — no existing document is modified except where cross-references
are required. Place this document at the same level as PIPELINE_STAGES.md,
DATA_CONTRACTS.md, and RELIABILITY.md.

---

## Table of Contents

1. [Worker Identity Lifecycle](#1-worker-identity-lifecycle)
2. [Worker Version Lifecycle](#2-worker-version-lifecycle)
3. [WorkerIdentity Data Contract](#3-workeridentity-data-contract)
4. [WorkerVersion Data Contract](#4-workerversion-data-contract)
5. [WorkerDeployment Data Contract](#5-workerdeployment-data-contract)
6. [Independent Verification Contract (S13)](#6-independent-verification-contract-s13)
7. [Verifier Data Contract](#7-verifier-data-contract)
8. [VerificationResult Data Contract](#8-verificationresult-data-contract)
9. [Observation Contract](#9-observation-contract)
10. [Admission Control — Sequenced Before Scheduling](#10-admission-control--sequenced-before-scheduling)
11. [AdmissionDecision Data Contract](#11-admissiondecision-data-contract)
12. [S12 Internal Sequence](#12-s12-internal-sequence)
13. [State Locality in Worker Selection](#13-state-locality-in-worker-selection)
14. [ExecutionOwnership Data Contract](#14-executionownership-data-contract)
15. [Implementation Rules](#15-implementation-rules)
16. [Worker Management Settings](#16-worker-management-settings)

---

## 1. Worker Identity Lifecycle

The WorkerIdentity is a durable, database-persisted entity. It represents
WHO is executing — not where or what version.

```
REGISTERED
    │
    │  (worker process starts, leases acquired)
    ▼
ACTIVE
    │
    │  (drain signal received — no new work, finish in-flight)
    ▼
DRAINING
    │
    │  (all in-flight executions reached terminal state)
    ▼
DRAINED
    │
    │  (leases released, process terminating)
    ▼
TERMINATED
```

### State Definitions

| State | Meaning | Accepts New Work | In-Flight Work | Lease Status |
|-------|---------|-----------------|----------------|--------------|
| `REGISTERED` | Created in DB, not yet running | No | No | None |
| `ACTIVE` | Running, healthy, accepting work | Yes | Runs | Acquired |
| `DRAINING` | Finishing in-flight, rejecting new | No | Runs to completion | Held, not renewed |
| `DRAINED` | All work complete, ready to terminate | No | None | Released |
| `TERMINATED` | Removed from pool | No | None | Released |

### State Transitions

```python
class WorkerIdentityState(StrEnum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    TERMINATED = "TERMINATED"


class WorkerIdentityStateValidator:
    LEGAL_TRANSITIONS: dict[WorkerIdentityState, set[WorkerIdentityState]] = {
        WorkerIdentityState.REGISTERED: {
            WorkerIdentityState.ACTIVE,
            WorkerIdentityState.TERMINATED,  # cancelled before start
        },
        WorkerIdentityState.ACTIVE: {
            WorkerIdentityState.DRAINING,
            WorkerIdentityState.TERMINATED,  # force kill
        },
        WorkerIdentityState.DRAINING: {
            WorkerIdentityState.DRAINED,
            WorkerIdentityState.ACTIVE,     # drain cancelled, resume
        },
        WorkerIdentityState.DRAINED: {
            WorkerIdentityState.TERMINATED,
            WorkerIdentityState.ACTIVE,     # restart before terminate
        },
        WorkerIdentityState.TERMINATED: set(),  # terminal
    }

    def validate(self, from_state: WorkerIdentityState,
                 to_state: WorkerIdentityState) -> None:
        if to_state not in self.LEGAL_TRANSITIONS.get(from_state, set()):
            raise StateError(
                f"Illegal worker identity transition: {from_state} -> {to_state}"
            )
```

### Failure Recovery

```
ACTIVE
    │
    │  (heartbeat timeout, lease expired, health check fails)
    ▼
UNHEALTHY
    │
    │  (scheduler confirms no response)
    ▼
RECOVERING
    │
    │  (new process starts, re-acquires lease)
    ▼
ACTIVE
```

`UNHEALTHY` and `RECOVERING` are transient sub-states, not persisted in the
`workers.state` column. They exist only in the scheduler's in-memory view.
The database only sees: ACTIVE → (heartbeat gap) → ACTIVE (new lease epoch).

### Drain Enforcement

When a worker transitions to `DRAINING`:

1. Scheduler stops assigning new executions to this worker
2. Worker continues executing in-flight executions to completion
3. Lease is NOT renewed — it expires naturally
4. When lease expires and no in-flight executions remain: `DRAINED`
5. Scheduler removes worker from eligible pool

The drain boundary is enforced by the scheduler, not by the worker process.
A crashed worker in `DRAINING` state still drains — its executions are
recovered via checkpoint/resume and reassigned to other workers.

---

## 2. Worker Version Lifecycle

WorkerVersion tracks WHAT code is running. Multiple versions of the same
WorkerIdentity can coexist during a rollout.

```
REGISTERED
    │  (version artifact built, hash recorded)
    ▼
INACTIVE
    │
    │  (deployment begins, accepting canary traffic)
    ▼
CANARY
    │
    │  (canary gate passes — errors, latency, success rate)
    ▼
RAMPING
    │
    │  (progressive traffic increase — 10%, 50%, 100%)
    ▼
CURRENT
    │
    │  (new version deployed, this version superseded)
    ▼
DEPRECATED
    │
    │  (drain signal — no new work, existing work finishes)
    ▼
DRAINING
    │
    │  (all in-flight complete)
    ▼
DRAINED
    │
    │  (safe to remove)
    ▼
RETIRED
```

### State Definitions

| State | Meaning | Traffic | Existing Executions | New Executions |
|-------|---------|---------|---------------------|----------------|
| `REGISTERED` | Artifact built, hash recorded | None | N/A | N/A |
| `INACTIVE` | Registered but not receiving traffic | None | N/A | No |
| `CANARY` | Receiving canary traffic only | Canary % | Continue | Only canary-tagged |
| `RAMPING` | Progressive traffic increase | Ramping % | Continue | Ramping-tagged + matched |
| `CURRENT` | Primary production version | 100% | Continue | Yes |
| `DEPRECATED` | New version is CURRENT | Decreasing % | Continue | No new |
| `DRAINING` | Finishing in-flight only | 0% | Finish | No |
| `DRAINED` | All complete, version idle | 0% | None | No |
| `RETIRED` | Artifact removed from serving | 0% | None | No |

### State Transitions

```python
class WorkerVersionState(StrEnum):
    REGISTERED = "REGISTERED"
    INACTIVE = "INACTIVE"
    CANARY = "CANARY"
    RAMPING = "RAMPING"
    CURRENT = "CURRENT"
    DEPRECATED = "DEPRECATED"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    RETIRED = "RETIRED"


class WorkerVersionStateValidator:
    LEGAL_TRANSITIONS: dict[WorkerVersionState, set[WorkerVersionState]] = {
        WorkerVersionState.REGISTERED: {WorkerVersionState.INACTIVE},
        WorkerVersionState.INACTIVE: {
            WorkerVersionState.CANARY,
            WorkerVersionState.RETIRED,  # never deployed
        },
        WorkerVersionState.CANARY: {
            WorkerVersionState.RAMPING,  # canary passed
            WorkerVersionState.DEPRECATED,  # canary failed, rollback
        },
        WorkerVersionState.RAMPING: {
            WorkerVersionState.CURRENT,  # ramp complete
            WorkerVersionState.DEPRECATED,  # ramp failed, rollback
        },
        WorkerVersionState.CURRENT: {
            WorkerVersionState.DEPRECATED,  # new version deployed
        },
        WorkerVersionState.DEPRECATED: {
            WorkerVersionState.DRAINING,
            WorkerVersionState.CURRENT,  # rollback (new version failed)
        },
        WorkerVersionState.DRAINING: {
            WorkerVersionState.DRAINED,
            WorkerVersionState.CURRENT,  # rollback before drained
        },
        WorkerVersionState.DRAINED: {
            WorkerVersionState.RETIRED,
            WorkerVersionState.CURRENT,  # rollback after drain
        },
        WorkerVersionState.RETIRED: set(),  # terminal
    }

    def validate(self, from_state: WorkerVersionState,
                 to_state: WorkerVersionState) -> None:
        if to_state not in self.LEGAL_TRANSITIONS.get(from_state, set()):
            raise StateError(
                f"Illegal worker version transition: {from_state} -> {to_state}"
            )
```

### Rollout Gates

Before advancing from CANARY → RAMPING → CURRENT, a gate workflow
verifies:

| Gate | Threshold | Action on Failure |
|------|-----------|-------------------|
| Error rate | < 1% of canary executions | Reject → DEPRECATED (rollback) |
| P99 latency | < 500ms | Reject → DEPRECATED |
| Success rate | > 99% | Pass |
| Dead letter rate | < 0.1% | Reject → DEPRECATED |

Only ONE version of a WorkerIdentity can be `CURRENT` at any time.
The scheduler routes new executions only to the `CURRENT` version
(plus canary-tagged executions to the `CANARY` version).

### Key Rule: Identity ≠ Version ≠ Runtime

```
WorkerIdentity (durable, DB-persisted)
  │
  ├── WorkerVersion v1.4.0 → state: DEPRECATED → DRAINING → DRAINED
  │     └── WorkerRuntimeInstance A (process, container)
  │     └── WorkerRuntimeInstance B (process, container)
  │
  ├── WorkerVersion v1.5.0 → state: CURRENT
  │     └── WorkerRuntimeInstance C (process, container)
  │     └── WorkerRuntimeInstance D (process, container)
  │
  └── WorkerVersion v1.6.0 → state: CANARY
        └── WorkerRuntimeInstance E (process, container)
```

A WorkerIdentity persists across all versions. Versions are immutable
once registered (hash-signed). Runtime instances are ephemeral.

---

## 3. WorkerIdentity Data Contract

```python
@dataclass(frozen=True)
class WorkerIdentity:
    """Durable worker identity. Persisted in DB. Survives restarts.

    This is WHO executes. It is NOT where, NOT what version, NOT a process.
    See STATE_TRANSITIONS.md §4 for the complete state machine.
    """
    worker_id: str                    # UUID v4 — immutable
    tenant_id: str                    # Isolation boundary
    workspace_id: str                 # Workspace scope
    worker_class: str                 # Classification (e.g., "execution", "scheduler")
    capability_profile: frozenset[str]  # Capability IDs this worker can execute
    state: WorkerIdentityState        # Current lifecycle state
    capacity: int                     # Max concurrent executions
    current_load: int                 # Current in-flight executions
    lease_epoch: int                  # Newest fence token issued to this worker (gate C25)
    heartbeat_at: float | None        # Last heartbeat timestamp
    last_assignment_at: float | None  # Last execution assignment
    created_at: float                 # Registration timestamp
    updated_at: float                 # Last state change timestamp
```

### Database Schema

```sql
CREATE TABLE workers (
    worker_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    worker_class TEXT NOT NULL,                    -- execution | scheduler | system
    capability_profile JSONB NOT NULL,             -- ["contact_create", "page_create"]
    state TEXT NOT NULL DEFAULT 'REGISTERED',      -- WorkerIdentityState values (FINAL_ARCHITECTURE §26 aligned in v9)
    capacity INTEGER NOT NULL DEFAULT 1,
    current_load INTEGER NOT NULL DEFAULT 0,
    lease_epoch BIGINT NOT NULL DEFAULT 0,
    heartbeat_at REAL,
    last_assignment_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_workers_tenant ON workers(tenant_id);
CREATE INDEX idx_workers_workspace ON workers(workspace_id);
CREATE INDEX idx_workers_state ON workers(state);
```

> **Worker-management repair (RD-1, RD-2):** DATABASE.md is authoritative for this table. Owner ruling: `worker_id` is `TEXT` (as here), and every referencing column is `TEXT`; DATABASE.md's `UUID` is superseded. Existing `REAL` timestamps stay; new time columns are `TIMESTAMPTZ` compared with database `NOW()`. Management columns are in §16.1.

### Invariants

1. `current_load <= capacity` at all times
2. `lease_epoch` changes on every lease acquisition and renewal — it records the newest fence token issued to this worker (tokens come from one database sequence). Stale owners cannot commit: the write fence is checked **per execution** against `execution_ownership.fencing_token` (gate C25), so other executions on the same worker (capacity > 1) are never fenced out by one lease's renewal
3. `state` transitions must pass `WorkerIdentityStateValidator`
4. `capability_profile` is set at registration and never changes
   (capability changes require a new worker registration)
5. The management columns of §16.1 are mutable. A change affects only leases acquired after it (I-017); it never alters a lease already held or a running step.

> **Worker-management repair (RD-4, RD-5):** invariant 5 added. `capability_profile`, `worker_class` and `tenant_id` remain immutable.

---

## 4. WorkerVersion Data Contract

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

### Database Schema

```sql
CREATE TABLE worker_versions (
    version_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),
    version TEXT NOT NULL,                         -- semver
    artifact_hash TEXT NOT NULL,                   -- SHA-256
    state TEXT NOT NULL DEFAULT 'REGISTERED',      -- WorkerVersionState values
    canary_percentage INTEGER NOT NULL DEFAULT 0,  -- 0-100
    rollout_config JSONB,                          -- gate thresholds, ramp schedule
    deployed_at REAL,
    promoted_at REAL,
    deprecated_at REAL,
    drained_at REAL,
    created_at REAL NOT NULL,

    UNIQUE(worker_id, artifact_hash)  -- same hash = same version
);
CREATE INDEX idx_worker_versions_worker ON worker_versions(worker_id);
CREATE INDEX idx_worker_versions_state ON worker_versions(state);
CREATE INDEX idx_worker_versions_worker_state ON worker_versions(worker_id, state);
```

### Invariants

1. `artifact_hash` is immutable — a new hash creates a new WorkerVersion row
2. Exactly one version per WorkerIdentity can be `CURRENT` at any time
   (enforced by scheduler query: `WHERE state = 'CURRENT'` returning one row)
3. `canary_percentage` is 0 for all states except `CANARY` and `RAMPING`
4. Rollback is a state transition: `DEPRECATED → CURRENT` (the old version)
   or `DEPRECATED → RAMPING` (re-ramp the old version)

---

## 5. WorkerDeployment Data Contract

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

### Database Schema

```sql
CREATE TABLE worker_deployments (
    deployment_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),
    version_id TEXT NOT NULL REFERENCES worker_versions(version_id),
    runtime_instance_id TEXT NOT NULL,             -- pod/container ID
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 1,
    current_load INTEGER NOT NULL DEFAULT 0,
    health_status TEXT NOT NULL DEFAULT 'healthy', -- healthy | degraded | unhealthy
    last_heartbeat_at REAL NOT NULL,
    started_at REAL NOT NULL,
    terminated_at REAL
);
CREATE INDEX idx_deployments_worker ON worker_deployments(worker_id);
CREATE INDEX idx_deployments_version ON worker_deployments(version_id);
CREATE INDEX idx_deployments_health ON worker_deployments(health_status);
```

### Relationship to Existing Tables

`worker_deployments` replaces and extends the existing `workers` table's
runtime tracking. The `workers` table holds the durable identity.
`worker_deployments` holds ephemeral runtime instances.

Existing `worker_leases` table links to `workers.worker_id` (unchanged).
The scheduler queries `worker_deployments` for capacity and health,
then writes leases against `workers.worker_id`.

---

## 6. Independent Verification Contract (S13)

### The Core Principle

A worker's self-reported success is NOT evidence. The verifier must
independently observe the post-execution state.

```
WORKER
  │
  │ executes step via adapter
  ▼
ADAPTER returns KernelResult(status="ok", data=...)
  │
  │  This is the worker's CLAIM. It is NOT trusted as truth.
  ▼
VERIFIER
  │
  │  independently observes actual state
  │  (e.g., GET the created resource, query the provider)
  ▼
OBSERVATION
  │
  │  compare observation against expected state
  ▼
VERDICT
  │
  ├── PASS     → step marked COMPLETED
  ├── FAIL     → step marked FAILED, retry or DLQ
  └── UNKNOWN  → step marked UNKNOWN, PROBE cycle begins
```

### What the Verifier Checks

| Check Type | How | Example |
|------------|-----|---------|
| Existence | Does the resource exist? | GET /contacts/{id} → 200 |
| Properties | Do fields match expected? | name == "John Doe" |
| Count | Was the right number created? | List returned 1 result |
| Side effects | Did dependent operations succeed? | Related record exists |
| Idempotency | Is the result stable on re-read? | GET twice, same result |

### What the Verifier Does NOT Do

- The verifier does NOT call the adapter's `call()` method again
- The verifier does NOT trust the adapter's `KernelResult.data` field
- The verifier does NOT re-authorize — S8 already passed
- The verifier does NOT re-resolve bindings — S5 is frozen

### Verification Is Mandatory for All Mutations

| Mutation | Verification Required | Method |
|----------|----------------------|--------|
| R | No — reads are self-verifying | N/A |
| W | Yes | Observe written resource |
| D | Yes | Confirm resource absent |
| IRREVERSIBLE | Yes + human notification | Observe + notify on failure |

---

## 7. Verifier Data Contract

```python
@dataclass(frozen=True)
class Verifier:
    """Independent post-execution verifier.

    Does not consume worker self-reports as evidence.
    Observes actual provider state via read operations.
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

### Verifier Construction (S11)

The verifier is constructed at S11 (Freeze Manifest) from the step definition.
It is NOT constructed at S13 — S13 only executes the pre-built verifier.

```python
# At S11, for each step:
def build_verifier(step: Step, binding: FrozenBindingIdentity) -> Verifier:
    """Build verifier from step definition. Called once, frozen in manifest."""
    return Verifier(
        verifier_id=generate_verifier_id(),
        step_id=step.id,
        execution_id=plan.execution_id,
        kernel_op_id=step.kernel_op_id,
        binding_id=binding.binding_id,
        expected_state=step.expected_state,  # from plan definition
        observation_method=_resolve_observation_method(step.kernel_op_id),
        observation_params=_resolve_observation_params(step),
        max_attempts=3,
        attempt_delay_ms=1000,
    )
```

### Observation Methods Registry

Each kernel_op that produces a mutation must have a registered observation method:

```python
OBSERVATION_METHODS: dict[str, ObservationMethod] = {
    # GHL operations
    "ghl.contact_create": ObservationMethod(
        method="get_contact",
        params_from_result=lambda r: {"contact_id": r.data["id"]},
    ),
    "ghl.contact_update": ObservationMethod(
        method="get_contact",
        params_from_result=lambda r: {"contact_id": r.data["id"]},
    ),
    "ghl.contact_delete": ObservationMethod(
        method="get_contact",
        params_from_result=lambda r: {"contact_id": r.data["id"]},
        expect_not_found=True,  # Should return 404
    ),

    # Notion operations
    "notion.page_create": ObservationMethod(
        method="get_page",
        params_from_result=lambda r: {"page_id": r.data["id"]},
    ),
}
```

`params_from_result` extracts the identifier from the adapter's result
to construct the observation query. The verifier uses these params —
not the adapter's result data — to query the provider.

---

## 8. VerificationResult Data Contract

```python
@dataclass(frozen=True)
class VerificationResult:
    """Outcome of independent verification."""
    verifier_id: str                 # Links to Verifier
    step_id: str
    execution_id: str
    verdict: str                     # PASS | FAIL | UNKNOWN
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
| `FAIL` | Observation contradicts expected state | Step → FAILED, retry or DLQ |
| `UNKNOWN` | Observation inconclusive (timeout, partial data) | Retry observation (up to max_attempts) |


> **S12–S15 gate v9 repair (C19, C32):** A verification UNKNOWN (after the bounded attempts below) opens a VERIFICATION episode that re-runs only the layers not yet PASS; the provider probe and the adapter are never called for it. Observations use `BaseAdapter.observe()`; its default returns an inconclusive observation, so a mutation on an adapter without observation support ends in DEAD_LETTER, never in silent success (register RES-5).

### Verification Is Bounded

```python
class VerificationEngine:
    MAX_ATTEMPTS = 3
    ATTEMPT_DELAY_MS = 1000
    OBSERVATION_TIMEOUT_MS = 5000

    async def verify(self, verifier: Verifier,
                     adapter_result: KernelResult) -> VerificationResult:
        observations = []
        verdict = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            obs = await self._observe(verifier, adapter_result)
            observations.append(obs)

            if obs.matches_expected is True:
                verdict = "PASS"
                break
            elif obs.matches_expected is False:
                verdict = "FAIL"
                break
            else:
                # UNKNOWN — wait and retry
                await asyncio.sleep(self.ATTEMPT_DELAY_MS / 1000)

        if verdict is None:
            verdict = "UNKNOWN"

        return VerificationResult(
            verifier_id=verifier.verifier_id,
            step_id=verifier.step_id,
            execution_id=verifier.execution_id,
            verdict=verdict,
            observations=observations,
            decided_at=time.time(),
            decided_at_attempt=len(observations),
            duration_ms=sum(o.duration_ms for o in observations),
        )
```

---

## 9. Observation Contract

The observation contract defines HOW the verifier queries the provider.
It is separate from the execution adapter — the verifier uses read-only
operations, never mutations.

### Observation Invariants

1. Observation calls use the SAME binding as the execution (same provider, same credentials)
2. Observation calls are read-only — they never mutate state
3. Observation calls bypass the reliability guard's circuit breaker
   (if the circuit is open for writes, reads may still succeed)
4. Observation failures (network error, timeout) produce `UNKNOWN`, never `FAIL`
5. Only a successful observation with contradictory data produces `FAIL`

### Observation vs Execution Comparison

| Aspect | Execution | Observation |
|--------|-----------|-------------|
| Purpose | Mutate state | Read state |
| Uses reliability guard | Yes (full 5-layer) | No — lightweight retry only |
| Circuit breaker | Per-(provider, operation) write breaker | Separate read path |
| Budget cost | Yes (per step) | No cost |
| Retry | Full retry with backoff | Bounded (max 3, 1s apart) |
| Failure = UNKNOWN | Yes | Yes |
| Failure = FAIL | No (retries) | No (only contradictory data = FAIL) |

---

## 10. Admission Control — Sequenced Before Scheduling

### The Problem

Currently, S12 (Execution) is described as:
```
Worker Selection → Execution → (reliability guard wraps adapter)
```

This means the system picks a worker before checking whether the execution
should run at all. Under load, this wastes worker slots on requests that
should have been rejected earlier.

### The Fix

Admission control runs FIRST — before any worker is selected, before any
lease is acquired, before any budget is reserved.

```
S12 INTERNAL SEQUENCE:

1. ADMISSION       → ACCEPT / QUEUE / REJECT / DEGRADE
2. WORKER SELECT   → Choose worker (if ACCEPT)
3. LEASE           → Acquire lease on chosen worker
4. EXECUTE         → Run step through reliability guard
5. CHECKPOINT      → Save state after step
6. VERIFY          → Independent verification (S13)
7. COMMIT/DLQ      → Finalize or dead-letter
```

Steps 1-3 are the "admission and scheduling" phase. Steps 4-7 are the
"execution" phase. They are separated by a clear boundary.

### Admission Gates (in order)

Each gate is checked in sequence. The first gate that rejects stops evaluation.

| Gate | Check | Reject Reason |
|------|-------|---------------|
| 1 | Kill switch | `system_halted` |
| 2 | Tenant quota | `tenant_quota_exceeded` |
| 3 | Tenant suspended/deleted | `tenant_inactive` |
| 4 | Workspace paused | `workspace_inactive` |
| 5 | Execution mode allowed | `mode_not_allowed` |
| 6 | Provider allowed | `provider_blocked` |
| 7 | Worker capacity | `worker_at_capacity` |
| 8 | Provider circuit | `provider_circuit_open` |
| 9 | DB pool utilization | `db_pool_pressure` |
| 10 | Budget remaining | `budget_exhausted` |
| 11 | System load | `system_overloaded` |
| 12a | Tenant / workspace paused (`paused_until > NOW()`) | `tenant_paused` / `workspace_paused` |
| 13a | Tenant / workspace not yet active (`scheduled_activation_at > NOW()`) | `not_yet_active` |
| 16 | Operation quota precheck (read-only) | `quota_exhausted` (hard) — QUEUE (soft) |

> **Worker-management repair (RD-4, RD-5, RD-6; gate v10 C39):** gates 12a, 13a and 16 are phase-1 admission gates: they need no worker. **Evaluation order:** 1–6, 12a, 13a, 16, 8–11, then 7 last, so that a REJECT is never masked by a capacity QUEUE. Gate numbers are unchanged because C30 maps REJECTs by number. Worker-level checks (worker pause 12b, worker activation 13b, assignment 14, runtime/capability match 17) are **not** admission gates: admission runs before a worker is chosen, so they are eligibility filters in §13 (see §16.3). Gates 12a and 13a are decided at S12 entry for new runs only (§16.2); gate 16 consumes nothing (§16.4). All comparisons use database `NOW()` (I-019).

> **S12–S15 gate v9 repair (C30):** S12 maps a REJECT by `gate_failed`: gate 1 → kill-switch revocation path (run CANCELLED, `kill_switch_engaged`); gate 3 → revocation path (`authorization_revoked`); gate 10 → budget-exhaustion path (run CANCELLED, `budget_exhausted`); gate 7 is a QUEUE, never a REJECT; every other gate → remaining steps CANCELLED with `admission_rejected` and the run consolidated. Every decision is recorded as a ledger event.


### Admission Is Stateless

Admission checks are snapshots — they do not reserve resources.
Resource reservation (budget, lease) happens AFTER admission passes.

This means:
- Admission can be retried without cleanup (it leaves no state)
- Queue/Delay decisions don't hold resources
- Admission is safe to evaluate multiple times for the same request

### Re-entry Revalidation

Every path that resumes or retries an existing run — dead-letter retry,
checkpoint resume, lease reacquisition after expiry, reconciliation of
UNKNOWN — is a re-entry point.

Every re-entry point re-evaluates authorization and admission against live
state before any further side effect is initiated.

The run snapshot (ExecutionContext, IntentSpecification, FrozenBindingIdentity,
ExecutionManifest, policy and configuration versions) supplies reproducibility
only. It never supplies the authorization decision on re-entry.

If live authorization now denies what the snapshot permitted — grant revoked,
tenant suspended, connection deleted, capability retired, kill switch active —
the run terminates per the kill-switch/UNKNOWN contract. It does not resume.

> **S12–S15 gate v9 repair (C23, C30, C35):** Revalidation is performed by the read-only `LiveAuthorizationCheck` at the start of every step and immediately before every adapter call. It reuses S8's check functions from a shared library, never writes a `SafetyResult`, and fails closed when live state cannot be read. It also checks the frozen binding's and the credential's validity (register ADR-7). Probes and verification are observations, not side effects: they always run to settle uncertainty (and budget) and never lead to new adapter calls after revocation. On revocation, remaining steps are CANCELLED with `authorization_revoked`, `kill_switch_engaged`, `binding_invalid` or `credential_invalid`, and the run ends CANCELLED.


This rule binds regardless of how much of the run already completed.

#### Required Tests

| Test | Purpose |
|------|---------|
| `test_reentry_revalidates_authorization()` | Verifies that every re-entry path (dead-letter retry, checkpoint resume, lease reacquisition, UNKNOWN reconciliation) re-evaluates authorization against live state and terminates if authorization is now denied, regardless of snapshot state. |

---

## 11. AdmissionDecision Data Contract

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

### Admission States

| Status | Meaning | Next Action |
|--------|---------|-------------|
| `ACCEPT` | All gates passed | Proceed to worker selection |
| `QUEUE` | Capacity temporarily unavailable | Retry after `retry_after_ms` |
| `DELAY` | Backpressure detected | Wait `retry_after_ms`, then retry admission |
| `REJECT` | Permanently denied | Return error to user |
| `DEGRADE` | Accepted with reduced features | Proceed with `degraded_features` disabled |

> **Worker-management repair (RD-6; gate v10 C39):** new `reason` codes: `tenant_paused`, `workspace_paused`, `not_yet_active`, `quota_exhausted`. A soft-quota QUEUE puts upgrade guidance in `detail`; no field is added to this contract.

### Degrade Mode Rules

When `DEGRADE` is returned:

1. Non-critical features are disabled (analytics, non-essential notifications, post-processing)
2. Step timeouts are reduced by 50%
3. Tenant priority is enforced for queued work
4. When system load drops below 70% for 60s, degrade mode lifts

```python
DEGRADE_FEATURES = {
    "analytics": {"description": "Analytics event recording", "timeout_reduction": 0.5},
    "notifications": {"description": "Non-essential notifications", "timeout_reduction": 0.5},
    "post_processing": {"description": "Post-execution enrichment", "timeout_reduction": 0.5},
}
```

---

## 12. S12 Internal Sequence

### Full S12 Flow

> **S12–S15 gate v9 repair (C11):** This sketch is non-normative. It iterates `plan.steps` in list order (the normative order is topological by `depends_on`), and its `continue` on QUEUE and on lease failure would silently skip a step. The normative sequence is S12_S15_EXECUTION_GATE §8.

```python
class S12Execute:
    """S12 — Execution. Admit, schedule, execute, checkpoint, verify."""

    async def execute(self, plan: Plan, context: ExecutionContext) -> ExecutionResult:
        step_results = {}

        for step in plan.steps:
            # ── ADMISSION ───────────────────────────────────────
            admission = await self._admit(step, context)
            if admission.status == "REJECT":
                return self._build_rejected_result(plan, step, admission)
            elif admission.status == "QUEUE":
                await self._queue_for_retry(step, admission.retry_after_ms)
                continue
            elif admission.status == "DELAY":
                await asyncio.sleep(admission.retry_after_ms / 1000)
                admission = await self._admit(step, context)  # re-check

            # ── WORKER SELECTION ────────────────────────────────
            worker = self._select_worker(step, context, admission)
            if worker is None:
                return self._build_no_worker_result(plan, step)

            # ── LEASE ACQUISITION ───────────────────────────────
            lease = await self._acquire_lease(worker.worker_id, step, context)
            if lease is None:
                continue  # lease failed, retry step

            try:
                # ── EXECUTE ─────────────────────────────────────
                adapter_result = await self._execute_step(step, lease, context)

                # ── CHECKPOINT ──────────────────────────────────
                await self._checkpoint(step, adapter_result, lease)

                # ── VERIFY (S13) ────────────────────────────────
                if step.mutation in ("W", "D", "IRREVERSIBLE"):
                    verifier = self._get_verifier(step)  # built at S11
                    verification = await self._verify(verifier, adapter_result)
                    if verification.verdict == "FAIL":
                        adapter_result = KernelResult(
                            status="error",
                            error=f"Verification failed: {verification.observations[-1].error}",
                            kernel=step.kernel_op_id,
                        )
                    elif verification.verdict == "UNKNOWN":
                        adapter_result = KernelResult(
                            status="UNKNOWN",
                            error="Verification inconclusive",
                            kernel=step.kernel_op_id,
                        )

                step_results[step.id] = adapter_result

            finally:
                # ── LEASE RELEASE ───────────────────────────────
                await self._release_lease(lease)

        return self._consolidate(plan, step_results)
```

### Key Rule: Admission Does Not Reserve Resources

```python
async def _admit(self, step: Step, context: ExecutionContext) -> AdmissionDecision:
    """Evaluate admission gates. Stateless — no resources reserved."""
    decision = await self._admission_controller.admit(step, context)
    return decision
    # No budget reserved here. No lease acquired here.
    # Admission is a predicate: CAN we execute? Not: HAVE we reserved?
```

Budget reservation happens at step execution time, inside the reliability
guard's BudgetTracker. Lease acquisition happens after admission passes.

---

## 13. State Locality in Worker Selection

### The Problem

A naive scheduler picks the least-loaded worker. But for stateful
executions, this can be wrong:

```
Execution E123 has state at Worker A (checkpoints, context, cached data)
Worker A: 40% load
Worker B: 10% load

Naive scheduler ��� Worker B
Correct scheduler → Worker A (state locality outweighs 30% load difference)
```

### State Locality Score

When selecting a worker, the scheduler computes a composite score:

```python
@dataclass(frozen=True)
class WorkerSelectionScore:
    worker_id: str
    locality_score: float           # 0.0-1.0, higher = closer to state
    capacity_score: float           # 0.0-1.0, higher = more available
    health_score: float             # 0.0-1.0, higher = healthier
    queue_score: float              # 0.0-1.0, higher = less queued
    tenant_fairness_score: float    # 0.0-1.0, higher = fair share available
    cost_score: float               # 0.0-1.0, higher = lower cost
    composite: float                # Weighted sum
```

```python
class WorkerSelector:
    WEIGHTS = {
        "locality": 0.30,      # State locality is the strongest signal
        "capacity": 0.20,      # Available slots
        "health": 0.15,        # Circuit breaker, health score
        "queue": 0.15,         # Queue depth
        "tenant_fairness": 0.10, # Fair share
        "cost": 0.10,          # Provider cost
    }

    def select(self, candidates: list[WorkerDeployment],
               execution: ExecutionOwnership) -> WorkerDeployment | None:
        scored = []
        for worker in candidates:
            scores = WorkerSelectionScore(
                worker_id=worker.worker_id,
                locality_score=self._locality_score(worker, execution),
                capacity_score=self._capacity_score(worker),
                health_score=self._health_score(worker),
                queue_score=self._queue_score(worker),
                tenant_fairness_score=self._fairness_score(worker),
                cost_score=self._cost_score(worker),
                composite=self._composite(
                    locality=self._locality_score(worker, execution),
                    capacity=self._capacity_score(worker),
                    health=self._health_score(worker),
                    queue=self._queue_score(worker),
                    tenant_fairness=self._fairness_score(worker),
                    cost=self._cost_score(worker),
                ),
            )
            scored.append(scored)

        if not scored:
            return None
        return max(scored, key=lambda s: s.composite).worker_id

    def _locality_score(self, worker: WorkerDeployment,
                        execution: ExecutionOwnership) -> float:
        """Score based on whether this worker already holds execution state."""
        if execution.worker_id == worker.worker_id:
            # Same worker — likely recovering from crash, resume from checkpoint
            return 1.0
        elif execution.worker_version == worker.version_id:
            # Same version — compatible checkpoint format
            return 0.7
        elif execution.state_location == worker.host:
            # Same host — checkpoints accessible
            return 0.5
        return 0.0  # No locality advantage
```

### Worker-Eligibility Filters (before scoring)

> **Worker-management repair (RD-4, RD-7; gate v10 C39):** before locality scoring, candidates are filtered by pure predicates evaluated against live state and database `NOW()`:
>
> 1. worker or any of its groups paused (`paused_until > NOW()`) → filter reason `worker_paused` (12b);
> 2. worker not yet active (`scheduled_activation_at > NOW()`) → `worker_not_yet_active` (13b);
> 3. `assigned_user_id` set and ≠ `PrincipalChain.original_principal_id` → `not_assigned` (14); membership role `owner`/`admin` in the run's workspace, read live, bypasses 1–3;
> 4. `runtime_type` cannot run the step's frozen binding, or the step capability is not in `capability_profile` → `capability_mismatch` (17).
>
> If no candidate remains, the step is handled as `no_worker` (gate §8 step 2), and the ledger event records every filter reason that removed a candidate. Filters never choose an adapter: the adapter comes from the binding frozen at S5 (RD-9).

### Locality Is Advisory, Not Binding

Locality influences selection but does not override hard constraints:

```python
def select(self, ...):
    # 1. Filter to eligible workers (capacity, health, version compat)
    eligible = [w for w in candidates if self._is_eligible(w)]

    # 2. Score eligible workers
    scored = sorted(
        [self._score(w, execution) for w in eligible],
        key=lambda s: s.composite,
        reverse=True,
    )

    # 3. If top scorer is >= 0.5 locality, use it
    #    If top scorer is < 0.5, still use it — locality is advisory
    return scored[0].worker_id if scored else None
```

### When Locality Does Not Apply

Stateless executions (R-only, single-step, no checkpoint) have no locality
preference. The locality score is 0.0 for all workers, and selection falls
back to capacity + health + fairness.

---

## 14. ExecutionOwnership Data Contract

```python
@dataclass(frozen=True)
class ExecutionOwnership:
    """Tracks who owns an execution at every point in its lifecycle.

    Answers: Who is executing this? Where is its state? Can they proceed?
    """
    execution_id: str                 # UUID v4
    worker_id: str | None             # Current owner (None = not assigned)
    worker_version: str | None        # Version running this execution
    runtime_instance_id: str | None   # The Worker Runtime process (UUID generated at process start; FINAL_ARCHITECTURE §34)
    lease_id: str | None              # Current lease
    fencing_token: int | None         # Lease epoch — monotonic, never decreases
    checkpoint_sequence: int          # Last checkpoint number
    state_location: str | None        # Host where checkpoints reside
    owner_acquired_at: float | None   # When current owner acquired
    lease_expires_at: float | None    # When lease expires
```

### Database Schema

```sql
CREATE TABLE execution_ownership (
    execution_id TEXT PRIMARY KEY REFERENCES execution_runs(execution_id),
    worker_id TEXT REFERENCES workers(worker_id),
    worker_version TEXT REFERENCES worker_versions(version_id),
    runtime_instance_id TEXT,
    lease_id TEXT REFERENCES worker_leases(lease_id),
    fencing_token BIGINT NOT NULL DEFAULT 0,
    checkpoint_sequence INTEGER NOT NULL DEFAULT 0,
    state_location TEXT,
    owner_acquired_at REAL,
    lease_expires_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_exec_owner_worker ON execution_ownership(worker_id);
CREATE INDEX idx_exec_owner_lease ON execution_ownership(lease_id);
```

### Ownership Transfer Rules

When ownership transfers (failover, migration, drain):

1. New owner writes new row with new `fencing_token`
2. Old owner's `fencing_token` is now stale — it cannot commit state
3. Tokens come from the database sequence `fence_token_seq`, so a new owner's
   token is always strictly greater than the previous one, whichever worker it
   leases (gate C25). `execution_ownership.fencing_token` holds the execution's
   current token and is updated by compare-and-set in the same transaction as the
   lease change.
4. Every state commit for an execution goes through `fenced_write()`, which checks
   `execution_ownership.fencing_token = :holder_token AND runtime_instance_id =
   :runtime_instance_id` — if not, the commit is rejected (`FencedOut`) and the
   holder stops all work on that execution

> **S12–S15 gate v9 repair (C25):** Rules 3–4 previously named `worker_leases.fence_token` as authority and checked `worker.lease_epoch` per worker. With per-worker counters a takeover by a different worker could produce a smaller token and fail the strictly-greater check below; with a per-worker check, capacity above 1 would fence out concurrent executions.


```python
class OwnershipManager:
    async def transfer(self, execution_id: str, new_worker_id: str,
                       new_lease_id: str, new_fence_token: int) -> None:
        """Transfer execution ownership. Old owner is immediately invalidated."""
        async with self._db.transaction() as tx:
            # Get current fencing token
            current = await tx.execute(
                "SELECT fencing_token FROM execution_ownership WHERE execution_id = $1",
                execution_id,
            ).fetchone()

            # Verify new token is strictly greater (monotonic)
            if new_fence_token <= current.fencing_token:
                raise ConcurrencyError(
                    f"New fence token {new_fence_token} <= current {current.fencing_token}"
                )

            # Transfer
            await tx.execute(
                """INSERT INTO execution_ownership
                   (execution_id, worker_id, worker_version, runtime_instance_id,
                    lease_id, fencing_token, checkpoint_sequence, state_location,
                    owner_acquired_at, lease_expires_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6,
                           (SELECT checkpoint_sequence FROM execution_ownership
                            WHERE execution_id = $1),
                           (SELECT state_location FROM execution_ownership
                            WHERE execution_id = $1),
                           NOW(), $7, NOW())
                   ON CONFLICT (execution_id) DO UPDATE SET
                       worker_id = EXCLUDED.worker_id,
                       worker_version = EXCLUDED.worker_version,
                       runtime_instance_id = EXCLUDED.runtime_instance_id,
                       lease_id = EXCLUDED.lease_id,
                       fencing_token = EXCLUDED.fencing_token,
                       updated_at = EXCLUDED.updated_at""",
                execution_id, new_worker_id, None, None,
                new_lease_id, new_fence_token, None,
            )
```

---

## 15. Implementation Rules

### Rule 1: No WorkerIdentity Mutation After Creation

`WorkerIdentity.capability_profile` is set at registration and never changes.
If capabilities change, a new WorkerIdentity is registered. This prevents
a running worker from silently gaining or losing capabilities mid-execution.

> **Worker-management repair (RD-4, RD-5):** the rule covers `capability_profile`, `worker_class` and `tenant_id`. The management columns of §16.1 are mutable; changes apply to leases acquired afterwards (I-017).

### Rule 2: No WorkerVersion Mutation After Registration

`WorkerVersion.artifact_hash` is immutable. A new deployment creates a new
WorkerVersion row. This ensures every execution can prove exactly which
code version produced its result.

### Rule 3: Exactly One CURRENT Version Per WorkerIdentity

The scheduler queries:
```sql
SELECT version_id FROM worker_versions
 WHERE worker_id = :wid AND state = 'CURRENT'
```
This must return exactly one row. If zero: no worker available.
If more than one: data integrity error (should never happen with
proper state validation).

### Rule 4: Verification Is Never Skipped for Mutations

S13 verification is mandatory for W, D, and IRREVERSIBLE mutations.
The only exception is when the adapter returns `UNKNOWN` — in that case,
the verification step still runs but the verdict is moot (the step is
already in UNKNOWN state). The verification result is still recorded for
audit purposes.

### Rule 5: Admission Is Always First

No worker is selected, no lease acquired, no budget reserved before
admission passes. This is enforced by code structure: the admission
check is the first operation in S12, before any resource acquisition.

### Rule 6: Locality Is Advisory

State locality influences worker selection but never overrides hard
constraints (capacity, health, version compatibility). A healthy worker
with no locality is always preferred over an unhealthy worker with
perfect locality.

### Rule 7: Fencing Token Monotonicity

Fencing tokens are strictly monotonically increasing. A stale owner
with an old token cannot commit any state change for the execution.

> **Worker-management repair (review E5; gate C25):** the former text said the authority was the maximum `worker_leases.fence_token` per worker, which C25 superseded. Tokens are issued by the database sequence `fence_token_seq` on every lease acquisition and renewal. `worker_leases.fence_token` still records the token issued with each lease, and `workers.lease_epoch` records the newest token issued to the worker, but the write fence is checked **per execution** against `execution_ownership.fencing_token` (see §14 ownership transfer: a new owner's token must be strictly greater than the stored one).

---

## 16. Worker Management Settings

> **Worker-management repair (gate v10 C39; RD-1…RD-8, RD-13):** new section. Source: `WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md` as corrected by `WORKER_MGMT_SPEC_REVIEW.md`. DATABASE.md remains authoritative for DDL; the column lists here are the contract.

### 16.1 Management columns on `workers` (additive)

| Column | Type | Default | Scope |
|---|---|---|---|
| `settings` | JSONB | `'{}'` | In scope (read by S12 only; contract in IDENTITY §5) |
| `assigned_user_id` | TEXT NULL, FK `users(user_id)` | NULL | In scope (filter 14) |
| `paused_until` | TIMESTAMPTZ NULL | NULL | In scope (filter 12b) |
| `scheduled_activation_at` | TIMESTAMPTZ NULL | NULL | In scope (filter 13b) |
| `runtime_type` | TEXT NOT NULL, CHECK in (llm, rules, vision, browser, rpa, data, rag, code, human) | `'llm'` | In scope (filter 17) |
| `max_sub_agents`, `parent_worker_id` (TEXT FK), `depth_level` | — | — | **Deferred** (spawning, RD-13) |

Tenant and workspace `paused_until` / `scheduled_activation_at` are typed `TIMESTAMPTZ NULL` columns on `tenants` and `workspaces`, not keys inside their TEXT `settings` JSON (review A-9). These columns are mutable management state (invariant 5), are read only by S12 admission and worker selection, are never read by S0–S11, and are never part of the ExecutionManifest.

### 16.2 Phase-1 admission additions (no worker needed)

Gates 12a (tenant/workspace paused) and 13a (tenant/workspace not yet active) are evaluated at **S12 entry** (gate §7.1): a new run is denied with the specific reason and nothing is written. A pause or activation time set while a run is RUNNING does **not** cancel its steps (drain semantics, RD-5). The hard stop remains the kill switch (C23).

Gate 16 is a read-only quota precheck, evaluated with the other gates before each step. It never consumes quota.

### 16.3 Phase-2 worker-eligibility filters

Defined in §13 "Worker-Eligibility Filters". Filters 12b, 13b and 14 apply to **new leases** only; a lease already held is never revoked by a pause (RD-5). Admin bypass: membership role `owner` or `admin` in the run's workspace, read live (RD-7). Filter 14 compares against `PrincipalChain.original_principal_id`, so worker-to-worker delegation keeps the human's assignment.

### 16.4 Operation quota

Table `operation_quotas` (tenant_id TEXT NOT NULL + RLS; workspace_id and worker_id TEXT NULL; `resource_type`; `period_start`, `period_end` TIMESTAMPTZ; `limit_value`, `used_count` INTEGER with `CHECK (used_count >= 0 AND limit_value >= 0)`; `is_hard`; `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)`).

**Consumption (RD-6):** once per run, inside the durable-admission transaction (gate §7.2), after the `(tenant_id, request_id)` duplicate check. Every applicable level is updated in the fixed order tenant → workspace → worker:

```sql
UPDATE operation_quotas
   SET used_count = used_count + 1
 WHERE quota_id = :quota_id
   AND period_start <= NOW() AND period_end > NOW()
   AND used_count < limit_value
RETURNING quota_id;
```

Zero rows at any level rolls the whole transaction back: hard → DENY `quota_exhausted` (nothing written), soft → QUEUE with upgrade text in `detail`. **Refund:** only when the run ends CANCELLED with no step COMPLETED; the refund is a ledger event. Invariant **I17** (gate §17): `used_count ≤ limit_value` for every hard quota.

### 16.5 Timestamp precedence

`effective_paused_until = GREATEST(tenant, workspace, every group of the worker, worker)` with NULL meaning "not paused"; the same rule applies to `scheduled_activation_at`. Tenant and workspace values are decided in phase 1, group and worker values in phase 2. Time is database `NOW()` (I-019).

### 16.6 Deferred (post-S15; recorded in gate §14)

Sub-agent spawning (G15 becomes a check inside `spawn_child_worker()`, not an admission gate; parent row locked `FOR UPDATE`; depth check `depth_level + 1 > max_depth`; only non-`TERMINATED` children counted; child capabilities and grants ⊆ parent's), `worker_spawn_audit`, worker groups, config versions (reusing `ConfigurationVersion`), state-change webhooks (secret via `CredentialProvider`, dispatch via outbox), batch (RD-12) and replanning (RD-11). Every deferred table carries `tenant_id TEXT NOT NULL` + RLS when it lands (RD-3).

### 16.7 Reason codes

| Code | Where | Outcome |
|---|---|---|
| `tenant_paused`, `workspace_paused`, `not_yet_active` | S12 entry (12a, 13a) | DENY, nothing written |
| `quota_exhausted` | S12 entry (consumption) | DENY (hard) / QUEUE (soft) |
| `worker_paused`, `worker_not_yet_active`, `not_assigned`, `capability_mismatch` | Filter reasons in the `no_worker` ledger event | Step → `no_worker` path |

---

## Document Relationships

| This Document | Extends | Extended By |
|---------------|---------|-------------|
| Worker Identity Lifecycle | IDENTITY_AND_TENANCY.md (Worker Lifecycle) | DATABASE.md (worker table) |
| Worker Version Lifecycle | NEW — no prior version state machine | PIPELINE_STAGES.md (S12 worker assignment) |
| Independent Verification | PIPELINE_STAGES.md (S13) | DATA_CONTRACTS.md (VerificationResult) |
| Admission Control | RELIABILITY.md (Backpressure) | PIPELINE_STAGES.md (S12 internal sequence) |
| State Locality | FINAL_ARCHITECTURE.md (Scheduler) | PIPELINE_STAGES.md (S12 worker selection) |
| Worker Management Settings (§16) | WORKER_MANAGEMENT_AND_EVOLUTION_SPEC.md; S12_S15_EXECUTION_GATE.md C39 | DATABASE.md (columns, `operation_quotas`); IDENTITY_AND_TENANCY.md §5 (settings contract) |
