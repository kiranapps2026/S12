# Event Gateway & Event Router — Data Contracts

**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §6a Event Gateway & External Event Routing, §12 Durable Execution Kernel (S0 entry), §23 Multi-Agent Communication (outbox/inbox pattern), §27 Observability & Tracing (trace_id, correlation). *(section numbers corrected in audit round 2, D1)*  [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — §28 OutboxEvent, §30 OutboxRecord/InboxRecord, §31 EventIdentity. [IDENTITY_AND_TENANCY.md](IDENTITY_AND_TENANCY.md) — §8 Authorization Chain (tenant from auth context, never from payload), §9 Time/Clock (server-authoritative, 5-minute skew tolerance). [PIPELINE_STAGES.md](PIPELINE_STAGES.md) — S0 Entry (generates trace_id, request_id, execution_id), S8 Safety Gate (8 deterministic checks). [SECURITY.md](SECURITY.md) — §3 Input Validation (signature validation, replay protection), §5 Secret Handling (per-tenant webhook secrets). [DATABASE.md](DATABASE.md) — RLS policies, event_log table, canonical roles. [RELIABILITY.md](RELIABILITY.md) — 5-layer reliability guard, circuit breaker, outbox atomicity.
**Status**: DESIGN_PROPOSED, NOT YET LOCKED
**Worker-management update (2026-09-29)**: §14.7–§14.8 added per gate v10 C39 and rulings RD-4, RD-5, RD-10 (`WORKER_MGMT_SPEC_REVIEW.md` Part E).
**Purpose**: Define the event ingress layer that normalizes all external events (webhooks, schedules, MCP, API) into the existing S0–S15 pipeline. Events are a fifth activation mode alongside human request, schedule, API, and internal trigger.

---

## Table of Contents

1. [Architecture Position](#1-architecture-position)
2. [Activation Mode: EVENT_DRIVEN](#2-activation-mode-event_driven)
3. [EventEnvelope — Canonical Event Representation](#3-eventenvelope--canonical-event-representation)
4. [EventGateway — Ingress Interface](#4-eventgateway--ingress-interface)
5. [EventRouter — Subscription Matching & Execution Creation](#5-eventrouter--subscription-matching--execution-creation)
6. [WorkerSubscription — Durable Subscription Contract](#6-workersubscription--durable-subscription-contract)
7. [EventCorrelator — Dedup, Windowing, Consolidation](#7-eventcorrelator--dedup-windowing-consolidation)
8. [EventEnvelope State Machine](#8-eventenvelope-state-machine)
9. [WorkerSubscription State Machine](#9-workersubscription-state-machine)
10. [Database Tables](#10-database-tables)
11. [Webhook Credential Management](#11-webhook-credential-management)
12. [Integration with Existing Pipeline](#12-integration-with-existing-pipeline)
13. [Security Constraints](#13-security-constraints)
14. [Implementation Rules](#14-implementation-rules)

---

## 1. Architecture Position

The Event Gateway is an **ingress/control-plane component**. It does NOT create a second execution path.

```
                 ┌── Human Request
                 ├── Schedule / Cron
                 ├── Webhook
                 ├── API Event
                 ├── MCP Event
                 └── Internal Event
                          │
                    EVENT INGRESS
                          │
             Authenticate + Validate
                          │
                EventEnvelope
                          │
             Correlate / Deduplicate
                          │
                  Worker Subscription
                          │
                    Worker Activation
                          │
                    ┌───────▼───────┐
                    │   S0 — Entry  │ ← Existing pipeline entry point
                    └───────┬───────┘
                            │
                     S1 → S2 → ... → S15
                            │
                    Existing resolution chain:
                    Intent → Capability → Kernel Op
                    → Risk → FrozenBindingIdentity
                    → Plan → Execute → Verify
```

**Critical invariant**: After the Event Gateway produces an `EventEnvelope`, execution enters S0 and follows the EXACT same path as every other activation mode. The Event Gateway does not bypass S8 Safety Gate, does not pre-select providers, and does not create alternate resolution paths.

---

## 2. Activation Mode: EVENT_DRIVEN

`EVENT_DRIVEN` is a fifth activation mode alongside `HUMAN`, `SCHEDULE`, `API`, and `INTERNAL`.

**Definition in PIPELINE_STAGES.md §2 (S0 Entry)**:

| Activation Mode | Source | S0 Input |
|-----------------|--------|----------|
| `HUMAN` | Terminal chat message | Raw text |
| `SCHEDULE` | Cron trigger | Schedule context |
| `API` | Direct API call | API payload |
| `INTERNAL` | System event | Internal context |
| `EVENT_DRIVEN` | External event (webhook, MCP, etc.) | `EventEnvelope` |

S0 Entry receives an `EventEnvelope` instead of a raw message. The only difference in S0 processing is:

| Field | HUMAN/SCHEDULE/API | EVENT_DRIVEN |
|-------|-------------------|--------------|
| `trace_id` | Generated | Generated (same) |
| `request_id` | Generated | Generated (same) |
| `event_id` | None | Set from `EventEnvelope.event_id` |
| `correlation_id` | From conversation | From `EventEnvelope.correlation_id` |
| `source` | "human"/"schedule"/"api" | From `EventEnvelope.source` |
| `activation_mode` | Implicit | `"event_driven"` |
| `context_snapshot` | User message text | `EventEnvelope.payload_ref` |

All other S0 actions are identical: generate IDs, create immutable `ExecutionContext`, proceed to S1.

---

## 3. EventEnvelope — Canonical Event Representation

The `EventEnvelope` is the normalized internal representation of any external event. It is immutable after creation.

```python
from dataclasses import dataclass
from enum import StrEnum

class EventSource(StrEnum):
    """Where the event originated."""
    WEBHOOK = "webhook"
    SCHEDULE = "schedule"
    MCP = "mcp"
    API = "api"
    INTERNAL = "internal"

class EventType(StrEnum):
    """Event type categories. Extensible per tenant."""
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    STEP_COMPLETED = "step.completed"
    WEBHOOK_GHL_CONTACT_CREATED = "webhook.ghl.contact_created"
    WEBHOOK_GHL_CONTACT_UPDATED = "webhook.ghl.contact_updated"
    WEBHOOK_STRIPE_PAYMENT_SUCCEEDED = "webhook.stripe.payment_succeeded"
    SCHEDULE_DAILY_SYNC = "schedule.daily_sync"
    SCHEDULE_WEEKLY_REPORT = "schedule.weekly_report"
    MCP_TOOL_CALL = "mcp.tool_call"
    MCP_RESOURCE_UPDATED = "mcp.resource_updated"


@dataclass(frozen=True)
class EventEnvelope:
    """Immutable normalized event representation.

    Created by EventGateway after authentication and validation.
    Consumed by S0 Entry to create ExecutionContext.
    Never modified after creation.
    """
    # ─── Identity ──────────────────────────────────────────────────────────
    event_id: str                  # UUID v4 — globally unique event identifier
    event_type: str                # EventType value or tenant-defined string
    source: str                    # EventSource value

    # ─── Origin ────────────────────────────────────────────────────────────
    source_system: str             # Originating system ("ghl", "stripe", "cron", "mcp.filesystem")
    tenant_id: str                 # From authentication context — NEVER from payload
    workspace_id: str              # From authentication context — NEVER from payload

    # ─── Timing ────────────────────────────────────────────────────────────
    occurred_at: float             # When the event actually occurred (source timestamp)
    received_at: float             # When the gateway received it (server-authoritative)

    # ─── Payload ───────────────────────────────────────────────────────────
    payload_ref: str               # Reference to stored payload: "pg:event_log.{event_id}"
    payload_size_bytes: int        # Size for billing/monitoring
    schema_version: str            # Schema version for payload deserialization

    # ─── Correlation ───────────────────────────────────────────────────────
    correlation_id: str            # trace_id — groups related events/executions
    idempotency_key: str           # For deduplication: "{source}:{source_event_id}"

    # ─── Authentication ────────────────────────────────────────────────────
    auth_method: str               # "hmac_sha256", "api_key", "bearer", "mcp_internal"
    auth_principal: str            # Authenticated principal (connection_id, user_id, or mcp_server_id)

    # ─── Processing State ──────────────────────────────────────────────────
    processing_status: str         # "received" → "validated" → "routed" → "processed"
    processing_execution_id: str | None  # execution_id if/when execution is created
```

### EventEnvelope Invariants

1. `tenant_id` comes from authentication context — it is NEVER extracted from `payload`
2. `event_id` is UUID v4, generated by the gateway, never from the source
3. `correlation_id` is the same as `trace_id` once S0 creates the execution
4. `idempotency_key` is computed as `{source}:{source_event_id}` — the same event from the same source is always deduplicated
5. `occurred_at` is the source's timestamp; `received_at` is server-authoritative (RELIABILITY.md: no worker-local clock in distributed decisions)
6. `payload_ref` is always set — the gateway stores the raw payload before any processing
7. `processing_status` transitions monotonically forward — never backward
8. `auth_principal` identifies WHO triggered this, not just WHAT system

### Relationship to Existing Contracts

| Existing contract | Relationship |
|-------------------|-------------|
| `OutboxEvent` (DATA_CONTRACTS §28) | `EventEnvelope` is the inbound counterpart. `OutboxEvent` is system-generated and outbound. `EventEnvelope` is externally-generated and inbound. Both share `event_id`, `event_type`, `correlation_id`, `sequence_number` concepts. |
| `EventIdentity` (DATA_CONTRACTS §29) | `EventEnvelope.event_id` IS the `EventIdentity.event_id`. `EventEnvelope.correlation_id` IS the `EventIdentity.correlation_id`. |
| `OutboxRecord` (DATA_CONTRACTS §31) | `EventEnvelope` maps to an `OutboxRecord` for internal event delivery after processing. |
| `InboxRecord` (DATA_CONTRACTS §31) | `EventEnvelope` is conceptually similar to `InboxRecord` but for external events, not internal A2A messages. |
| `ExecutionContext` (DATA_CONTRACTS §2) | S0 creates `ExecutionContext` from `EventEnvelope`. `EventEnvelope.event_id` → `ExecutionContext.task_id`. `EventEnvelope.correlation_id` → `ExecutionContext.trace_id`. |

---

## 4. EventGateway — Ingress Interface

The EventGateway is the single entry point for all external events. It authenticates, validates, normalizes, deduplicates, and hands off to the EventRouter.

```python
class EventGateway:
    """Single ingress point for all external events.

    Responsibilities:
    1. Authenticate the incoming request
    2. Validate the event structure and signature
    3. Check replay protection (timestamp + idempotency)
    4. Store raw payload durably
    5. Create immutable EventEnvelope
    6. Pass to EventRouter for subscription matching

    The gateway is STATELESS between events. All state is in PostgreSQL.
    """

    async def receive_webhook(
        self,
        raw_request: bytes,
        signature_header: str | None,
        timestamp_header: str | None,
    ) -> EventEnvelope:
        """Receive and process an incoming webhook event."""

    async def receive_schedule(
        self,
        schedule_id: str,
        triggered_at: float,
    ) -> EventEnvelope:
        """Receive a scheduled/cron trigger."""

    async def receive_mcp(
        self,
        mcp_server_id: str,
        tool_name: str,
        arguments: dict,
    ) -> EventEnvelope:
        """Receive an MCP tool call event."""

    async def receive_api(
        self,
        api_key_id: str,
        payload: dict,
    ) -> EventEnvelope:
        """Receive a direct API event."""


class EventGatewayAuthenticator:
    """Authenticates event sources and extracts tenant/workspace context.

    Tenant identity comes from authentication context ONLY.
    The event payload is NEVER used for tenant determination.
    """

    async def authenticate_webhook(
        self,
        source_system: str,
        signature: str,
        timestamp: str,
        raw_body: bytes,
    ) -> AuthContext:
        """Validate HMAC signature and extract tenant context."""

    async def authenticate_api_key(
        self,
        api_key_id: str,
    ) -> AuthContext:
        """Validate API key and extract tenant context."""

    async def authenticate_mcp_internal(
        self,
        mcp_server_id: str,
    ) -> AuthContext:
        """Validate internal MCP server identity."""


class EventGatewayValidator:
    """Validates event structure, schema, and replay protection."""

    async def validate_schema(
        self,
        event_type: str,
        payload: dict,
        schema_version: str,
    ) -> ValidationResult:
        """Validate payload against registered event schema."""

    async def check_replay_protection(
        self,
        idempotency_key: str,
        timestamp: float,
    ) -> ReplayCheck:
        """Check idempotency key + timestamp for replay attacks.

        Reject if:
        - idempotency_key already processed (duplicate)
        - timestamp is more than 5 minutes from server time (replay)
        """

    async def check_tenant_active(
        self,
        tenant_id: str,
    ) -> bool:
        """Check tenant is active (not kill-switched). Mirrors S8 G4a."""


class EventGatewayStorage:
    """Stores raw event payload durably before any processing."""

    async def store_payload(
        self,
        event_id: str,
        raw_payload: bytes,
    ) -> str:
        """Store raw payload and return payload_ref.

        Returns "pg:event_log.{event_id}" for PostgreSQL storage
        or "s3:..." for large payloads.
        """

    async def mark_envelope_status(
        self,
        event_id: str,
        status: str,
        execution_id: str | None = None,
    ) -> None:
        """Update processing_status in event_log table."""
```

### Gateway Processing Flow

```
HTTP POST /webhook/{source_system}
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. AUTHENTICATE                                                      │
│    - Extract HMAC signature from header                              │
│    - Look up tenant's webhook secret from provider_tokens            │
│    - Verify signature: HMAC-SHA256(secret, raw_body + timestamp)     │
│    - Extract tenant_id, workspace_id from credential                 │
│    - FAIL → 401 Unauthorized                                         │
├─────────────────────────────────────────────────────────────────────┤
│ 2. VALIDATE                                                          │
│    - Check timestamp: |server_time - event_time| < 300s (5 min)      │
│    - Check idempotency_key: already processed? → return cached       │
│    - Validate payload against event schema                           │
│    - FAIL → 400 Bad Request (with reason)                           │
├─────────────────────────────────────────────────────────────────────┤
│ 3. STORE                                                             │
│    - Store raw payload in event_log table                            │
│    - Atomic with envelope creation                                   │
├─────────────────────────────────────────────────────────────────────┤
│ 4. ENVELOPE                                                          │
│    - Create immutable EventEnvelope                                  │
│    - Set tenant_id from auth context (NOT payload)                   │
│    - Set processing_status = "received"                              │
├─────────────────────────────────────────────────────────────────────┤
│ 5. ROUTE                                                             │
│    - Pass EventEnvelope to EventRouter                               │
│    - Return immediately (async processing)                           │
│    - HTTP 202 Accepted                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Gateway Constraints

1. The gateway NEVER executes business logic
2. The gateway NEVER selects providers or adapters
3. The gateway NEVER calls LLMs
4. The gateway returns 202 Accepted immediately after queuing — it does not wait for execution
5. All failures are logged to `event_log` with status = "failed"
6. The gateway is stateless between events — all state in PostgreSQL

---

## 5. EventRouter — Subscription Matching & Execution Creation

The EventRouter receives validated `EventEnvelope` objects and matches them against worker subscriptions.

```python
class EventRouter:
    """Routes validated events to worker subscriptions.

    Responsibilities:
    1. Match event against active worker subscriptions
    2. Apply correlation/consolidation (EventCorrelator)
    3. Create S0 execution entry via existing execution engine
    4. Update EventEnvelope.processing_status

    The router does NOT select providers, adapters, or capabilities.
    It activates workers — the worker's normal execution flow handles everything else.
    """

    async def route(self, envelope: EventEnvelope) -> RoutingResult:
        """Route an event to matching worker(s)."""

    async def match_subscriptions(
        self,
        envelope: EventEnvelope,
    ) -> list[WorkerSubscription]:
        """Find all active subscriptions matching this event."""

    async def activate_worker(
        self,
        subscription: WorkerSubscription,
        envelope: EventEnvelope,
    ) -> ExecutionActivation:
        """Activate a worker for an event. Creates S0 execution entry."""


class RoutingResult:
    """Result of routing an event."""
    action: str              # "activated", "queued", "dropped", "failed"
    matched_subscriptions: list[str]  # subscription_ids that matched
    execution_id: str | None  # Set if action == "activated"
    reason: str | None       # Explanation for non-activated outcomes
```

### Router Processing Flow

```
EventEnvelope (from gateway)
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. CHECK CIRCUIT BREAKER                                             │
│    - Check tenant circuit breaker state                             │
│    - If OPEN: buffer event in outbox, return "queued"               │
├─────────────────────────────────────────────────────────────────────┤
│ 2. CORRELATE                                                        │
│    - Pass to EventCorrelator for dedup/consolidation                 │
│    - If consolidated: merge with existing batch                      │
│    - If duplicate: mark processed, return "dropped"                  │
├─────────────────────────────────────────────────────────────────────┤
│ 3. MATCH SUBSCRIPTIONS                                              │
│    - Query event_subscriptions for matching event_type + tenant      │
│    - Filter by subscription.filter (JSONB conditions)                │
│    - Filter by worker state (ACTIVE only, not DRAINING)              │
│    - Filter by worker capacity (current_load < capacity)             │
│    - If no match: mark event "no_match", return "dropped"            │
├─────────────────────────────────────────────────────────────────────┤
│ 4. ACTIVATE                                                         │
│    - Select worker (scheduler decision if multiple match)            │
│    - Create execution via S0 with activation_mode = "event_driven"   │
│    - Set EventEnvelope.processing_execution_id = execution_id        │
│    - Set EventEnvelope.processing_status = "routed"                  │
│    - Return "activated"                                              │
└─────────────────────────────────────────────────────────────────────┘
```

### Router Constraints

1. The router does NOT call S1–S15 — it creates the S0 entry point and the existing pipeline takes over
2. The router does NOT select providers or adapters — that is S5's job
3. The router does NOT modify the `EventEnvelope` after creation — it only updates `processing_status` and `processing_execution_id`
4. Multiple subscriptions can match one event — each gets its own execution
5. Subscription matching is deterministic — same event + same subscriptions = same result

---

## 6. WorkerSubscription — Durable Subscription Contract

A `WorkerSubscription` declares which event types/conditions can activate a worker. It is durable — worker crashes do not lose subscriptions.

```python
@dataclass(frozen=True)
class WorkerSubscription:
    """Durable worker subscription. Persisted in DB.

    A subscription declares: "When events of type X match condition Y,
    activate this worker to execute capability Z."

    Subscriptions survive worker crashes and restarts.
    They are NOT ephemeral — they are first-class durable state.
    """
    subscription_id: str           # UUID v4 — immutable
    worker_id: str                 # Worker this subscription belongs to
    tenant_id: str                 # Isolation boundary
    workspace_id: str              # Workspace scope

    # ─── Event Matching ───────────────────────────────────────────────────
    event_types: list[str]         # EventType values or patterns ("webhook.ghl.*")
    source_systems: list[str]      # Source filter (["ghl", "stripe"]) or [] for all
    filter: dict | None            # JSONB conditions on payload fields

    # ─── Activation ───────────────────────────────────────────────────────
    capability_id: str             # Capability to execute when matched
    priority: int                  # Lower = higher priority
    max_concurrent: int            # Max concurrent executions from this subscription (default: 1)

    # ─── State ────────────────────────────────────────────────────────────
    is_active: bool                # False = paused, not matching
    matched_count: int             # Total matches (monitoring)
    last_matched_at: float | None  # Last match timestamp

    # ─── Lifecycle ────────────────────────────────────────────────────────
    created_at: float
    updated_at: float
    created_by: str                # user_id who created this subscription
```

### Subscription Matching Algorithm

```
EventEnvelope arrives
    │
    ▼
For each active WorkerSubscription where:
    │
    ├── event_types matches event_type
    │   (exact match OR wildcard pattern match)
    │
    ├── source_systems is empty OR source in source_systems
    │
    ├── subscription.filter matches envelope payload fields
    │   (JSONB containment: payload @> filter)
    │
    ├── Worker state == ACTIVE
    │
    ├── Worker.current_load < Worker.capacity
    │
    ├── Subscription matching_count < Subscription.max_concurrent
    │
    ▼
Match found → activate worker → create execution via S0
No match → event marked "no_active_subscription" → dropped
```

---

## 7. EventCorrelator — Dedup, Windowing, Consolidation

The `EventCorrelator` processes raw events before expensive LLM reasoning. It reduces noise, deduplicates, and batches related events.

```python
class EventCorrelator:
    """Correlates, deduplicates, and consolidates events before routing.

    Runs between gateway validation and router subscription matching.
    Reduces event volume and noise before reaching the execution pipeline.
    """

    async def process(self, envelope: EventEnvelope) -> CorrelatedEvent:
        """Process an event through correlation pipeline."""

    async def deduplicate(
        self,
        envelope: EventEnvelope,
    ) -> DedupResult:
        """Check if this event is a duplicate.

        Uses idempotency_key for exact duplicates.
        Uses event_type + payload hash for near-duplicates within window.
        """

    async def consolidate(
        self,
        envelope: EventEnvelope,
        window_ms: int,
    ) -> ConsolidationResult:
        """Group related events within a time window.

        Example: 50 "contact_created" events in 30s → consolidated batch
        """

    async def filter_noise(
        self,
        envelope: EventEnvelope,
    ) -> FilterResult:
        """Remove noise events (heartbeats, health checks, etc.)"""


class CorrelatedEvent:
    """Output of correlation processing."""
    envelope: EventEnvelope       # Original (or consolidated) envelope
    is_duplicate: bool            # True if exact duplicate
    is_consolidated: bool         # True if merged with other events
    consolidated_with: list[str]  # event_ids this was merged with
    batch_payload: dict | None    # Consolidated payload (if batched)
    correlation_window: int | None  # Window size used (ms)
```

### Correlation Rules

| Rule | Description | Default |
|------|-------------|---------|
| Exact dedup | Same `idempotency_key` already processed → discard | Always |
| Time-window consolidation | Same `event_type` + same `source_system` within window → batch | Configurable per event_type |
| Noise filter | Event type in noise list → discard | Configurable per tenant |
| Priority | HIGH events bypass consolidation; LOW events may be dropped under load | event_type-dependent |

### Consolidation Output

When events are consolidated, the resulting `EventEnvelope.payload` contains the batch:

```python
{
    "batch": True,
    "event_count": 50,
    "first_event_id": "uuid-1",
    "last_event_id": "uuid-50",
    "first_occurred_at": 1700000000.0,
    "last_occurred_at": 1700000030.0,
    "items": [ ... 50 event payloads ... ],
    "summary": "50 new contacts created in batch — likely import"
}
```

The LLM at S2 sees the consolidated batch as a single input, reducing token consumption and improving context.

---

## 8. EventEnvelope State Machine

The `EventEnvelope.processing_status` field transitions through a defined state machine:

```
RECEIVED
    │  (gateway authenticated and stored event)
    ▼
VALIDATED
    │  (schema, signature, timestamp, replay check passed)
    ▼
DEDUPLICATED
    │  (correlator checked for duplicates)
    ▼
ROUTED
    │  (router matched subscription, created execution)
    ▼
PROCESSED
    │  (execution reached terminal state)
    ▼
CLOSED
```

### State Definitions

| State | Meaning | Transitions |
|-------|---------|-------------|
| `received` | Raw event stored, authentication pending | → validated, → failed |
| `validated` | Authentication, schema, replay check passed | → deduplicated, → failed |
| `deduplicated` | Dedup check complete | → routed, → dropped |
| `routed` | Matched subscription, execution created | → processed |
| `processed` | Execution reached terminal state | → closed |
| `dropped` | No subscription matched or duplicate | → closed |
| `failed` | Validation/auth/storage failure | → closed |
| `closed` | Terminal state — no further transitions | — |

### Illegal Transitions

| From | To | Reason |
|------|----|--------|
| Any | received | Cannot revert to received |
| closed | Any | Terminal state |
| routed | dropped | Once routed, execution owns the event |
| processed | dropped | Execution already created |

---

## 9. WorkerSubscription State Machine

```
REGISTERED
    │  (subscription created by user/system)
    ▼
ACTIVE
    │  (matching events activate worker)
    │
    ├── (paused by user) ──► SUSPENDED
    │                          │
    │                          │ (resumed) ──► ACTIVE
    │
    ├── (tenant kill-switch) ──► SUSPENDED
    │
    └── (worker terminates) ──► ORPHANED
                                 │
                                 │ (worker re-registered, subscription transferred)
                                 ▼
                               ACTIVE (new worker)
```

### State Definitions

| State | Meaning | Matches Events |
|-------|---------|----------------|
| `registered` | Created, not yet active | No |
| `active` | Active, matching events | Yes |
| `suspended` | Paused by user or tenant policy | No |
| `orphaned` | Worker no longer exists | No |

---

## 10. Database Tables

### 10.1 event_log

Stores every event that passes through the gateway, regardless of processing outcome.

```sql
CREATE TABLE event_log (
    event_id TEXT PRIMARY KEY,           -- UUID v4
    tenant_id TEXT NOT NULL,             -- From auth context
    workspace_id TEXT NOT NULL,          -- From auth context
    event_type TEXT NOT NULL,            -- EventType or tenant-defined
    source TEXT NOT NULL,                -- EventSource value
    source_system TEXT NOT NULL,         -- "ghl", "stripe", "cron", etc.
    source_event_id TEXT,                -- Source's own event ID (for dedup)
    payload_ref TEXT NOT NULL,           -- "pg:event_log.{event_id}"
    payload_size_bytes INTEGER,          -- For billing
    schema_version TEXT NOT NULL,        -- Payload schema version
    correlation_id TEXT NOT NULL,        -- trace_id
    idempotency_key TEXT NOT NULL,       -- "{source}:{source_event_id}"
    auth_method TEXT NOT NULL,           -- "hmac_sha256", "api_key", etc.
    auth_principal TEXT NOT NULL,        -- connection_id or user_id
    processing_status TEXT NOT NULL DEFAULT 'received',  -- State machine values
    processing_execution_id TEXT,        -- execution_id if activated
    error TEXT,                          -- Error message if failed
    occurred_at REAL NOT NULL,           -- Source timestamp
    received_at REAL NOT NULL,           -- Server-authoritative timestamp
    created_at REAL NOT NULL,            -- Record creation timestamp

    -- Foreign keys
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    CONSTRAINT fk_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id),

    -- Constraints
    CONSTRAINT chk_processing_status CHECK (
        processing_status IN (
            'received', 'validated', 'deduplicated', 'routed',
            'processed', 'dropped', 'failed', 'closed'
        )
    ),
    CONSTRAINT chk_source CHECK (source IN ('webhook', 'schedule', 'mcp', 'api', 'internal'))
);

CREATE INDEX idx_event_log_tenant ON event_log(tenant_id);
CREATE INDEX idx_event_log_tenant_status ON event_log(tenant_id, processing_status);
CREATE INDEX idx_event_log_correlation ON event_log(correlation_id);
CREATE INDEX idx_event_log_idempotency ON event_log(idempotency_key);
CREATE INDEX idx_event_log_source_system ON event_log(source_system);
CREATE INDEX idx_event_log_occurred_at ON event_log(occurred_at);

-- RLS: tenant isolation — event_log is tenant-scoped
ALTER TABLE event_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY event_log_tenant_isolation ON event_log
    FOR ALL TO application_role
    USING (tenant_id = current_setting('app.current_tenant')::text);
```

### 10.2 event_subscriptions

Durable worker subscriptions. Survives worker crashes.

```sql
CREATE TABLE event_subscriptions (
    subscription_id TEXT PRIMARY KEY,    -- UUID v4
    worker_id TEXT NOT NULL,             -- Worker this belongs to
    tenant_id TEXT NOT NULL,             -- Isolation boundary
    workspace_id TEXT NOT NULL,          -- Workspace scope

    -- Event matching
    event_types JSONB NOT NULL,          -- ["webhook.ghl.contact_created", "schedule.*"]
    source_systems JSONB NOT NULL,       -- ["ghl", "stripe"] or []
    filter JSONB,                        -- Payload field conditions (JSONB @> query)

    -- Activation
    capability_id TEXT NOT NULL,         -- Capability to execute on match
    priority INTEGER NOT NULL DEFAULT 100,  -- Lower = higher priority
    max_concurrent INTEGER NOT NULL DEFAULT 1,

    -- State
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    matched_count INTEGER NOT NULL DEFAULT 0,
    last_matched_at REAL,

    -- Lifecycle
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    created_by TEXT NOT NULL,            -- user_id

    -- Foreign keys
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    CONSTRAINT fk_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id),
    CONSTRAINT fk_worker FOREIGN KEY (worker_id) REFERENCES workers(worker_id),
    CONSTRAINT fk_capability FOREIGN KEY (capability_id) REFERENCES capabilities(capability_id)
);

CREATE INDEX idx_event_subscriptions_tenant ON event_subscriptions(tenant_id);
CREATE INDEX idx_event_subscriptions_worker ON event_subscriptions(worker_id);
CREATE INDEX idx_event_subscriptions_active ON event_subscriptions(tenant_id, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_event_subscriptions_event_type ON event_subscriptions USING GIN(event_types);

-- RLS: tenant isolation
ALTER TABLE event_subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY event_subscriptions_tenant_isolation ON event_subscriptions
    FOR ALL TO application_role
    USING (tenant_id = current_setting('app.current_tenant')::text);
```

### 10.3 webhook_credentials

Per-tenant webhook signing secrets.

```sql
CREATE TABLE webhook_credentials (
    credential_id TEXT PRIMARY KEY,      -- UUID v4
    tenant_id TEXT NOT NULL,
    source_system TEXT NOT NULL,         -- "ghl", "stripe", etc.
    webhook_secret TEXT NOT NULL,        -- HMAC secret (encrypted at rest)
    secret_version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    rotated_at REAL,                     -- Last rotation timestamp
    expires_at REAL,                     -- Optional expiration
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,

    -- Foreign keys
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),

    -- Constraints
    CONSTRAINT chk_source CHECK (source IN ('ghl', 'stripe', 'custom', 'mcp')),
    CONSTRAINT uq_tenant_source UNIQUE (tenant_id, source_system)
);

CREATE INDEX idx_webhook_credentials_tenant ON webhook_credentials(tenant_id);
CREATE INDEX idx_webhook_credentials_source ON webhook_credentials(source_system);

-- RLS: tenant isolation
ALTER TABLE webhook_credentials ENABLE ROW LEVEL SECURITY;
CREATE POLICY webhook_credentials_tenant_isolation ON webhook_credentials
    FOR ALL TO application_role
    USING (tenant_id = current_setting('app.current_tenant')::text);
```

---

## 11. Webhook Credential Management

Webhook secrets are per-connection credentials, not per-tenant. This aligns with the existing `provider_tokens` pattern (DATA_CONTRACTS §30, DATABASE.md §10).

```python
class WebhookCredentialManager:
    """Manages webhook signing secrets.

    One credential per (tenant, source_system) pair.
    Secrets are encrypted at rest (same as provider_tokens).
    """

    async def get_secret(self, tenant_id: str, source_system: str) -> str:
        """Get HMAC secret for webhook signature verification."""

    async def rotate_secret(self, tenant_id: str, source_system: str) -> str:
        """Rotate webhook secret. Old secret remains valid during grace period."""

    async def validate_signature(
        self,
        tenant_id: str,
        source_system: str,
        raw_body: bytes,
        signature: str,
        timestamp: str,
    ) -> bool:
        """Validate HMAC-SHA256 webhook signature."""
```

### Signature Validation

```python
def validate_hmac_signature(
    secret: str,
    raw_body: bytes,
    signature: str,
    timestamp: str,
) -> bool:
    """Validate HMAC-SHA256 webhook signature.

    Format: t=timestamp,v1=signature
    """
    # 1. Check timestamp freshness
    server_time = get_server_time()
    event_time = float(timestamp)
    if abs(server_time - event_time) > 300:  # 5 minutes
        raise ReplayAttackError("Timestamp outside acceptable window")

    # 2. Compute expected signature
    signed_payload = f"{timestamp}.{raw_body.decode()}"
    expected = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    # 3. Constant-time comparison
    return hmac.compare_digest(expected, signature)
```

---

## 12. Integration with Existing Pipeline

### S0 Entry Extension for EVENT_DRIVEN mode

The existing S0 Entry (PIPELINE_STAGES.md §2) handles event-driven activation with minimal changes:

```python
# PIPELINE_STAGES.md S0 — Entry (extended)

async def s0_entry(request: Request) -> ExecutionContext:
    """Entry point — handles all activation modes including EVENT_DRIVEN."""

    # ── Common to all modes ─────────────────────────────────────────────
    trace_id = generate_uuid()          # Always generated by system
    request_id = generate_uuid()        # Always generated by system

    if request.activation_mode == "event_driven":
        # ── Event-specific fields ───────────────────────────────────────
        event_id = request.event_id     # From EventEnvelope
        correlation_id = request.correlation_id  # From EventEnvelope
        task_id = event_id              # event_id IS the task_id for events
        context_snapshot = request.payload_ref  # Reference to stored payload
        source = request.source         # From EventEnvelope.source

        # ── Tenant/workspace from auth context ──────────────────────────
        tenant_id = request.tenant_id   # From EventGateway auth (NEVER from payload)
        workspace_id = request.workspace_id  # From EventGateway auth

    else:
        # ── Existing human/schedule/api paths ───────────────────────────
        task_id = None                  # Generated at S2
        context_snapshot = request.raw_text
        source = request.source
        tenant_id = request.tenant_id   # From connection auth
        workspace_id = request.workspace_id

    # ── Create immutable ExecutionContext (unchanged) ────────────────────
    context = ExecutionContext(
        trace_id=trace_id,
        request_id=request_id,
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection_id=request.connection_id,
        user_id=request.user_id,
        source=source,
        context_snapshot=context_snapshot,
        activation_mode=request.activation_mode,
        # ... rest of fields unchanged
    )

    return context
```

### Event → S1 → S2 → S5 → S8 → S12 Flow

```
EventEnvelope
    │
    ▼
S0 Entry (event_driven mode)
    │  - Creates ExecutionContext with event_id as task_id
    │  - Sets activation_mode = "event_driven"
    │  - payload_ref becomes context_snapshot
    │
    ▼
S1 Normalize
    │  - Loads payload from payload_ref
    │  - Normalizes event data (not user text)
    │  - Injects event metadata into entities
    │
    ▼
S2 Intent Analysis
    │  - LLM sees: "Event: contact_created from GHL. Data: {...}"
    │  - Identifies intent from event data
    │  - Same as any other activation mode
    │
    ▼
S3-S7 (unchanged)
    │  - Capability discovery, resolution, safety, planning
    │
    ▼
S8 Safety Gate (unchanged)
    │  - tenant_id from ExecutionContext (already validated by gateway)
    │  - All 8 checks apply
    │
    ▼
S9-S11 (unchanged)
    │
    ▼
S12 Execute (unchanged)
    │
    ▼
S13-S15 (unchanged)
```

### Key Integration Points

| Integration point | How Event Gateway connects |
|-------------------|---------------------------|
| S0 Entry | Receives `EventEnvelope` fields, creates `ExecutionContext` with `activation_mode = "event_driven"` |
| S1 Normalize | Loads event payload from `payload_ref`, normalizes event data |
| S2 Intent Analysis | LLM sees event metadata + payload as input context |
| S8 Safety Gate | `tenant_id` from `ExecutionContext` (validated by gateway, not re-derived) |
| Outbox | Post-execution events go through existing `OutboxEvent` / `OutboxRecord` system |
| Idempotency | `event_id` becomes `task_id`; existing `idempotency_ledger` handles dedup |

---

## 13. Security Constraints

### 13.1 Tenant Identity from Auth Context

**RULE**: `EventEnvelope.tenant_id` comes from authentication context ONLY. It is NEVER extracted from the event payload.

```python
# CORRECT: tenant from auth context
auth_context = await authenticator.authenticate_webhook(...)
envelope = EventEnvelope(
    tenant_id=auth_context.tenant_id,      # From credential lookup
    ...
)

# WRONG: tenant from payload
# payload_tenant = payload.get("tenant_id")  # NEVER DO THIS
```

**Rationale**: The event payload is untrusted (SECURITY.md §2: "Payload is untrusted input"). An attacker who can forge webhooks can set any `tenant_id` in the payload. The HMAC signature ties the event to a specific tenant's credential.

### 13.2 Replay Protection

| Check | Rule | Action on Violation |
|-------|------|---------------------|
| Timestamp | \|server_time - event_time\| < 300s | Reject with 400 |
| Idempotency key | Already processed | Return cached result (if available) or 409 |
| Signature | HMAC mismatch | Reject with 401 |

### 13.3 Payload Isolation

The raw event payload is stored in `event_log` with tenant-scoped RLS. Workers accessing the payload through `payload_ref` must go through the same tenant isolation as any other data access.

### 13.4 Subscription Authorization

Worker subscriptions are scoped to `(tenant_id, workspace_id)`. A worker can only have subscriptions within its own tenant/workspace. The subscription's `capability_id` must be in the worker's `capability_profile` (enforced at S8, not at subscription creation — but validated at subscription creation as a safety net).

### 13.5 Circuit Breaker Integration

The gateway checks the tenant circuit breaker before routing. If the circuit breaker is OPEN:

1. Event is stored in `event_log` with status = "received"
2. Event is written to `outbox` for retry when circuit closes
3. HTTP 202 Accepted returned immediately
4. Circuit breaker half-open probe triggers retry

---

## 14. Implementation Rules

### 14.1 No Parallel Execution Path

The Event Gateway feeds INTO S0 — it does not create a parallel execution path. After S0, event-driven executions are IDENTICAL to human-driven executions.

### 14.2 Event Gateway is Control Plane Only

The gateway:
- Authenticates ✓
- Validates ✓
- Normalizes ✓
- Deduplicates ✓
- Routes ✓

The gateway does NOT:
- Execute business logic ✗
- Select providers ✗
- Call LLMs ✗
- Modify existing execution flow ✗

### 14.3 State is in PostgreSQL Only

The gateway and router are stateless between events. All state (subscriptions, credentials, event log, idempotency) is in PostgreSQL with RLS enforcement.

### 14.4 Event Payloads are Immutable

Once an `EventEnvelope` is created, its `payload_ref` points to immutable stored data. The payload cannot be modified. If a corrected event arrives, it gets a new `event_id`.

### 14.5 Worker Subscriptions are Durable

Subscriptions are NOT ephemeral worker-process state. They are database-persisted and survive worker crashes, restarts, and deployments.

### 14.6 Correlation Links to Existing trace_id

`EventEnvelope.correlation_id` becomes `ExecutionContext.trace_id` at S0. This links event-driven executions to the existing trace infrastructure (FINAL_ARCHITECTURE §27).

### 14.7 Pause, Activation and Assignment Do Not Change Routing

> **Worker-management repair (RD-4, RD-5; audit round 2 B4, B6; gate v10 C39):** the router keeps matching subscriptions of paused, not-yet-active or assigned workers; it never reads worker-management columns. Enforcement happens downstream: a paused or not-yet-active tenant/workspace is denied at **S0.1** (S0–S11 ruling R-P, before any S1–S11 work; `tenant_paused`, `workspace_paused`, `not_yet_active`) and again at S12 entry; a paused worker is removed by the S12 eligibility filters. Assignment (filter 14) does not apply to event-driven runs. The event is never lost: it stays in `event_log` with its processing status and can be replayed after the pause (FINAL_ARCHITECTURE §47). Quota is charged only when S12 admits the run.

### 14.8 Plan / Event / Hybrid Workers Are Derived

> **Worker-management repair (RD-10):** there is no stored worker type. A worker with at least one active subscription accepts event-driven executions; a worker with capabilities accepts plan executions; both → "hybrid". Every worker that executes a step still needs the capability in `capability_profile` and a worker `CapabilityGrant`, whatever the trigger.

---

## Validation Tests

| Test | Validates |
|------|-----------|
| `test_event_envelope_immutable()` | EventEnvelope is frozen dataclass |
| `test_event_envelope_tenant_from_auth_not_payload()` | tenant_id from auth context, never from payload |
| `test_gateway_rejects_replay()` | Events outside 5-minute window rejected |
| `test_gateway_deduplicates()` | Same idempotency_key returns cached result |
| `test_gateway_validates_hmac()` | Invalid HMAC signature rejected |
| `test_router_matches_subscription()` | Event matches subscription by type, source, filter |
| `test_router_no_match_drops()` | Event with no matching subscription is dropped |
| `test_router_creates_s0_execution()` | Matched event creates S0 entry with event_driven mode |
| `test_subscription_survives_worker_crash()` | Subscription persists when worker crashes |
| `test_correlator_consolidates_batch()` | Multiple same-type events within window are batched |
| `test_correlator_filters_noise()` | Noise events are filtered before routing |
| `test_subscription_state_machine()` | SUBSCRIPTION state transitions are valid |
| `test_event_envelope_state_machine()` | EventEnvelope processing_status transitions are valid |
| `test_circuit_breaker_buffers_events()` | Events buffered when tenant circuit is OPEN |
| `test_s0_entry_event_driven()` | S0 Entry correctly creates ExecutionContext from EventEnvelope |
| `test_event_driven_execution_same_as_human()` | Event-driven execution follows same S1-S15 path |
| `test_router_ignores_worker_pause()` | Router matching is unchanged by pause/activation/assignment; S0.1 and S12 enforce them (§14.7) |
| `test_assignment_skipped_for_event_runs()` | An assigned worker still serves an event-driven run (filter 14 skipped) |
| `test_paused_event_replayable()` | An event denied at S12 entry for a pause stays in `event_log` and replays after the pause |

---

*End of Event Gateway & Event Router Data Contracts.*
