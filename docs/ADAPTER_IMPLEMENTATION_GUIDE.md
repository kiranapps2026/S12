# Adapter Implementation Guide — S12-S15 Certified Reference

This document is a **read-only specification**. It is written before S12 certification is complete and
will be executed after the `s12-s15-certified` tag. Nothing in this file changes `src/`, `tests_golden/`,
migrations 001–015, or any frozen document. The milestone card for the first new-adapter milestone
will reference the sections of this file that apply.

**Revision 1.1 (2026-10-03).** Corrected against the code on `s12-work`: the 22 guide findings and the code facts of
`docs/proposals/ADAPTER_DOCS_REVIEW.md` (sections A and B). It is still not the full v2 that DR-08 asks for: the
worker-runtime composition (DR-14), routing several providers through one guard (DR-42), rate-limit sizing, the
golden scans and the credential store (DR-11, MC-058) are not written yet; §17 lists them. Where this guide and the
Layer A README disagree, the README and the code win. A proposed structure for real adapters (one engine, operation
archetypes, provider profiles) is in `docs/proposals/PROVIDER_API_PROFILES.md`; it is a proposal, not part of this
guide.

## 1. What "a new adapter" means in this architecture

An adapter is one class implementing `contracts.adapter_interface.BaseAdapter` plus one
`CredentialProvider` implementing `contracts.adapter_interface.CredentialProvider`. Every other
concern — retry, circuit breaking, lease management, idempotency, verification, dead-letter
handling — is owned by the S12-S15 kernel and is **never** the adapter's responsibility.

A new adapter for a new provider (vision, market data, etc.) is therefore a **narrow, additive**
change: one adapter class file, one credential provider file, and registry entries. It plugs into
the execution kernel the way `MockAdapter` does, and the way the Layer A adapters will: `ghl_crm.md` and
`gmail_mail.md` are specifications; no GoHighLevel or Gmail adapter exists in `src/` yet. Before any real adapter can
run in production, the prerequisites in §14 must also exist.

## 2. The contracts that govern every adapter call

Read these files before writing any adapter code. They are the source of truth; this guide
explains them, not replaces them.

| Contract file | What it defines | Fixed by milestone |
|---|---|---|
| `contracts/adapter_interface.py` | `BaseAdapter` protocol (`call`, `probe`, `observe`), `CallMeta`, `GuardedCall`, `ProbeOutcome`, `Observation`, `ErrorClass`, `RETRYABLE`, `BudgetStateError`, `CredentialProvider` | M10 |
| `contracts/step_execution.py` | `AdapterResult`, `StepCall`, `StepAdapter`, `FencedOut`, `Revoked` | M2 (frozen S0-S11) |
| `contracts/execution_context.py` | `ExecutionContext` — the frozen request envelope | S0-S11 (frozen) |
| `contracts/frozen_binding.py` | `FrozenBindingIdentity` — the immutable S5 resolution artifact | S0-S11 (frozen) |
| `contracts/execution_states.py` | All enums: `StepState`, `ExecutionStatus`, `ReservationState`, `RetryMode`, `ReconciliationKind`, `ReconciliationStatus`, `ReconciliationOutcome`, `DeadLetterErrorType`, `StepTerminalReason` | M1-M4 |
| `contracts/idempotency.py` | `step_idempotency_key(request_id, plan_step_id)`, `attempt_id`, `IdempotencyConflict` | M11 |

**Golden tests that lock these contracts**: `tests_golden/s12/M10_guard.py`, `M11_idempotency_retry.py`,
`M12_loop.py`, `M13_probe.py`, `M15_verification.py`. The M10 docstring is the interface contract.
Never edit these files.

## 3. The four call paths

The kernel calls the adapter through four distinct paths. Every adapter must handle all four.
Each path is read from the reference implementation, not from documentation.

### 3.1 Call (`call()` → `AdapterResult`)

**Entry point**: `engine/stages/s12_execute/attempts.py` → `run_attempts` → `ReliabilityGuard.call`

**What the kernel provides**:

- `kernel_op_id`: the operation identifier (e.g. `"crm.contact_create"`, `"mail.email_send"` from `docs/catalog/catalog.yaml`). For a rollback inverse it is the inverse operation, while `binding` is still the **create's** binding (§3.4)
- `params`: the step's params dict — **never mutate this dict**
- `binding`: `FrozenBindingIdentity` — contains `provider`, `effective_risk`, `effective_mutation`, `inverse_kernel_op_id`
- `context`: `ExecutionContext` — contains `tenant_id`, `connection_id`, `trace_id`, `request_id`, and every other S0-S11 field
- `call_meta`: `CallMeta` with `idempotency_key` (`{request_id}:{plan_step_id}`), `attempt_id`, `provider_call_id`, `tenant_id`

**What the kernel expects back**: `AdapterResult(status, retryable, error_class, data)` where:
- `status` is `"ok"`, `"error"`, or `"timeout"` — these are the only valid strings
- `error_class`, on `"error"`, is one of the five adapter classes: `NOT_DISPATCHED`, `RATE_LIMITED`, `SERVER_ERROR`, `CLIENT_ERROR`, `ADAPTER_DEFECT`. An uncertain outcome is `status="timeout"`, not an error class. `TIMEOUT`, `CIRCUIT_OPEN` and `RETRY_STORM` are set by the guard (Layer A README §1)
- `retryable` is ignored by the guard (it recomputes from `error_class` via `RETRYABLE`); set it anyway for documentation
- `data` on `"ok"` must contain `result.data[identifier_field]`, the field named by the catalog's `observation.identifier_field` (usually `id`; `ref` for GHL notes and tasks after `ghl_crm.md` §0). M15's deterministic layer requires it to be a non-empty string or int (`verification.py:75`). For an update or delete, take it from the params when the response carries no id
- `data` on `"error"` must be empty or at most `{"provider_status": <int>, "provider_code": <str>}` — **never include the provider's error body** (M18 redaction, M17 ledger safety)

**What the guard does before and after** (read `engine/stages/s12_execute/reliability.py`):

```
1. Acquire bulkhead slot (per-provider concurrency limit)
2. CircuitBreaker.allow(provider) — if OPEN, return CIRCUIT_OPEN immediately
3. BudgetTracker.check() — verify reservation is LOCKED; raise BudgetStateError if not
4. RetryStormGuard.allow_retry() — only on attempt > 1
5. TimeoutManager.run(adapter.call, timeout_s) — asyncio.timeout deadline
6. If adapter.call raises ANY exception → ADAPTER_DEFECT (non-retryable)
7. _normalise(result) — recompute retryable, drop data on timeout, reject unknown error_class
8. Record: breaker.record_success/record_failure, health.record, billing.record
```

**Retry policy** (`engine/stages/s12_execute/retry_policy.py`):

| mutation | safe | idempotent | never |
|---|---|---|---|
| R | 3 attempts | 3 attempts | 1 attempt |
| W | 2 attempts | 2 attempts | 1 attempt |
| D | 2 attempts | 2 attempts | 1 attempt |
| IRREVERSIBLE | 1 | 1 | 1 |

Backoff: reads use exponential (`base * 2^(n-1)`); writes, deletes and IRREVERSIBLE use fixed (`base_s`).
The retry ceiling is the *maximum* attempts; retry count = ceiling - 1. The starter catalog sets
`retry_safety: never` on every write and delete, so today every mutation gets one attempt.

### 3.2 Probe (`probe()` → `ProbeOutcome`)

**Entry point**: `engine/stages/s13_reconciliation/probe.py` → `resolve_execution` → `guard.probe`

**When it is called**: After a W, D or IRREVERSIBLE step's attempt produced `"timeout"` or `"uncertain"` (the step is
now `PENDING_PROBE`). The ledger has no record for this idempotency key. The probe asks: did the call
identified by `call_meta.idempotency_key` take effect? A **read** that times out is never probed: it is re-executed
(`loop.py` `read_reexecution_safe`). Up to `probe_max_attempts` probes run, immediately and then after `b` and `2b`
more seconds (`b = probe_backoff_s`).

**Guard behavior**:
- Takes a slot from the **same** per-provider bulkhead as calls (`reliability.py:79`), so a slow probe costs call
  capacity
- Bounded by one `probe_timeout_s` for everything the probe does (`reliability.py:230`), not `step_timeout_s`. The
  code default is **0.5 s**; real providers need 5–10 s, set through `S12_PROBE_TIMEOUT_S` (DR-17). Every request
  inside the probe (a search, a GET per hit) must fit that one deadline
- Bypasses the circuit breaker, budget tracker, and retry-storm guard entirely
- Any exception → `INCONCLUSIVE` (never raises to the caller)

**What the adapter must return**:

| Return when | Return value |
|---|---|
| Found the resource/effect AND it carries our idempotency key | `EXECUTED_SUCCESS` |
| Provider records the attempt as failed (rare; provider has an operation log) | `EXECUTED_FAILURE` |
| Authoritative strongly-consistent read for our key returned nothing, after documented propagation delay | `NOT_EXECUTED` |
| Search index lag, read error, ambiguous matches, more than one match | `INCONCLUSIVE` |

**Finding the idempotency key** (choose the most reliable method per operation):

1. **Provider idempotency key**: send it on the original call, then look up by it
2. **Deterministic identifier**: derive the resource id from the key (e.g. `Message-ID: <{key}@{domain}>`)
3. **Stamped marker**: write the key into a non-user-facing field (metadata, custom field, external_id), then read by it
4. **Natural key**: search by unique business field — **never use alone for NOT_EXECUTED**; an empty result from a natural-key search proves nothing because there is no dispatch time to bound it

**Critical rule**: NOT_EXECUTED requires a strongly consistent read by id or by a known index. Returning
NOT_EXECUTED incorrectly causes M13 to **re-execute the operation** — a duplicate side effect.
Return INCONCLUSIVE when in doubt; after 3 INCONCLUSIVE the step dead-letters with budget LOCKED,
which is the safe outcome.

### 3.3 Observe (`observe()` → `Observation`)

**Entry point**: `engine/stages/s13_reconciliation/verification.py` → `_provider_state` → `guard.observe`

**When it is called**: On **every** verification of a W, D or IRREVERSIBLE step: after a successful call
(`_settle_success` → verification) and after a probe that returned EXECUTED_SUCCESS. Verification makes up to three
observations, 1 s apart, until one is conclusive. The spec passed to `observe()` is:

```python
spec = {
    "method": "get_contact",           # from catalog observation.method
    "identifier": result.data["id"],   # from the call result; None after probe path
    "expected": {
        "exists": True,                # True for W/IRREVERSIBLE, False for D
        "properties": {"name": "..."}  # the step's full params, unfiltered (verifiers.py:46); D ops have none
    },
    "idempotency_key": "{request_id}:{plan_step_id}"
}
```

**Guard behavior**:
- Same per-provider bulkhead as calls, bounded by one `probe_timeout_s` (`reliability.py:251`); timeout →
  `error="observe_timeout"`
- Bypasses breaker, budget, retry-storm guard
- Any exception → `Observation(attempt=0, error="observe_error")`

**What the adapter must return**:

| Situation | `matches_expected` | `error` | Verdict |
|---|---|---|---|
| Resource read, fields match expected | `True` | `None` | PASS |
| Resource read, fields differ (or present when should be absent) | `False` | `None` | FAIL (budget released) |
| Read failed, timed out, 5xx, 429, permission error | `None` | set to error description | UNKNOWN (re-observed, never FAIL) |
| Method not implemented | `None` | `"observe_not_supported"` | UNKNOWN |

**`observed_state`**: only the compared keys' match results, never provider values (DR-60: it can reach the semantic
layer). The contract types it `str | None` (`adapter_interface.py:48`) while the semantic assessor takes
`dict | None` (`verification.py:54`); use the dict until the type is fixed.

**The `identifier=None` case** (after the probe path): After EXECUTED_SUCCESS, verification has no
adapter result, so `spec["identifier"]` is `None`. The adapter must find the resource from
`spec["idempotency_key"]` — using the same lookup method the probe used. If it cannot, return
`Observation(attempt=0, error="observe_no_identifier")`.

### 3.4 Inverse (rollback call → `AdapterResult`)

**Entry point**: `engine/stages/s14_dead_letter/rollback.py` → `rollback_execution` → `guard.call`
with `InverseBudget.check()` instead of `BudgetTracker.check()`

**When it is called**: Never automatically. Only through the explicit `rollback_execution()` of a terminal run
(gate D2, `rollback.py`), which today has no caller outside tests (DR-29). For each COMPLETED W/D step with an undo
token, latest first, it first checks that the original executed (`confirm_executed`), then calls the inverse. Never
for `IRREVERSIBLE` operations.

**What changes**:
- `call_meta.idempotency_key` ends with `:inverse` (e.g. `{request_id}:{plan_step_id}:inverse`)
- `reservation_id` is `None` (the inverse call has no budget reservation)
- `params` are the **original step's params** (not the created resource's id)
- `binding` is the **original step's binding** (`rollback.py:109`): `binding.kernel_op_id` names the create and
  `binding.effective_mutation` is `W`. Use the `kernel_op_id` argument (the inverse) to decide what to do

**What the adapter must do**:
1. Strip the `:inverse` suffix to get the original key
2. Find exactly one target resource that carries the original idempotency key
3. Operate on that target
4. If zero or multiple targets found → `client_error`, `provider_code: "inverse_target_not_found"` or `"inverse_target_ambiguous"` — never destructive

## 4. Error classification rules

The adapter classifies every outcome. The guard recomputes `retryable` from the class, so the
adapter's `retryable` flag is informational only — but setting it correctly helps debugging.

**The before-send / after-send rule**: Return a retryable error class only when you can prove the
request never reached the provider's application, or that the provider rejected it without acting.
Whenever the request **may** have been processed, return `status="timeout"`. That is the class
that leads to a probe, and the probe decides truth.

### 4.1 Transport-level errors

| Exception | Request reached provider? | Classification |
|---|---|---|
| `ConnectError`, `ConnectTimeout`, `PoolTimeout` | No | `error`, `not_dispatched` |
| `WriteTimeout`, `WriteError` | Maybe (partial body) | `timeout` |
| `ReadTimeout`, `ReadError`, `RemoteProtocolError` | After send | `timeout` |
| `asyncio.CancelledError` | — | Do not catch; let the guard's deadline handle it |
| Any other exception | Unknown | Catch at the top of `call()`: `timeout` if after send, else `adapter_defect`. Never raise. |

### 4.2 HTTP responses

| Response | Read (R) | Write (M) — no provider idempotency | Write (M) — provider honours idempotency key |
|---|---|---|---|
| 2xx, body valid, identifier present | `ok` | `ok` | `ok` |
| 2xx, body invalid or no identifier | `adapter_defect` | **`timeout`** | `timeout` |
| 400, 422 validation | `client_error` | `client_error` | `client_error` |
| 401, 403 auth/permission | `client_error` | `client_error` | `client_error` |
| 403 that is a rate limit (Google `rateLimitExceeded`) | `rate_limited` | `rate_limited` | `rate_limited` |
| 404 addressed resource | `client_error` | `client_error` (a delete may map a recorded not-found to `ok` with `already_absent`, `ghl_crm.md` §2) | `client_error` |
| 409 duplicate with our key | — | per provider file | `ok` (provider replayed) |
| 429 | `rate_limited` | `rate_limited` | `rate_limited` |
| 408 | `server_error` | **`timeout`** | `server_error` |
| 500, 502, 504 | `server_error` | **`timeout`** | `server_error` |
| 503 "not processed" body | `server_error` | `server_error` | `server_error` |
| Anything unlisted | `server_error` | **`timeout`** | `server_error` |

**Breaker interaction**: `client_error` does NOT count against the circuit breaker (C37). Every other
class and `timeout` counts as a failure. A provider that answers rate limits with 403 and is not
mapped to `rate_limited` will not open the breaker and will keep hammering the provider.

## 5. The adapter contract checklist

Every new adapter must satisfy every row. This is the definition of done for the adapter class itself;
integration tests, registry entries, and credential provider are separate concerns.

```
CONTRACT  call()
  - Signature: async def call(self, kernel_op_id, params, binding, context, *, call_meta=None) -> AdapterResult
  - Returns AdapterResult, never raises
  - Does not mutate params
  - If context.connection_id is None → client_error, provider_code="no_connection", before anything else
  - Credentials via context.connection_id → CredentialProvider only (never env, never settings)
  - result.data on ok contains the catalog's identifier_field (usually "id")
  - result.data on error is empty or {"provider_status": int, "provider_code": str}
  - No secrets, tokens, PII in data, logs, or exception text (M18 redaction)
  - No own retry loop (retry is the kernel's job via retry_policy.ceiling)
  - No deadline longer than the guard's (step_timeout_s for call, probe_timeout_s for probe and observe);
    the HTTP client timeout is ExecutionSettings.adapter_client_timeout_s, injected at construction
  - Does not catch asyncio.CancelledError (the guard's TimeoutManager cancels the task)
  - Catches Exception at the top level; converts to AdapterResult

CONTRACT  probe()
  - Signature: async def probe(self, kernel_op_id, params, binding, context, *, call_meta) -> ProbeOutcome
  - Returns ProbeOutcome, never raises
  - Read-only: zero side effects
  - Uses the idempotency key (call_meta.idempotency_key) to find the resource
  - NOT_EXECUTED only when a strongly consistent read by id/key returns nothing
  - Returns INCONCLUSIVE when the result is ambiguous or the read is eventually consistent
  - Everything it does fits one probe_timeout_s (code default 0.5 s; set S12_PROBE_TIMEOUT_S, DR-17)

CONTRACT  observe()
  - Signature: async def observe(self, kernel_op_id, observation_spec, binding, context) -> Observation
  - Returns Observation, never raises
  - Read-only: zero side effects
  - Handles identifier=None (probe path) by finding resource from observation_spec["idempotency_key"]
  - Compares only the fields listed in the operation's provider spec (ignores server-generated fields)
  - Returns matches_expected=True/False/None with error=None/set per the table in §3.3

CONTRACT  credentials
  - Every call, probe, and observe invokes credential_provider.credential(tenant_id, connection_id)
  - credential() returns str and should never raise (the protocol says so); the adapter still treats a raise
    as not_dispatched (Layer A README §5)
  - credential_valid() is a cheap local check (token present, not expired); not a provider round trip.
    M14 calls it before every step (live_authorization.py:81), but the CredentialProvider protocol in
    adapter_interface.py does not declare it yet: implement it anyway

CONTRACT  idempotency key
  - call_meta.idempotency_key = "{request_id}:{plan_step_id}" is stable across attempts and recovery
  - Send it to the provider when the provider supports idempotency headers or idempotency keys
  - Otherwise stamp it on the created resource (custom field, metadata, external_id) so probe can find it
  - The inverse key ("{request_id}:{plan_step_id}:inverse") is constructed by the kernel; the adapter
    sees it as call_meta.idempotency_key and must strip the suffix to find the original target

CONTRACT  isolation
  - No imports from engine.*, adapters.* (other than this file and mock_adapter in tests)
  - No calls to the control plane, other adapters, or S12 code
  - No authorization decisions (S8 and M14's live check own those)
  - No filesystem writes, no environment reads; settings are injected at construction, never read
```

## 6. How the existing adapters implement this

### 6.1 MockAdapter (`adapters/runtime/mock_adapter.py`)

The reference implementation. Study it before writing any adapter.

Key patterns to copy:
- `program(kernel_op_id, ...)` sets behavior per operation — in a real adapter this is the HTTP client config
- Side-effect ledger per idempotency key — the real adapter's equivalent is the provider's idempotency support
- `probe()` reads from the effect ledger by idempotency key — in a real adapter this is a provider read-by-id
- `observe()` reads by idempotency key when identifier is None — same pattern as probe
- Credentials via injected `credentials.credential(tenant_id, connection_id)` — same pattern
- Never raises, except in its `raise_exception` mode, which exists only so the guard's `adapter_defect` handling and the
  redaction tests have something to catch; a real adapter has no such mode

Key patterns NOT to copy:
- `_HANG_S` sleep (the real adapter uses HTTP client timeouts)
- `p.calls <= p.n` for retry simulation (the real adapter lets the kernel retry)

### 6.2 DeepSeek (`adapters/llm/deepseek.py`)

The existing LLM adapter. It does **not** implement `BaseAdapter` — it implements `IntentModel`.
It is not plugged into the S12 reliability guard. It is an S2-only component.

**Do not extend this adapter** for trading or vision. It has a different contract (`IntentCompletion`,
not `AdapterResult`) and a different call site (S2, not S12). A new adapter for a new provider
implements `BaseAdapter` from `contracts/adapter_interface.py` and plugs into `LoopDeps.guard`.

### 6.3 Provider base class (`engine/providers/base.py`)

This is the **S0-S11 prototype** adapter interface (`BaseProviderAdapter`). It is **not** the S12
contract. It has `execute`, `read_state`, `health_check`, `get_capabilities`. It uses
`KernelResult`/`ExecutionOutcome` return types — these are frozen S0-S11 types.

**Do not inherit from `BaseProviderAdapter`** for S12 adapters. Inherit from `contracts.adapter_interface.BaseAdapter`.

### 6.4 Startup guard (`engine/stages/s12_execute/startup.py`)

`check_worker_runtime` runs before the runtime accepts work. It checks:
1. The database role is not a superuser / does not have BYPASSRLS
2. Every active PRODUCTION_ENABLED W/D/IRREVERSIBLE binding has an adapter class whose **own class body** defines
   both `probe` and `observe` (`startup.py:25` checks `adapter_class.__dict__`; methods inherited from a base class
   do not count)

This means **no W/D/IRREVERSIBLE binding can go live without a verifiable adapter**. A vision adapter
or market-data adapter that only implements `call()` will be rejected at startup.

## 7. The kernel components that wrap the adapter

The adapter does not call the kernel. The kernel calls the adapter. These are the components the
adapter interacts with — read them, do not modify them.

### 7.1 ReliabilityGuard (`engine/stages/s12_execute/reliability.py`)

The single gate every adapter call passes through. Acquisition order:

```
1. InProcessBulkhead.slot(provider)   — per-provider concurrency limit
2. InProcessCircuitBreaker.allow()    — CLOSED=yes, OPEN=no, HALF_OPEN=one trial
3. BudgetTracker.check()              — reservation must exist and be LOCKED
4. InProcessRetryStormGuard           — only on attempt > 1
5. TimeoutManager.run(adapter.call)   — asyncio.timeout(step_timeout_s)
```

Recording order (every exit path):
```
- breaker.record_success / record_failure / record_ignored
- InProcessHealthMonitor.record(provider, status, latency_ms, attempt)
- InProcessBilling.record(call_meta, kernel_op_id, status, attempt)
```

`probe()` and `observe()` take a slot from the same per-provider bulkhead and run under `probe_timeout_s`. They
bypass the breaker, budget tracker, and retry-storm guard entirely.

### 7.2 CircuitBreaker (`adapters/runtime/circuit_breaker.py`)

Per-provider state machine: `CLOSED → OPEN` after `failure_threshold` consecutive failures;
`OPEN → HALF_OPEN` after `cooldown_seconds`; success closes, failure reopens.

Key behaviors:
- `allow()` admits one trial in HALF_OPEN; subsequent concurrent calls are refused (C37)
- `record_ignored()` releases the HALF_OPEN trial slot — the guard calls this when a call is
  refused (breaker open, budget error, retry storm) so the next call gets a trial
- `client_error` never counts as a failure (C37)

### 7.3 BudgetTracker / InverseBudget (`engine/stages/s12_execute/reliability.py`)

`BudgetTracker.check()` raises `BudgetStateError` if the reservation is missing or not LOCKED.
The guard catches this and re-raises it; the loop handles it as a run-ending condition.

`InverseBudget.check()` allows a call only when `reservation_id is None` AND the idempotency key
ends with `:inverse`. Every other call is refused. This is the D2 / CONF-038 design.

### 7.4 Retry policy (`engine/stages/s12_execute/retry_policy.py`)

Pure functions. No imports from `engine.*` or `adapters.*`. The loop calls `max_attempts(mutation, retry_safety, step_max)` to get the ceiling, then `backoff_s(mutation, attempt, base_s)` between retries.

**For a new adapter**: the adapter does not set these. The registry/catalog sets `mutation` and
`retry_safety` per operation. The adapter only needs to return the correct `ErrorClass` — the kernel
decides whether to retry.

## 8. How a step flows through the kernel (adapter's-eye view)

Read this sequence to understand when your adapter is called and what state the kernel expects.

```
Loop.run_execution(deps, tenant_id, execution_id)
  │
  ├─ Load execution, verify ownership (fence)
  │
  ├─ For each step in topological_order:
  │   │
  │   ├─ Live authorization check (M14) — may cancel run before adapter is called
  │   │
  │   ├─ Admission (M8) — may reject with QUEUE/DELAY/DENY
  │   │
  │   ├─ Worker selection + lease acquisition (M7, M8a)
  │   │
  │   ├─ Budget reservation (M9) — RESERVED → LOCKED
  │   │
  │   ├─ Pre-flight check — may cancel step
  │   │
  │   ├─ Step state → RUNNING, checkpoint written
  │   │
  │   ├─ ATTEMPTS (M11-M12):
  │   │   ├─ Live revalidation check
  │   │   ├─ Idempotency ledger lookup → HIT (cached) or miss
  │   │   ├─ Dispatch marker written (C35)
  │   │   ├─ ReliabilityGuard.call(GuardedCall) ──► YOUR ADAPTER.call()
  │   │   │     ├─ Bulkhead slot
  │   │   │     ├─ Circuit breaker allow
  │   │   │     ├─ Budget check
  │   │   │     ├─ Retry storm guard (attempt > 1)
  │   │   │     ├─ TimeoutManager.run(adapter.call, timeout_s)
  │   │   │     └─ Record outcome (breaker, health, billing)
  │   │   │
  │   │   ├─ On ok → store in idempotency ledger → SUCCESS
  │   │   ├─ On timeout → UNCERTAIN → PENDING_PROBE (a read is re-executed instead)
  │   │   ├─ On error (retryable, attempts left) → sleep(backoff) → retry
  │   │   ├─ On error (retryable, exhausted) → FAILURE
  │   │   └─ On error (non-retryable) → FAILURE
  │   │
  │   ├─ SUCCESS → S13 verification (M15), before the step commits:
  │   │   ├─ schema layer: data is a JSON-serialisable dict
  │   │   ├─ deterministic layer: data[identifier_field] is present
  │   │   ├─ guard.observe() ──► YOUR ADAPTER.observe()  (up to 3, 1 s apart)
  │   │   └─ semantic layer: LLM verdict (when required by mutation and risk)
  │   │
  │   │   → PASS → COMPLETED, budget COMMITTED
  │   │   → FAIL (any layer) → FAILED, budget released, dead letter data / retry_mode NONE
  │   │   → UNKNOWN → VERIFICATION episode → still UNKNOWN: dead letter, retry_mode VERIFY
  │   │
  │   ├─ FAILURE → DEAD_LETTER (M17):
  │   │   ├─ retry_mode: PROBE after probe exhaustion, VERIFY after unresolved verification,
  │   │   │   NONE for data failures and failed rollbacks
  │   │   └─ explicit rollback_execution() of a terminal run is separate (§3.4)
  │   │
  │   └─ PENDING_PROBE → S13 probe path (M13):
  │       ├─ ledger lookup (may resolve without adapter call)
  │       ├─ guard.probe() ──► YOUR ADAPTER.probe()
  │       ├─ EXECUTED_SUCCESS → verification → settle
  │       ├─ NOT_EXECUTED → retry the operation (NEW side effect — M13 does this)
  │       └─ INCONCLUSIVE ×3 → DEAD_LETTER, budget LOCKED
  │
  ├─ All steps terminal → Consolidation (M16)
  └─ Build envelope (M18) → S15
```

## 9. Layer A adapter specification standard

Every production adapter must have a provider spec file in `LAYER_A/ADAPTER_SPECS/`. The template
is `LAYER_A/ADAPTER_SPECS/TEMPLATE.md`. Read it before writing any provider spec.

A provider spec must document:

1. **Operations table**: `kernel_op_id`, `mutation` (R/W/D/IRREVERSIBLE), `retry_safety` (safe/idempotent/never), `identifier_field`, `observation.method`
2. **Credential format**: what the `CredentialProvider` returns for this provider (token JSON, scopes, per-connection settings)
3. **Error mapping**: how this provider's HTTP status codes map to `ErrorClass` values
4. **Idempotency mechanism**: does the provider accept idempotency keys, or does the adapter stamp them?
5. **Probe strategy**: how to find the resource by idempotency key (method 1-4 from §3.2)
6. **Observe fields**: which params are resource fields (compared) vs. metadata (ignored)
7. **Inverse operations**: which operations have inverses, and how the inverse locates its target
8. **Rate limits**: provider's concurrency and rate limits → bulkhead size and breaker threshold
9. **Launch allow-list**: which operations are cleared for production (the rest are dead-lettered until reviewed)

## 10. Adapter skeleton (for copy-paste after certification)

This skeleton implements `BaseAdapter` with all the patterns from the reference code. It is a
starting point only — every adapter needs provider-specific logic in each method.

```python
"""<Provider> adapter implementing BaseAdapter (post-S12 certification)."""
from __future__ import annotations

import logging
from typing import Any

from contracts.adapter_interface import (
    BaseAdapter, CallMeta, ErrorClass, Observation, ProbeOutcome,
)
from contracts.step_execution import AdapterResult

logger = logging.getLogger(__name__)


class CredentialProvider:
    """Tenant credential source for <Provider>.

    The credential string is a JSON document: {"token": "...", "settings": {...}}.
    Per-connection settings (location, mailbox, field ids) live inside "settings".
    The whole string is secret: never log it, never return any part of it in data.
    """

    async def credential(self, tenant_id: str, connection_id: str | None) -> str:
        """Return the credential JSON string for this tenant/connection."""
        raise NotImplementedError  # resolve from your credential store

    async def credential_valid(self, tenant_id: str, connection_id: str | None) -> bool:
        """Cheap local check: token present, not expired, refreshable."""
        raise NotImplementedError


class <Provider>Adapter(BaseAdapter):
    """<Provider> implementation of BaseAdapter.

    Every method:
    - returns its contract type, never raises
    - calls credentials.credential(tenant_id, connection_id) before any provider request
    - uses call_meta.idempotency_key for provider idempotency or stamped lookup
    - never mutates params
    """

    def __init__(self, credentials: CredentialProvider) -> None:
        self._credentials = credentials

    # -- call ----------------------------------------------------------

    async def call(
        self,
        kernel_op_id: str,
        params: dict,
        binding: Any,
        context: Any,
        *,
        call_meta: CallMeta | None = None,
    ) -> AdapterResult:
        # 1. No connection: refuse before anything else (Layer A README §5). Checking this after
        #    credential() would turn a provider that raises for None into a retryable not_dispatched.
        if context.connection_id is None:
            return AdapterResult("error", False, ErrorClass.CLIENT_ERROR,
                                 {"provider_code": "no_connection"})

        # 2. Resolve credential
        try:
            credential = await self._credentials.credential(context.tenant_id, context.connection_id)
        except Exception:
            return AdapterResult("error", False, ErrorClass.NOT_DISPATCHED)

        # 3. Dispatch to provider based on kernel_op_id
        #    The dispatch table maps kernel_op_id → (HTTP method, path, handler)
        #    Each handler: sends request, classifies response per §4.2, returns AdapterResult

        raise NotImplementedError  # implement per provider

    # -- probe ---------------------------------------------------------

    async def probe(
        self,
        kernel_op_id: str,
        params: dict,
        binding: Any,
        context: Any,
        *,
        call_meta: CallMeta,
    ) -> ProbeOutcome:
        # 1. Resolve credential
        try:
            await self._credentials.credential(context.tenant_id, context.connection_id)
        except Exception:
            return ProbeOutcome.INCONCLUSIVE

        # 2. Find the resource by call_meta.idempotency_key
        #    Use the most reliable method available (idempotency key header → stamped field → id lookup)
        #    Return EXECUTED_SUCCESS / EXECUTED_FAILURE / NOT_EXECUTED / INCONCLUSIVE per §3.2

        raise NotImplementedError  # implement per provider

    # -- observe -------------------------------------------------------

    async def observe(
        self,
        kernel_op_id: str,
        observation_spec: dict,
        binding: Any,
        context: Any,
    ) -> Observation:
        # 1. Resolve credential
        try:
            await self._credentials.credential(context.tenant_id, context.connection_id)
        except Exception:
            return Observation(attempt=0, observed_at=0.0, error="observe_error")

        # 2. Read the resource
        #    If observation_spec.get("identifier") is None, find from observation_spec["idempotency_key"]
        #    Compare the resource's fields against observation_spec["expected"]["properties"]
        #    Return Observation(attempt, observed_at, provider_response_code, observed_state,
        #                      matches_expected, error) per §3.3

        raise NotImplementedError  # implement per provider
```

## 11. Credential provider pattern

The `CredentialProvider` protocol is:

```python
class CredentialProvider(Protocol):
    async def credential(self, tenant_id: str, connection_id: str | None) -> str:
        """Return credential JSON string. Never raise."""
        ...
```

**Rules**:
- Returns one `str` (JSON document). Per-connection settings live inside it.
- Should never raise. If the credential cannot be resolved, return a string that the adapter interprets
  as "not available". The adapter still treats a raise as `not_dispatched` (Layer A README §5), never raises itself.
- `credential_valid(tenant_id, connection_id)` is a cheap local check (token present, not expired).
  It is called by M14's `LiveAuthorizationCheck` before every step (`live_authorization.py:81`) — it must not make a
  provider round trip. The protocol above does not declare it yet; implement it anyway.
- Token refresh happens inside the credential provider, not the adapter.
- The credential string is secret: never log it, never put any part of it in `data`, never include
  it in an exception message.

## 12. Registry and catalog entries

After the adapter class and credential provider are written, the following registry entries are needed:

1. **Kernel operation** (`kernel_ops` table or catalog): one row per operation, with `mutation`, `risk_floor`, `cost`,
   `timeout_seconds`, `retry_safety`, `inverse` and `observation` (`method`, `identifier_field`, `expects_absent`).
   The loader rejects any other field (`catalog.py:17`, `:20`); compared fields live in the provider spec
2. **Binding** (`bindings` table): links `kernel_op` → `adapter_class`, with `capability`, `provider`,
   `engine_module`, `priority`, `is_active` (`catalog.py:19`). Effective risk and mutation are computed at S5, never
   stored on the binding
3. **Readiness**: `tools/registry_readiness.py` exits 0 (every production W/D/IRREVERSIBLE op has an observation method)
4. **Provider config**: bulkhead size (from provider's concurrency limit), breaker threshold and cooldown

The `startup.py` guard (`check_worker_runtime`) will refuse to start if any W/D/IRREVERSIBLE binding
points to an adapter whose own class body does not define both `probe` and `observe` (§6.4).

## 13. Testing strategy (post-certification)

### 13.1 Recorded-response tests (offline, CI)

Run against `httpx.MockTransport` with recorded fixtures. The test matrix is the 16+ rows from
`LAYER_A/ADAPTER_SPECS/README.md` §6, mapped to `MockAdapter` behaviors.

Fixtures live at `tests_agent/fixtures/providers/<provider>/<operation>/<case>.json`.
Tests live at `tests_agent/test_adapter_<provider>.py`.

### 13.2 Live smoke tests (opt-in, never in CI)

`tests_live/test_<provider>_live.py` — sandbox credentials only. The repo already uses
`tests_live/` for DeepSeek. Follow the same pattern.

### 13.3 Integration check

Run the M12-M21 journeys once with the new adapter wired in and recorded transport, using a
`tests_agent` copy of the M12 `_deps` wiring. Never edit golden files to do this.

### 13.4 Sabotage patches

The milestone certifier will apply sabotage patches to the adapter's key symbols (same pattern as
M10's `MockAdapter.call` and M12's `run_execution`). The adapter must be importable by the
sabotage framework — keep symbol names stable.

## 14. What does NOT change

This guide explicitly does not require changes to:

- `src/engine/stages/s12_execute/reliability.py` — the guard is complete
- `src/engine/stages/s12_execute/loop.py` — the loop is complete
- `src/engine/stages/s12_execute/attempts.py` — the attempt runner is complete
- `src/engine/stages/s12_execute/retry_policy.py` — the retry policy is complete
- `src/engine/stages/s13_reconciliation/probe.py` — the probe path is complete
- `contracts/adapter_interface.py` — the BaseAdapter protocol is complete
- `contracts/step_execution.py` — the S0-S11 frozen contracts
- `contracts/execution_context.py` — the frozen context
- `contracts/frozen_binding.py` — the frozen binding
- Any migration 001-015
- `tests_golden/**` — never edit, never weaken, never xfail
- `docs/implementation/**` — pinned
- `docs/gates/**` — pinned

A new adapter is additive for the kernel: one class file, one credential file, registry entries. It is **not** yet
enough to run in production. Prerequisites outside the adapter: a production Worker Runtime composition (DR-14; today
the guard and loop are composed only in tests), routing when one runtime serves several providers (DR-42: the guard
holds one adapter), an API path that admits a validated plan to S12 (DR-48), an encrypted per-connection credential
store (DR-11, MC-058), and `S12_PROBE_TIMEOUT_S` set for real providers (DR-17).

## 15. Reference: full data flow for one adapter call

```
StepAttempt (built in loop.py:_execute)
  │  kernel_op_id, params, binding, context, reservation_id, timeout_s
  ▼
StepAttempt.__init__  →  StepAttempt frozen dataclass
  │  idempotency_key = step_idempotency_key(request_id, plan_step_id)
  │  attempt_id = attempt_id(step_index, attempt)
  ▼
run_attempts(step, holder, deps)
  │
  ├─ deps.live.check(...)        → M14 live authorization (may REVOKE)
  ├─ deps.ledger.lookup(key)     → idempotency HIT (cached) or miss
  ├─ deps.attempts.dispatched()  → already dispatched (UNCERTAIN)
  ├─ deps.attempts.mark_dispatched()  → dispatch marker (C35)
  │
  ├─ CallMeta(key, attempt_id, provider_call_id, tenant_id)
  ├─ GuardedCall(kernel_op_id, params, binding, context, call_meta, step_id, reservation_id, attempt, timeout_s)
  │
  ▼
ReliabilityGuard.call(GuardedCall)
  │
  ├─ bulkhead.slot(provider)     → acquire concurrency slot
  ├─ breaker.allow(provider)     → check circuit state
  ├─ budget.check(call)          → verify LOCKED reservation
  ├─ retry_storm.allow_retry()   → only if attempt > 1
  │
  ├─ TimeoutManager.run(adapter.call(kernel_op_id, params, binding, context, call_meta=call_meta), timeout_s)
  │     │
  │     ▼
  │   YOUR ADAPTER.call()
  │     │  resolves credential via CredentialProvider
  │     │  dispatches to provider API
  │     │  classifies response per §4
  │     │  returns AdapterResult
  │     │
  │     ▼
  │   _normalise(raw_result)     → recompute retryable, validate error_class
  │
  ├─ breaker.record_success/record_failure/record_ignored
  ├─ health.record(provider, status, latency_ms, attempt)
  ├─ billing.record(call_meta, kernel_op_id, status, attempt)
  │
  ▼
AttemptOutcome(kind, result, attempts)
  │  kind: "success" | "failure" | "uncertain" | "revoked"
  ▼
loop.py:_execute
  │
  ├─ "success"     → _settle_success → S13 verification → PASS: COMPLETED
  ├─ "failure"     → _settle_failure → FAILED → dead letter
  ├─ "uncertain"   → PENDING_PROBE → S13 probe path
  └─ "revoked"     → NOT_EXECUTED → release → run CANCELLED
```

## 16. Document index

| Document | Role | When to read |
|---|---|---|
| `docs/implementation/S12_S15_EXECUTION_GATE.md` | Binding gate: rulings C1-C41, D1-D6, Appendix A transition tables, normative sequence §7-§13 | Every session; the milestone card names the sections |
| `docs/implementation/S12_S15_IMPLEMENTATION_PLAN.md` | 22-milestone plan; §4 has the milestone cards | When starting a milestone |
| `docs/implementation/FINAL_ARCHITECTURE.md` | Master architecture: principles, planes, invariants, adapter contracts | M0 and when a card cites it |
| `docs/implementation/PROVIDER_ADAPTERS.md` | BaseAdapter contract, before-send/after-send rule, probe/observe semantics | M10 |
| `docs/implementation/RELIABILITY.md` | Guard components, circuit breaker, bulkhead, timeouts, probe table | M10 |
| `batch_bundles/LAYER_A/ADAPTER_SPECS/README.md` | Layer A standard: contract, error classification, probe, observe, credentials, recorded-response tests | Before writing any production adapter |
| `batch_bundles/LAYER_A/ADAPTER_SPECS/TEMPLATE.md` | Provider spec template | When creating a new provider file |
| `batch_bundles/LAYER_A/ADAPTER_SPECS/ghl_crm.md` | GoHighLevel adapter spec (reference implementation of the standard) | Reference for structure |
| `batch_bundles/README.md` | Batch status, ten rules, module map, names the tests patch | Session start |
| `docs/proposals/ADAPTER_DOCS_REVIEW.md` | Code-grounded review behind revision 1.1 of this guide | Before the v2 rewrite (DR-08) |
| `docs/proposals/PROVIDER_API_PROFILES.md` | Proposed structure for real adapters: engine, archetypes, profiles (owner decisions pending) | Before the first real adapter |

## 17. Not covered yet (for v2, DR-08)

| Topic | Where it is today |
|---|---|
| Worker Runtime composition: settings from the environment, Postgres stores, guard, sweeper, lease renewal, start-up checks, run pickup | DR-14; composed only in test fixtures |
| Several providers in one runtime (the guard holds one adapter) | DR-42 |
| Rate limits → bulkhead size and breaker threshold (one setting for every provider today, `bootstrap.py:75`) | Layer A README §7; CONF-022 |
| Timeout settings for real providers (`S12_PROBE_TIMEOUT_S`, `S12_ADAPTER_CLIENT_TIMEOUT_S`, `S12_STEP_TIMEOUT_S`) | DR-16, DR-17; recommended values in `PROVIDER_API_PROFILES.md` "Deadlines" |
| Golden scans an adapter must pass (no exception text in logs, no unfenced writes, no direct adapter calls outside the guard) | Layer A README §7 |
| Encrypted per-connection credential store | DR-11, MC-058 |

