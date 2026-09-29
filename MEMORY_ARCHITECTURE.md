# Worker Memory Architecture

**Purpose**: Complete specification for how AI workers remember, forget, learn, and share state across time, sessions, and worker instances. Memory is what transforms a stateless agent into a persistent worker.
**Status**: DEFERRED (post-S15, memory / LLM layer) — REPAIRS PENDING. Nothing here is implemented, migrated or tested in S12–S15 (gate v10 §14). **No vector code** until SUPERSESSION_AWARE_BLOCKER_REGISTER.md Section 20 MR-1 is decided (gate v10 §1).
**Upstream contracts**: [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) — §21 Memory Architecture, §36 Pluggable Memory Backends, I-001, I-014, I-018, I-019; [ADR-14_VECTOR_MEMORY_BACKEND.md](ADR-14_VECTOR_MEMORY_BACKEND.md) (partially decided: pgvector only, S3; MR-1 open); [S12_S15_EXECUTION_GATE.md](S12_S15_EXECUTION_GATE.md) v10. Where this document and FINAL_ARCHITECTURE differ, FINAL_ARCHITECTURE wins (I-015).
**Repair markers (2026-09-29)**: passages that conflict with the master documents carry `> **Memory repair (MR-n):**` notes (items MR-5…MR-10 in SUPERSESSION_AWARE_BLOCKER_REGISTER.md Section 20). Text is corrected only where a binding rule already decides the answer; passages that depend on MR-1 (scope contract) or MR-3 (embedding contract) are flagged, not redesigned.

---

## Table of Contents

1. [Memory Philosophy](#1-memory-philosophy)
2. [Memory Taxonomy](#2-memory-taxonomy)
3. [Working Memory](#3-working-memory)
4. [Long-Term Memory](#4-long-term-memory)
5. [Cross-Session Memory](#5-cross-session-memory)
6. [Memory Lifecycle](#6-memory-lifecycle)
7. [Memory Access Patterns](#7-memory-access-patterns)
8. [Memory Isolation](#8-memory-isolation)
9. [Memory Quality & Decay](#9-memory-quality--decay)
10. [Implementation](#10-implementation)
11. [Observability](#11-observability)

---

## 1. Memory Philosophy

### Why Workers Need Memory

A stateless agent treats every request as the first request. It has no context, no history, no preferences, no learned behaviors. A worker with memory:

- Remembers what the user asked for 3 days ago
- Learns which providers work best for which tasks
- Knows which confirmation patterns the user prefers
- Builds on previous results instead of re-doing work
- Maintains state across crashes and restarts

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

### What Memory Is NOT

- Memory is NOT a global knowledge base
- Memory is NOT a general-purpose or cross-tenant vector knowledge base

> **Memory repair (MR-10):** the former line said memory "is NOT a vector store for semantic search (that's a different system)", which contradicts §4 of this document (LanceDB vector search for patterns and domain knowledge) and FINAL_ARCHITECTURE §21 (L3 stored in PostgreSQL + a vector store). L3 memory **does** use vector search for retrieval, scoped per MR-1; it is not a global knowledge base.
- Memory is NOT infinite — it has explicit lifecycle and limits
- Memory is NOT shared across tenants or users without explicit intent

---

## 2. Memory Taxonomy

### The Four Memory Layers

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — Long-Term Knowledge                               │
│  Domain knowledge, learned preferences, historical patterns  │
│  Persists across worker restarts                              │
│  Curated, summarized, confidence-scored                       │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2 — Session Memory                                    │
│  Conversation history, decisions made, results obtained      │
│  Persists within a worker session                            │
│  Compacted when session ends                                 │
├─────────────────────────────────────────────────────────────┤
│  LAYER 1 — Working Memory                                    │
│  Current execution context, intermediate results             │
│  Persists during a single execution                          │
│  Checkpointed at every step                                  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 0 — Episodic Buffer                                   │
│  Immediate context window, attention focus                    │
│  Persists during a single LLM call                           │
│  Scoped to current step/iteration                            │
└─────────────────────────────────────────────────────────────┘
```

### Memory Layer Comparison

| Layer | Name | Lifetime | Size | Persistence | Access Pattern |
|-------|------|----------|------|-------------|----------------|
| 0 | Episodic Buffer | Single LLM call | ~8K tokens | In-memory | Sequential |
| 1 | Working Memory | Single execution | ~100K tokens | Checkpointed | Random |
| 2 | Session Memory | Worker session | ~1M tokens | Checkpointed | Random |
| 3 | Long-Term Knowledge | Indefinite | ~10M tokens | Database | Random/Vector |

---

## 3. Working Memory

### What It Contains

Working memory holds the execution state for a single execution run:

```python
@dataclass
class WorkingMemory:
    """In-memory context for a single execution."""
    trace_id: str                    # Unique execution identifier
    execution_context: ExecutionContext  # Frozen from S0
    current_step: int                # Current step index
    step_results: list[StepResult]   # Results from each executed step
    partial_results: dict[str, Any]  # Intermediate results for consolidation
    errors: list[ExecutionError]     # Errors encountered during execution
    retry_count: int                 # Current retry count
    checkpoint_sequence: int         # Last checkpoint number
```

> **Memory repair (MR-10):** `budget_remaining: Decimal` was removed. Budget is held only by `budget_reservations` through the BudgetReserver, in integer minor units (gate C3, C31); working memory never carries a budget figure. Working memory is also not a new S0 artifact: S0–S11 are certified, and S12–S15 state lives in the execution tables and `checkpoints` (gate C10). The database state is the source of truth; a checkpoint is a hint (gate §13).

### Working Memory Lifecycle

```
Created at S0 (Entry)
    │
    ▼
Populated during pipeline (S0-S12)
    │
    ├── Checkpoint after each step (S12)
    │   └── Persisted to checkpoint store
    │
    ▼
Consolidated at S13
    │
    ▼
Archived at S14/S15
    │
    ├── Success → Session Memory (compacted)
    ├── Partial failure → Session Memory (with error context)
    └── Dead letter → Long-Term Knowledge (failure pattern)
```

> **Memory repair (MR-10):** material copied from execution results, errors or dead-letter evidence into memory passes the same redaction as S15 and dead-letter evidence: no credentials, tokens, provider bodies or stack traces (I-018, gate §21 S6). Memory promotion is a memory write and goes through `MemoryWriteBarrier` (MR-9).

### Working Memory Isolation

| Attribute | Enforcement |
|-----------|------------|
| Per-execution | trace_id scopes all memory entries |
| Per-tenant | RLS ensures tenant isolation |
| Per-worker | worker_id scopes worker-specific memory |
| Checkpoint store | Row-level security on checkpoints table |

---

## 4. Long-Term Memory

### What It Contains

Long-term memory is the persistent knowledge store for a worker:

```python
@dataclass
class LongTermMemory:
    """Persistent knowledge for a worker."""
    worker_id: str
    tenant_id: str
    user_id: str | None  # None for shared worker memory

    # Preference Memory
    preferences: dict[str, Any]     # User preferences, defaults, habits
    confirmation_patterns: dict[str, Any]  # How user confirms/rejects — informational only (MR-10)

    # Procedural Memory
    successful_patterns: list[ExecutionPattern]  # What worked before
    failure_patterns: list[FailurePattern]        # What failed and why

    # Semantic Memory
    domain_knowledge: dict[str, Any] # Domain-specific knowledge
    provider_knowledge: dict[str, Any] # Provider-specific learnings

    # Historical Memory (MR-10: renamed from "Episodic Memory", which is the name of layer L0)
    significant_events: list[Event]  # Important past events
```

> **Memory repair (MR-10):** `confirmation_patterns` and every other memory entry are informational. Memory never decides authorization, confirmation (S10) or admission, and never skips a confirmation (FINAL_ARCHITECTURE §21 "memory is never authorization", I-007).

### Pluggable Memory Backend

Workers depend on `MemoryBackend`, never on a specific implementation. LanceDB is the default vector backend; PostgreSQL handles structured data; object storage handles bulk archival.

> **Superseded in part — ADR-14 Q1 (owner, 2026-09-29):** LanceDB is **not** the vector backend. The only vector backend is **pgvector in PostgreSQL** (RLS, I-001; no I-001 exception). This section, and every LanceDB reference in this document, is rewritten when ADR-14 is DECIDED; until MR-1 is decided no vector code of any kind is written (gate v10 §1). Object storage for large payloads is Amazon S3 (ADR-14 Part 3).

| Memory Type | Primary Backend | Vector Backend | Notes |
|-------------|----------------|----------------|-------|
| Preferences | PostgreSQL (JSONB) | — | Key-value lookup by preference key |
| Execution Patterns | PostgreSQL | LanceDB | Vector search by task description |
| Failure Patterns | PostgreSQL | — | Query by error type, provider, time range |
| Domain Knowledge | — | LanceDB | Vector search by topic |
| Events | PostgreSQL | — | Time-range query by worker/tag |

```python
class MemoryBackend(ABC):
    """Pluggable memory backend — workers depend on this abstraction."""

    @abstractmethod
    async def store(self, entry: MemoryEntry) -> None: ...
    @abstractmethod
    async def retrieve(self, query: MemoryQuery) -> list[MemoryEntry]: ...
    @abstractmethod
    async def delete(self, entry_id: str) -> None: ...
    @abstractmethod
    async def consolidate(self) -> None: ...
```

> **Memory repair (MR-7):** this interface (`store`, `retrieve`, `delete`, `consolidate`) differs from FINAL_ARCHITECTURE §36 (`write`, `read`, `search`, `close`), which is authoritative (I-015). Neither has a scope argument, and this one has no vector search at all. The single interface is decided with MR-1: ADR-14 §3.1 proposes `write`, `read`, `search`, `purge`, `close`, all async and all taking a mandatory `MemoryScope`. Until then, treat the class names below as placeholders.

```python
class PostgresMemoryBackend(MemoryBackend):
    """PostgreSQL-backed structured memory (preferences, events, failures)."""

class LanceDBMemoryBackend(MemoryBackend):
    """LanceDB-backed vector memory (domain knowledge, pattern search)."""

class ObjectStorageMemoryBackend(MemoryBackend):
    """Object storage-backed archival memory (bulk retention, replay)."""
```

Adding a new backend requires implementing `MemoryBackend` — no worker code changes needed.

### Long-Term Memory Storage

| Memory Type | Storage | Query Pattern |
|-------------|---------|---------------|
| Preferences | PostgreSQL (JSONB) | Key-value lookup by preference key |
| Execution Patterns | PostgreSQL + LanceDB | Vector search by task description |
| Failure Patterns | PostgreSQL | Query by error type, provider, time range |
| Domain Knowledge | LanceDB | Vector search by topic |
| Events | PostgreSQL | Time-range query by worker/tag |

### Long-Term Memory Operations

```python
class LongTermMemoryStore:
    """Persistent memory store with query and update operations."""

    async def get_preference(self, worker_id: str, key: str) -> Any | None:
        """Get a user preference by key."""

    async def set_preference(self, worker_id: str, key: str, value: Any) -> None:
        """Set a user preference."""

    async def record_pattern(self, worker_id: str, pattern: ExecutionPattern) -> None:
        """Record a successful execution pattern."""

    async def find_similar_patterns(self, worker_id: str, task: str,
                                     limit: int = 5) -> list[ExecutionPattern]:
        """Find similar successful patterns using vector search."""

    async def record_failure(self, worker_id: str, failure: FailurePattern) -> None:
        """Record a failure pattern."""

    async def get_recent_failures(self, worker_id: str, provider: str | None = None,
                                   hours: int = 24) -> list[FailurePattern]:
        """Get recent failures, optionally filtered by provider."""

    async def record_event(self, worker_id: str, event: Event) -> None:
        """Record a significant event."""

    async def get_events(self, worker_id: str, tag: str | None = None,
                         since: datetime | None = None) -> list[Event]:
        """Get events, optionally filtered by tag and time."""
```

---

## 5. Cross-Session Memory

### Session Memory Lifecycle

```
Worker Session Created
    │
    ▼
Session Memory Initialized
    │
    ├── Load from Long-Term Memory (preferences, recent patterns)
    │   └── Compacted summary of last N sessions
    │
    ▼
Session Active
    │
    ├── Conversation appended to session history
    ├── Decisions recorded in session memory
    ├── Results cached in session memory
    │
    ▼
Session Ended
    │
    ├── Compact session memory
    │   ├── Significant events → Long-Term Memory (significant_events)
    │   ├── Successful patterns → Long-Term Memory (successful_patterns)
    │   ├── Failure patterns → Long-Term Memory (failure_patterns)
    │   └── Preferences → Long-Term Memory (preferences)
    │
    └── Session memory archived
```

### Session Memory Structure

```python
@dataclass
class SessionMemory:
    """Memory for a single worker session."""
    session_id: str
    worker_id: str
    tenant_id: str
    started_at: datetime
    ended_at: datetime | None

    # Conversation
    messages: list[Message]  # Conversation turns
    decisions: list[Decision]  # Decisions made during session
    results: list[Result]  # Execution results

    # Context
    active_context: dict[str, Any]  # Current working context
    context_history: list[ContextSnapshot]  # Context snapshots

    # Summary
    summary: str | None  # Compact session summary
    tags: list[str]  # Session tags for retrieval
```

### Session Memory Operations

```python
class SessionMemoryStore:
    """Session-scoped memory store."""

    async def create_session(self, worker_id: str, tenant_id: str) -> SessionMemory:
        """Create a new session, loading recent context from long-term memory."""

    async def append_message(self, session_id: str, message: Message) -> None:
        """Append a message to session history."""

    async def record_decision(self, session_id: str, decision: Decision) -> None:
        """Record a decision made during the session."""

    async def record_result(self, session_id: str, result: Result) -> None:
        """Record an execution result."""

    async def compact_session(self, session_id: str) -> SessionSummary:
        """Compact session memory and migrate significant items to long-term memory."""

    async def end_session(self, session_id: str) -> None:
        """End session, compact memory, migrate to long-term."""
```

---

## 6. Memory Lifecycle

### Memory Entry Lifecycle

```
Created
    │
    ▼
Active (in working memory)
    │
    ├── Used within execution context
    │
    ▼
Evaluated at session end
    │
    ├── Significant → Promote to Long-Term Memory
    │   └── Confidence: HIGH
    │   └── TTL: Indefinite (until superseded)
    │
    ├── Routine → Keep in Session Summary
    │   └── Confidence: MEDIUM
    │   └── TTL: Until next session
    │
    ├── Stale → Discard
    │   └── Confidence: LOW
    │   └── TTL: N/A
    │
    ▼
Archived / Deleted
    │
    └── Deleted on user request or TTL expiry
```

### Memory TTL Policy

| Memory Type | TTL | Trigger |
|-------------|-----|---------|
| Episodic buffer | End of LLM call | Step completion |
| Working memory | End of execution | Execution completion |
| Session memory | End of session | Session end |
| Session summary | 30 days | Time-based expiry |
| Successful patterns | Indefinite | Until superseded by better pattern |
| Failure patterns | 90 days | Time-based expiry |
| Preferences | Indefinite | Until user changes |
| Events | 1 year | Time-based expiry |

### Memory Quality Scoring

```python
@dataclass
class MemoryQuality:
    """Quality metrics for a memory entry."""
    confidence: float      # 0.0-1.0, how confident we are this memory is correct
    recency: float         # 0.0-1.0, how recently this memory was used
    relevance: float       # 0.0-1.0, how relevant to current task
    usage_count: int       # How many times this memory has been retrieved
    last_used: datetime    # Last retrieval timestamp
    created_at: datetime   # Creation timestamp

    def effective_score(self, now: datetime) -> float:
        """Compute effective quality score."""
        recency_decay = self._decay(self.recency, self.last_used, now)
        confidence_weight = self.confidence * 0.6
        recency_weight = recency_decay * 0.3
        usage_weight = min(self.usage_count / 10, 1.0) * 0.1
        return confidence_weight + recency_weight + usage_weight

    @staticmethod
    def _decay(base: float, last_used: datetime, now: datetime) -> float:
        """Exponential decay based on time since last use.

        `now` is server-authoritative time from the database (I-019), passed in by the caller.
        """
        hours_since = (now - last_used).total_seconds() / 3600
        return base * (0.95 ** hours_since)
```

> **Memory repair (MR-10):** the former `datetime.now()` used the worker-local clock, which IDENTITY_AND_TENANCY §11 marks "WRONG" for any stored or policy decision (I-019). `effective_score()` must pass the database time through. Every `now()` elsewhere in this document means database time.

---

## 7. Memory Access Patterns

### Read Patterns

| Pattern | Query | Use Case |
|---------|-------|----------|
| **Direct lookup** | Get by key (preference, session) | Current execution needs specific data |
| **Temporal query** | Get events in time range | Debugging, audit |
| **Vector search** | Semantic search in patterns | Finding similar past executions |
| **Tag query** | Get by tag | Category-based retrieval |
| **Session replay** | Get session by ID | Re-execution, debugging |

### Write Patterns

| Pattern | Write | Use Case |
|---------|-------|----------|
| **Immediate write** | Write to working memory | Current execution state |
| **Deferred write** | Write to session memory | Conversation turns |
| **Promotion** | Write to long-term memory | Significant events, patterns |
| **Batch write** | Write multiple entries | Session compaction |
| **Conditional write** | Write if not exists | Preferences (don't overwrite) |

### Memory Access Rules

> **Memory repair (MR-6):** `can_delete` had no tenant check (`worker_id` match **or** `is_admin`), so an admin of tenant A could delete tenant B's memory. Corrected below: the tenant check comes first in every rule, and "admin" means membership role `owner`/`admin` **in the memory's workspace**, read live (IDENTITY_AND_TENANCY §5). The final scope rules are part of MR-1; these are the minimum.

```python
class MemoryAccessPolicy:
    """Rules for accessing memory."""

    # Read rules
    def can_read(self, caller: Caller, memory: Memory) -> bool:
        # Rule 1: Tenant match
        if caller.tenant_id != memory.tenant_id:
            return False
        # Rule 2: Worker match or shared
        if caller.worker_id != memory.worker_id and not memory.is_shared:
            return False
        # Rule 3: Not expired
        if memory.expires_at and memory.expires_at < now():
            return False
        return True

    # Write rules
    def can_write(self, caller: Caller, memory: Memory) -> bool:
        # Rule 1: Tenant match
        if caller.tenant_id != memory.tenant_id:
            return False
        # Rule 2: Own worker or system
        if caller.worker_id != memory.worker_id and caller.type != "system":
            return False
        return True

    # Delete rules
    def can_delete(self, caller: Caller, memory: Memory) -> bool:
        # Rule 1: Tenant match (MR-6: was missing)
        if caller.tenant_id != memory.tenant_id:
            return False
        # Rule 2: Owner, or owner/admin membership in the memory's workspace (read live)
        return caller.worker_id == memory.worker_id or caller.is_workspace_admin(memory.workspace_id)
```

---

## 8. Memory Isolation

### Isolation Dimensions

| Dimension | Enforcement | Scope |
|-----------|------------|-------|
| **Tenant** | RLS on all memory tables | All memory layers |
| **User** | user_id field, RLS policy | Preferences, session memory |
| **Worker** | worker_id field, RLS policy | All memory layers |
| **Session** | session_id field, RLS policy | Session memory |
| **Execution** | trace_id field, RLS policy | Working memory |

> **Memory repair (MR-5):** "RLS on all memory tables" holds only for PostgreSQL tables. A vector store such as LanceDB is embedded and file-based and has **no RLS**, so the guarantees below do not hold for vector data until MR-1 (scope contract and physical layout) and ADR-14 (store choice) are decided. The §10 `record_pattern` code shows the gap: its vector row has `worker_id` but no `tenant_id`.

### Isolation Guarantees

| Guarantee | Enforcement |
|-----------|------------|
| Tenant A cannot read Tenant B's memory | RLS on all tables |
| Worker A cannot read Worker B's memory | worker_id in RLS policy |
| User A cannot read User B's preferences | user_id in RLS policy |
| Executions cannot access other executions' working memory | trace_id scoped |
| Shared memory is explicit | is_shared flag, admin-only write |

### Memory Leak Prevention

| Risk | Prevention |
|------|-----------|
| Cross-tenant memory leak | RLS on all memory tables |
| Cross-user memory leak | user_id in RLS policy |
| Memory unbounded growth | Size limits + TTL enforcement |
| Zombie memory references | Soft delete + cleanup job |
| Memory poisoning | Validation on all memory writes |

---

## 9. Memory Quality & Decay

### Decay Policy

| Memory Type | Decay Rate | Trigger |
|-------------|-----------|---------|
| Preferences | None | Explicit change only |
| Successful patterns | 5% per month | Access-based |
| Failure patterns | 10% per month | Time-based |
| Events | 5% per month | Time-based |
| Session summaries | 10% per month | Time-based |

### Memory Promotion Rules

```python
class MemoryPromotionPolicy:
    """Rules for promoting session memory to long-term memory."""

    def should_promote(self, event: Event, pattern: ExecutionPattern) -> bool:
        """Determine if a memory entry should be promoted to long-term."""

        # Rule 1: Significant events always promote
        if event.type in ("confirmation_escalation", "dead_letter", "human_intervention"):
            return True

        # Rule 2: Patterns with high confidence promote
        if pattern.confidence > 0.8 and pattern.usage_count > 3:
            return True

        # Rule 3: Patterns with high success rate promote
        if pattern.success_rate > 0.9 and pattern.usage_count > 5:
            return True

        # Rule 4: Failure patterns with actionable insight promote
        if pattern.is_failure and pattern.has_actionable_insight:
            return True

        return False
```

### Memory Forgetting

```python
class MemoryForgettingPolicy:
    """Rules for forgetting or degrading memories."""

    def should_forget(self, memory: MemoryEntry) -> bool:
        """Determine if a memory should be forgotten."""

        # Rule 1: Expired memories
        if memory.expires_at and memory.expires_at < now():
            return True

        # Rule 2: Low quality + old
        if memory.quality.effective_score(now()) < 0.1 and \
           (now() - memory.created_at).days > 90:
            return True

        # Rule 3: Superseded by newer memory
        if memory.superseded_by is not None:
            return True

        return False

    def decay(self, memory: MemoryEntry) -> MemoryEntry:
        """Apply decay to a memory entry."""
        decayed_confidence = memory.quality.confidence * 0.95
        return dataclasses.replace(memory, quality=MemoryQuality(
            confidence=decayed_confidence,
            recency=0.0,
            relevance=0.0,
            usage_count=memory.quality.usage_count,
            last_used=memory.quality.last_used,
            created_at=memory.quality.created_at,
        ))
```

---

## 10. Implementation

### Memory Store Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Store Layer                         │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Working      │  │ Session      │  │ Long-Term        │  │
│  │ Memory Store │  │ Memory Store │  │ Memory Store     │  │
│  │ (in-memory,  │  │ (checkpoint, │  │ (PostgreSQL +    │  │
│  │  checkpoint) │  │  archive)    │  │  LanceDB)        │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────┘  │
│         │                 │                                 │
│         └─────────────────┼─────────────────────────────────┘
│                           │
│                    ┌──────▼───────┐
│                    │ Memory Cache │
│                    │ (Redis)      │
│                    │ Hot-path     │
│                    └──────────────┘
└─────────────────────────────────────────────────────────────┘
```

> **Memory repair (MR-10):** the Redis memory cache is out of scope until the fleet phase (gate §1 forbids Redis in S12–S15). When it lands, every cache key starts with the full memory scope (tenant, workspace, worker, user), the cache is never authoritative, and `purge(scope)` invalidates it.

### Memory Store Classes

```python
class WorkingMemoryStore:
    """In-memory working memory, checkpointed to database."""

    def __init__(self, trace_id: str, db: Database):
        self.trace_id = trace_id
        self.db = db
        self._memory: WorkingMemory | None = None

    async def initialize(self, context: ExecutionContext) -> WorkingMemory:
        """Create initial working memory from execution context."""
        self._memory = WorkingMemory(
            trace_id=self.trace_id,
            execution_context=context,
            current_step=0,
            step_results=[],
            partial_results={},
            errors=[],
            retry_count=0,
            checkpoint_sequence=0,  # MR-10: budget_remaining removed; ExecutionContext has no `budget`
        )
        return self._memory

    async def checkpoint(self) -> None:
        """Persist current working memory to database."""
        if self._memory is None:
            raise RuntimeError("Memory not initialized")
        await self.db.insert("checkpoints", {  # MR-10: gate C10 table (was "execution_checkpoints")
            "trace_id": self.trace_id,
            "sequence": self._memory.checkpoint_sequence,
            "step": self._memory.current_step,
            "data": self._memory.to_dict(),
            "created_at": now(),
        })

    async def restore(self) -> WorkingMemory | None:
        """Restore working memory from last checkpoint."""
        row = await self.db.fetch_one(
            "SELECT * FROM checkpoints WHERE trace_id = :trace_id "
            "ORDER BY sequence DESC LIMIT 1",
            {"trace_id": self.trace_id},
        )
        if row is None:
            return None
        return WorkingMemory.from_dict(row["data"])


class SessionMemoryStore:
    """Session-scoped memory, compacted at session end."""

    def __init__(self, session_id: str, db: Database, cache: Redis):
        self.session_id = session_id
        self.db = db
        self.cache = cache
        self._memory: SessionMemory | None = None

    async def initialize(self, worker_id: str, tenant_id: str) -> SessionMemory:
        """Create session, load recent context from long-term memory."""
        ltm = LongTermMemoryStore(self.db, self.cache)
        recent = await ltm.get_recent_sessions(worker_id, limit=5)
        self._memory = SessionMemory(
            session_id=self.session_id,
            worker_id=worker_id,
            tenant_id=tenant_id,
            started_at=now(),
            ended_at=None,
            messages=[],
            decisions=[],
            results=[],
            active_context={},
            context_history=[],
            summary=recent.summary if recent else None,
            tags=[],
        )
        return self._memory


class LongTermMemoryStore:
    """Persistent long-term memory store."""

    def __init__(self, db: Database, cache: Redis, vector_store: LanceDB):
        self.db = db
        self.cache = cache
        self.vector_store = vector_store

    async def get_preference(self, worker_id: str, key: str) -> Any | None:
        """Get preference by key."""
        row = await self.db.fetch_one(
            "SELECT value FROM worker_preferences WHERE worker_id = :worker_id AND key = :key",
            {"worker_id": worker_id, "key": key},
        )
        return row["value"] if row else None

    async def record_pattern(self, worker_id: str, pattern: ExecutionPattern) -> None:
        """Record execution pattern in both PostgreSQL and vector store.

        NOT A TEMPLATE — see the repair note after this block (MR-5, MR-8, MR-9).
        """
        # Store in PostgreSQL
        await self.db.insert("execution_patterns", {
            "worker_id": worker_id,
            "pattern_id": pattern.id,
            "task_description": pattern.task_description,
            "provider": pattern.provider,
            "steps": pattern.steps,
            "success_rate": pattern.success_rate,
            "usage_count": pattern.usage_count,
            "created_at": now(),
        })
        # Store embedding in LanceDB
        embedding = await self._embed(pattern.task_description)
        await self.vector_store.upsert("patterns", {
            "id": pattern.id,
            "worker_id": worker_id,
            "embedding": embedding,
            "task_description": pattern.task_description,
        })
```

> **Memory repair (MR-5, MR-8, MR-9):** this sketch shows three defects, kept visible on purpose.
> - **MR-5:** the vector row carries `worker_id` but no `tenant_id` (or workspace/user), and the PostgreSQL queries filter by `worker_id` alone. Every memory row and query is scoped by the full `MemoryScope` (MR-1; gate C34 for PostgreSQL rows).
> - **MR-8:** `self._embed(...)` makes the memory store call an embedding provider itself. A memory backend (Layer 0) cannot call a provider (Layer 1), and an embedding call needs a frozen binding, credentials via `CredentialProvider` (I-018) and budget. The caller embeds and passes vectors (MR-3).
> - **MR-9:** both writes go straight to the database and the vector store. Every memory write goes through `MemoryWriteBarrier` (I-014), which is not yet designed; the PostgreSQL row and the vector row must also be written consistently with their event (I-020), which is decided by the store choice (ADR-14).

---

## 11. Observability

### Memory Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `memory.working.size_bytes` | Gauge | Current working memory size |
| `memory.session.count` | Gauge | Active session count |
| `memory.longterm.pattern_count` | Gauge | Long-term pattern count |
| `memory.cache.hit_rate` | Gauge | Cache hit rate |
| `memory.checkpoint.duration_ms` | Histogram | Checkpoint write duration |
| `memory.compaction.duration_ms` | Histogram | Session compaction duration |
| `memory.promotion.count` | Counter | Memory promotion count by type |
| `memory.decay.count` | Counter | Memory decay count by type |

### Memory Tracing

| Trace Event | Data |
|-------------|------|
| `memory.read` | memory_type, key, hit/miss, latency_ms |
| `memory.write` | memory_type, key, size_bytes |
| `memory.checkpoint` | trace_id, sequence, step, size_bytes, duration_ms |
| `memory.compact` | session_id, input_size, output_size, duration_ms |
| `memory.promote` | memory_type, source, confidence |
| `memory.forget` | memory_type, reason, age_days |

### Memory Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| Memory unbounded growth | Working memory > 10MB per execution | Warning |
| Checkpoint failure | Checkpoint write fails 3x in a row | Critical |
| Cache hit rate low | Cache hit rate < 70% | Warning |
| Memory leak | Session memory > 100MB | Critical |
| Decay backlog | Decay queue > 10K entries | Warning |
