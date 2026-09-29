# ADR-14 — Vector Memory Backend and Tenant Isolation

**Status**: DRAFT — DECISION_REQUIRED (owner). **Owner choice recorded 2026-09-29:** the tier-2 object store for large memory payloads is **Amazon S3** (Part 3; Cloudflare R2 was considered and not chosen). The vector-index option (Part 2) is still to be decided.
**Date**: 2026-09-29
**Register**: `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` Section 13 (ADR-14) and Section 20 (Memory / RAG group, items MR-1 and MR-2)
**Target phase**: post-S15 (memory / LLM layer). Nothing here is implemented, migrated or tested in S12–S15.
**Blocking rule**: **no vector code** — no dependency, backend, migration, adapter or capability — is written until Part 1 of this ADR is DECIDED and propagated. Tenant isolation is chosen together with the store, because retrofitting it onto an embedded store is harder than choosing the right store up front.

---

## 1. Context

| Source | What it says today |
|---|---|
| FINAL_ARCHITECTURE §20, §29 | LanceDB selected for vector search: "embedded, no separate service" |
| FINAL_ARCHITECTURE §21 | L3 long-term memory stored in PostgreSQL (JSONB) + LanceDB (vector); memory is isolated by worker, tenant and user |
| FINAL_ARCHITECTURE §36 | `MemoryBackend` protocol: `write(entry)`, `read(query)`, `search(vector, limit)`, `close()` — synchronous, and **no scope argument** |
| FINAL_ARCHITECTURE I-001 | "No cross-tenant data access under any circumstance. RLS enforces this at the database level." |
| FINAL_ARCHITECTURE I-014, I-020 | Memory writes go through `MemoryWriteBarrier`; state changes and their events commit atomically |
| FINAL_ARCHITECTURE §6 | `MemoryBackend` sits in Layer 0, which imports nothing from higher layers |
| DATABASE §5 | Backup, WAL archiving and PITR are defined for PostgreSQL only |
| Gate §21 / fleet phase | Several Worker Runtimes on several nodes will share state after S15 |

**The problem.** `search(vector, limit)` cannot express *whose* memory is searched. LanceDB is embedded and file-based: it has no row-level security, no roles and no transactions shared with PostgreSQL. Under the current interface, tenant isolation for vectors would rest entirely on every caller remembering to add a filter, which contradicts I-001.

## 2. Decision drivers (in priority order)

Following the gate's conflict-resolution principle (§3), the first driver outranks the rest:

1. **No cross-tenant read or write is possible**, even through a caller bug or an LLM-influenced parameter (I-001, I-007).
2. **Memory writes and their ledger/outbox events are atomic** (I-020), and go through `MemoryWriteBarrier` (I-014).
3. **Works with several Worker Runtimes on several nodes** (fleet phase), without a single-node file lock.
4. **Covered by the existing backup / PITR procedures** (DATABASE §5).
5. **Operational footprint**: fewest new services.
6. **Search performance** at the expected scale, including very large tenants.

---

## 3. Part 1 — Scope contract (decide first; independent of the store)

### 3.1 Required scope on every call

```python
@dataclass(frozen=True)
class MemoryScope:
    tenant_id: str                 # always required
    workspace_id: str              # always required
    worker_id: str | None          # None = workspace-wide memory
    user_id: str | None            # None = not user-specific
    layer: Literal["L2", "L3"]     # L0/L1 are never vector-stored

class MemoryBackend(Protocol):
    async def write(self, scope: MemoryScope, entry: MemoryEntry) -> WriteResult: ...
    async def read(self, scope: MemoryScope, query: MemoryQuery) -> list[MemoryEntry]: ...
    async def search(self, scope: MemoryScope, vector: Sequence[float],
                     limit: int, filters: MemoryFilter | None = None) -> list[MemoryHit]: ...
    async def purge(self, scope: MemoryScope) -> int: ...
    async def close(self) -> None: ...
```

Rules:

1. **Scope is mandatory and comes from `ExecutionContext` / `PrincipalChain`, never from LLM output or request parameters.** A capability parameter can narrow the search (a `MemoryFilter`), never widen it.
2. **The backend enforces scope itself.** Callers never pass a raw filter string that could replace it. There is no method that searches without a scope, and no cross-tenant API.
3. **Scope matching is exact on `tenant_id` and `workspace_id`**; `worker_id` / `user_id` of `None` in the scope means "entries with no worker/user", not "any worker/user". Broader reads are separate, explicit scopes the caller must be authorized for.
4. **Async**, consistent with adapters and runtimes.
5. **Vectors only.** The backend never calls an embedding provider (Layer 0 cannot import Layer 1). The caller embeds first (MR-3).
6. **`purge(scope)`** deletes everything in a scope (tenant off-boarding, erasure requests) and is audited.
7. **Every row/record stores** `tenant_id`, `workspace_id`, `worker_id`, `user_id`, `layer`, `embedding_model`, `embedding_dim`, `content_hash`, `source`, `confidence`, `created_at`. A search with a vector of a different model or dimension is rejected, never silently compared.

### 3.2 Physical layout — the store decides how scope is enforced

| | pgvector (PostgreSQL) | LanceDB (embedded) |
|---|---|---|
| Isolation unit | One table `memory_vectors` with `tenant_id TEXT NOT NULL`, the standard **RLS** policy (`tenant_id = current_setting('app.current_tenant')`), and LIST partitioning by tenant for large tenants | One dataset per tenant: `<root>/<tenant_id>/<layer>.lance`, path built only by the backend from `MemoryScope` |
| Enforcement level | **Database** (RLS) — meets I-001 as written | **Application** (backend code) — does **not** meet I-001's "database level" without an owner exception |
| Inside a tenant | `workspace_id`, `worker_id`, `user_id` columns; composite B-tree index; RLS + mandatory predicates | Same columns; mandatory pre-filter built by the backend |
| Path / injection risk | None (parameterized SQL) | `tenant_id` must match a strict pattern before any path is built (path traversal) |
| Approximate-nearest-neighbour index | HNSW per partition, so filtering does not destroy recall | IVF-PQ / HNSW per tenant dataset |

---

## 4. Part 2 — Store options

| Criterion (priority order) | A. pgvector default | B. LanceDB, per-tenant datasets | C. pgvector default + LanceDB optional |
|---|---|---|---|
| 1. Tenant isolation | RLS, database level ✅ | Application level ⚠️ (I-001 exception needed) | ✅ default; ⚠️ where LanceDB is enabled |
| 2. Atomic write + event (I-020) | Same transaction as ledger/outbox ✅ | Two stores; needs outbox + idempotent replay ⚠️ | ✅ default |
| 3. Several nodes | Shared database ✅ | Needs shared object storage (e.g. S3) and LanceDB concurrency rules ⚠️ | ✅ default |
| 4. Backup / PITR | Existing DATABASE §5 ✅ | Separate backup procedure ❌ | ✅ default |
| 5. Footprint | PostgreSQL extension only ✅ | No service; files/object store ✅ | Two code paths ⚠️ |
| 6. Performance at very large scale | Good to tens of millions of vectors per partition; heavier on the primary database ⚠️ | Strong on large, columnar datasets ✅ | Choose per deployment ✅ |
| Consistency with current documents | Changes §20, §29, §36 ⚠️ | Matches today ✅ | Changes §20, §29 ⚠️ |

### Recommendation: Option C

- **pgvector is the default vector backend.** It is the only option that meets drivers 1–4 as written: RLS isolation (I-001), atomic writes with events (I-020), sharing across nodes and the existing backups.
- **LanceDB remains an optional `MemoryBackend`** (§36 already makes backends pluggable) for deployments that need its scale — enabled per deployment by the owner, only with the per-tenant dataset layout of §3.2, shared object storage (Amazon S3, Part 3) for multiple nodes, its own backup procedure, and a recorded, owner-approved I-001 exception stating that isolation for that store is enforced in the backend.
- Both implement the same Part 1 contract, and the same test suite runs against both.

If the owner prefers to keep LanceDB as the default (Option B), Part 1 still applies unchanged, and the I-001 exception, the object-storage design and the backup procedure become prerequisites for MR-2.

---

## 4a. Part 3 — Tier-2 object store: Amazon S3 (owner choice, 2026-09-29)

### 4a.1 Role

S3 holds **large memory payloads** (full conversation transcripts, document chunks, binary artifacts) and memory exports. It never holds the vector index, the scope columns, metadata, or anything that search or authorization depends on: **PostgreSQL remains the system of record**, and S3 objects are reached only through a `payload_ref` stored in a PostgreSQL row. S3 is not a separate `MemoryBackend`; it is the payload store behind the PostgreSQL backend, and it carries no vector search.

### 4a.2 Size threshold

A payload stays inline in PostgreSQL (stored out of line automatically by TOAST) up to `memory_payload_inline_max_bytes` (settings object; **default 256 KiB**); larger payloads go to S3. Embeddings always stay in PostgreSQL, because the ANN index needs them there. A threshold of "a few KB" would add an S3 round trip and a cross-store consistency seam to almost every memory read, for values PostgreSQL stores efficiently.

### 4a.3 Object layout and isolation

- **Key:** `tenants/{tenant_id}/workspaces/{workspace_id}/memory/{layer}/{sha256-of-plaintext}`, built only by the backend from `MemoryScope` (never from request or LLM parameters); `tenant_id` and `workspace_id` are validated against a strict pattern first. Content-addressed keys make uploads idempotent.
- **One bucket per environment**, not per tenant: per-tenant buckets run into account bucket quotas and multiply bucket policies. Tenant isolation is enforced in two layers:
  1. the backend builds every key from the scope (Part 1);
  2. each request uses short-lived STS credentials whose **session policy only allows `tenants/{tenant_id}/*`**, so a bug in (1) cannot reach another tenant's prefix.
- Workers and Worker Runtimes never receive S3 credentials; the memory service obtains them through `CredentialProvider` (I-018).
- Bucket settings: Block Public Access on; a bucket policy that denies non-TLS requests; versioning on (for recovery), bounded by the lifecycle rules in 4a.6.

### 4a.4 Encryption and erasure (crypto-shredding)

- **Client-side envelope encryption per tenant**, following the SEC-HMAC pattern: each tenant has a data key (DEK) stored in PostgreSQL only in wrapped form, wrapped by the system KEK in the platform secret manager (AWS KMS or equivalent). Objects are encrypted before upload; SSE-S3 or SSE-KMS stays on as a baseline.
- **Erasure of an entry or scope:** in one PostgreSQL transaction, delete the rows and write an outbox event (I-020); a job then deletes the S3 object **and all its versions**, idempotently and with retries.
- **Erasure of a whole tenant:** destroy the tenant DEK. Every copy of that tenant's objects — old S3 versions, replicas, S3 backups — becomes unreadable at once.
- **Backups of PostgreSQL still contain the wrapped DEK** until they expire. To make those copies useless as well, rotate the KEK after the erasure (re-wrap the remaining tenants' DEKs) and destroy the old KEK version once no retained backup still needs it for other tenants. Otherwise, erasure inside backups completes when the oldest backup containing the DEK expires. Which of the two applies is open question 4.
- **Object Lock is not enabled** on the memory bucket: it prevents deletion until its retention ends, which contradicts on-demand erasure. If a law requires immutable retention for some records (for example an audit archive), that goes to a **separate bucket** by owner decision (open question 8).

### 4a.5 Write, read and delete paths

| Path | Order | Crash behaviour |
|---|---|---|
| Write | encrypt → PUT object (content-addressed key) → PostgreSQL transaction: metadata + vector + `payload_ref` + outbox event → commit | A crash after the PUT and before the commit leaves an orphan object. A sweeper deletes objects with no referencing row that are older than 24 hours. A row never references an object whose upload was not confirmed. |
| Read | pgvector ANN search in PostgreSQL (scoped by RLS and `MemoryScope`) → fetch by `payload_ref` → check that the key prefix matches the scope → decrypt | S3 is strongly consistent for read-after-write, so a committed reference is always readable |
| Delete | PostgreSQL delete + outbox event in one transaction → job deletes the object and its versions | Idempotent retries; the object may outlive the row briefly, but it is unreachable without the row and the key |

### 4a.6 Cost, placement and lifecycle

- **Placement:** run the memory service in the same AWS region as the bucket. S3 → compute transfer in the same region carries no data-transfer charge; transfer to compute outside AWS (for example a VPS elsewhere) is charged per GB. This is another reason to keep embeddings and small payloads in PostgreSQL. Open question 6 asks where the runtime will run.
- **Lifecycle:** noncurrent object versions expire after a set number of days, bounded by the erasure SLA (open question 7); incomplete multipart uploads are aborted after 7 days. Optional cross-region replication for disaster recovery follows the same encryption and deletion rules.

### 4a.7 Hot cache

A shared cache (Redis) is out of scope until the fleet phase (gate §1; MEMORY_ARCHITECTURE MR-10). An in-process LRU cache is allowed if every key contains the full `MemoryScope` and `purge(scope)` invalidates it.

---

## 5. Consequences (when DECIDED)

| Document | Change |
|---|---|
| FINAL_ARCHITECTURE §20, §21, §29, §36 | Default vector backend; `MemoryBackend` with `MemoryScope`, async, `purge`; LanceDB as optional backend and its conditions |
| FINAL_ARCHITECTURE I-001 | Only if LanceDB is enabled: the recorded exception text |
| DATABASE.md | `memory_vectors` table (partitioned, RLS, HNSW per partition), `CREATE EXTENSION vector`, migration, backup note |
| DATA_CONTRACTS.md | `MemoryScope`, `MemoryEntry`, `MemoryHit`, `MemoryFilter`, `WriteResult` |
| SECURITY.md | Scope from context only; purge audit; path validation for LanceDB |
| IDENTITY_AND_TENANCY.md | Memory scope derivation from `ExecutionContext` / `PrincipalChain` |
| VALIDATION.md | Tests below |
| Implementation repo | `pgvector` (and optionally `lancedb`) dependency, added in the memory phase only |
| DATABASE.md (Part 3) | `payload_ref` column on memory rows; `memory_tenant_keys` (wrapped per-tenant DEK, `kek_version`); `memory_payload_inline_max_bytes` in the settings object |
| SECURITY.md, RELIABILITY.md (Part 3) | S3 access through `CredentialProvider` and per-tenant STS session policies; crypto-shredding procedure; orphan-object sweeper and deletion job |
| Infrastructure (Part 3) | One S3 bucket per environment: Block Public Access, TLS-only policy, versioning, lifecycle rules; KMS key for the KEK |

## 6. Required tests

| Test | Proves |
|---|---|
| `test_memory_calls_require_scope()` | No backend method can be called without a `MemoryScope` |
| `test_cross_tenant_vector_search_impossible()` | Tenant A's scope never returns tenant B's vectors, including under a forged filter (pgvector: with RLS on and the application predicate removed) |
| `test_scope_from_context_not_llm()` | LLM/request parameters cannot change `tenant_id` / `workspace_id` |
| `test_filter_narrows_never_widens()` | `MemoryFilter` cannot broaden a scope |
| `test_memory_write_and_event_atomic()` | A failed ledger/outbox write leaves no vector (and vice versa) |
| `test_embedding_model_mismatch_rejected()` | A vector of another model or dimension is rejected |
| `test_tenant_memory_purge()` | `purge(scope)` removes every entry in scope and is audited |
| `test_lancedb_tenant_path_validation()` | (LanceDB only) malformed `tenant_id` never builds a path |
| `test_backend_contract_suite_both_backends()` | The same suite passes on every enabled backend |
| `test_s3_key_built_from_scope_only()` | (S3) The object key comes only from `MemoryScope`; request or LLM parameters cannot change it |
| `test_s3_session_policy_limits_tenant_prefix()` | (S3) Credentials for tenant A cannot read or write under tenant B's prefix |
| `test_payload_threshold_inline_vs_s3()` | (S3) Payloads up to the threshold stay in PostgreSQL; larger ones go to S3 |
| `test_no_row_references_unwritten_object()` | (S3) A failed upload never produces a committed `payload_ref` |
| `test_orphan_object_swept()` | (S3) An object left by a crash between upload and commit is deleted by the sweeper |
| `test_tenant_erasure_crypto_shred()` | (S3) After the tenant DEK is destroyed, old object versions cannot be decrypted |

## 7. Open questions for the owner

1. Option A, B or C (recommended: C)?
2. If LanceDB is ever enabled: accept an I-001 exception for that store, or require that LanceDB is used only for data that is not tenant-scoped (none known today)?
3. Can one embedding model be fixed per tenant, or must mixed models coexist (separate tables/partitions per model)?
4. Does erasure (`purge`) need to cover backups? If yes: immediately (KEK rotation and destruction of the old KEK version, §4a.4) or when backups expire (bounded by backup retention)?
5. Is the default inline threshold of 256 KiB acceptable (§4a.2)?
6. Where will the memory service run: in the same AWS region as the bucket, or outside AWS (per-GB transfer charges, §4a.6)?
7. What is the erasure SLA? It bounds the lifecycle expiry of noncurrent S3 versions and the backup retention.
8. Does any record class need immutable retention (Object Lock)? If so, which, and in a separate bucket (§4a.4)?
