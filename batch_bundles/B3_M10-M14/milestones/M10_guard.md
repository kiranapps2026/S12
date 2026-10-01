# M10: mock adapter, adapter interface, reliability guard (gate commit G, part 1) ⚙

| | |
|---|---|
| Gate | C4, C31, C32, C37, §15.3, §21 S3, S6; RELIABILITY §1–§8; PROVIDER_ADAPTERS §1 |
| Rulings | CONF-021 (use the frozen `AdapterResult`), CONF-022 (breaker per provider), CONF-023 (a half-open 4xx releases the trial; an adapter's own `TimeoutError` is `timeout`) |
| Golden | `tests_golden/s12/M10_guard.py`: 64 cases |
| Sabotage (10) | `M10_breaker_before_bulkhead`, `M10_budget_unchecked`, `M10_call_unchecked`, `M10_client_error_counts`, `M10_mock_no_dedup`, `M10_probe_through_breaker`, `M10_timeout_from_text`, `M10_trial_held_on_cancel`, `M10_trial_leak`, `M10_unsafe_default_probe` (helper `_guard_base.py` wraps `ReliabilityGuard.__init__` keyword arguments) |
| Reference | `src/contracts/adapter_interface.py`, `src/engine/stages/s12_execute/reliability.py` (131 lines), `src/adapters/runtime/{reliability,mock_adapter,circuit_breaker}.py`, `budget_reserver.py` (`reservation`) |

## Files

| File | Action |
|---|---|
| `src/contracts/adapter_interface.py` | **new**: `CallMeta`, `ProbeOutcome`, `Observation`, `ErrorClass`, `RETRYABLE`, `BaseAdapter`, `CredentialProvider`, `BudgetStateError`, `GuardedCall` |
| `src/engine/stages/s12_execute/reliability.py` | **new**: `BudgetTracker`, `TimeoutManager`, `ReliabilityGuard`. No SQL, no `adapters.*` / `asyncpg` import |
| `src/adapters/runtime/reliability.py` | **new**: `InProcessBulkhead`, `InProcessRetryStormGuard`, `InProcessHealthMonitor`, `InProcessBilling` |
| `src/adapters/runtime/mock_adapter.py` | **new**: `MockAdapter(credentials)` |
| `src/adapters/runtime/circuit_breaker.py` | add `allow(provider)` and `record_ignored(provider)`; HALF_OPEN admits one trial at a time; `state` keeps the S8 names |
| `src/adapters/postgres/budget_reserver.py` | add `reservation(tenant_id, reservation_id)` → row (`reservation_id`, `step_id`, `execution_id`, `status`) or `None` |

## Interface (exact; from the golden docstring)

```python
# contracts/adapter_interface.py
@dataclass(frozen=True) class CallMeta: idempotency_key; attempt_id; provider_call_id; tenant_id
class ProbeOutcome(StrEnum): EXECUTED_SUCCESS; EXECUTED_FAILURE; NOT_EXECUTED; INCONCLUSIVE
@dataclass(frozen=True) class Observation: attempt; observed_at; provider_response_code; observed_state; matches_expected; error
class ErrorClass(StrEnum): not_dispatched; rate_limited; server_error; client_error; adapter_defect; timeout; circuit_open; retry_storm
RETRYABLE = frozenset({not_dispatched, rate_limited, server_error})
class BaseAdapter(ABC):
    async def call(self, kernel_op_id, params, binding, context, *, call_meta=None) -> AdapterResult   # abstract
    async def probe(self, kernel_op_id, params, binding, context, *, call_meta) -> ProbeOutcome        # default INCONCLUSIVE
    async def observe(self, kernel_op_id, observation_spec, binding, context) -> Observation           # default matches_expected=None, error="observe_not_supported"
class CredentialProvider(Protocol): async def credential(self, tenant_id, connection_id) -> str
class BudgetStateError(Exception)
@dataclass(frozen=True) class GuardedCall: kernel_op_id; params; binding; context; call_meta; step_id; reservation_id; attempt; timeout_s
    # ValueError when call_meta.tenant_id != context.tenant_id (C34), attempt < 1, or timeout_s <= 0

# engine/stages/s12_execute/reliability.py
class BudgetTracker:  def __init__(self, lookup); async def check(self, call)    # LOCKED row of this step, else BudgetStateError
class TimeoutManager: async def run(self, awaitable, timeout_s)                # result, or TimeoutError when ITS deadline passes
class ReliabilityGuard:
    def __init__(self, adapter, *, bulkhead, breaker, budget, retry_storm, timeouts, health, billing, probe_timeout_s)
    async def call(self, call: GuardedCall) -> AdapterResult
    async def probe(self, call: GuardedCall) -> ProbeOutcome
    async def observe(self, kernel_op_id, spec, binding, context) -> Observation
```

## Logic and conditions

**`ReliabilityGuard.call`: acquisition order (RELIABILITY §8, C4), Bulkhead first:**

1. `async with bulkhead.slot(provider)`. The slot is released on **every** exit: refusal, exception, cancellation.
2. `breaker.allow(provider)`. False → `AdapterResult("error", False, circuit_open)`, no adapter call.
3. `await budget.check(call)`. `BudgetStateError` **propagates**, after `record_ignored` releases any trial.
4. If `attempt > 1`: `retry_storm.allow_retry(provider, kernel_op_id)`. False → `record_ignored`, then
   `error retry_storm`, no call.
5. `await timeouts.run(adapter.call(..., call_meta=call.call_meta), call.timeout_s)`.
6. Then the breaker update (table below), `health.record(provider, status, latency_ms)` and
   `billing.record(call_meta, kernel_op_id, status)`, for every adapter outcome and never without one.

**Normalising the result:**

| Adapter outcome | Guard result | Breaker |
|---|---|---|
| `AdapterResult("ok", …)` | `ok` (data kept) | `record_success` |
| `error` with a known `ErrorClass` | `error`, `retryable = class in RETRYABLE` | `client_error` → `record_ignored`; else `record_failure` |
| `error` with an unknown class, or not an `AdapterResult` | `error adapter_defect`, not retryable | `record_failure` |
| adapter-reported `timeout`, the TimeoutManager deadline, or a `TimeoutError` escaping the adapter (CONF-023) | `timeout` (unknown outcome, probed later) | `record_failure` |
| any other exception escaping the adapter | `error adapter_defect`; **one** ERROR log with `attempt_id` and `kernel_op_id` as record attributes, **never the message** | `record_failure` |
| `CancelledError` while the adapter runs | propagates | `record_ignored` (trial released), slot released |

- Timeouts come only from the TimeoutManager or a `TimeoutError`, never from error text (sabotage
  `M10_timeout_from_text`).
- The breaker opens on **consecutive** failures only: a success resets the count; a client error neither counts nor
  resets.
- HALF_OPEN admits exactly one trial. Every trial outcome is recorded, including a trial refused later by the retry
  storm or the budget (`record_ignored`).

**`probe` and `observe`:** take their **own** bulkhead slot and `probe_timeout_s`. No breaker (an open breaker does not
block a probe), no budget. **Never raise**: `probe` falls back to `INCONCLUSIVE`, `observe` to
`Observation(..., matches_expected=None, error=...)`. Return the `ProbeOutcome` enum itself.

**`InProcessRetryStormGuard(max_retries, window_s, monotonic)`:** a sliding window **per (provider, operation)**. It
limits retries only; first attempts are never blocked.

**`MockAdapter(credentials)`:**

- `program(kernel_op_id, call="success", *, n=0, ms=0, probe="ledger", observe="ledger")`. The state is **per
  `kernel_op_id`**: `n` counts that operation's calls.
- Behaviours: `success`; `fail_500_then_success` / `rate_limit_429` / `connect_refused` (the first `n` calls fail
  retryably, then succeed); `auth_401`, `validation_422` (client error); `timeout_executed`; `timeout_not_executed`;
  `timeout_failed`; `verify_mismatch`; `slow` (`ms`); `raise_exception`.
- The side-effect ledger counts real executions per idempotency key. A key that already succeeded is not executed
  again (the provider deduplicates; sabotage `M10_mock_no_dedup`). `side_effects(key)` reads it.
- `calls` and `probes` list the `CallMeta` of every call and probe.
- Every call, probe and observe asks `credentials.credential(tenant_id, connection_id)`. A credential never appears in
  a result or a log.

**§21 S3:** components live behind the injected interfaces; there is **no module-level mutable state** in any S12 file
(the mock keeps its state on the instance).

## Traps

- The breaker counting client errors (sabotage `M10_client_error_counts`). The guard calls `record_ignored`; the
  breaker itself knows nothing about error classes.
- Breaker checked before the bulkhead (sabotage `M10_breaker_before_bulkhead`).
- A half-open trial never released after a refusal or a cancellation (`M10_trial_leak`, `M10_trial_held_on_cancel`):
  the breaker then refuses every later call.
- A probe routed through the breaker (`M10_probe_through_breaker`).
- A default probe that guesses NOT_EXECUTED (`M10_unsafe_default_probe`). It must be INCONCLUSIVE.
- Returning `ProbeOutcome.X.name` or upper-case strings. Return the enum member.
- `logger.error(str(exc))`. The case also checks that the message never leaks.

## Done when

- [ ] 64/64 in `M10_guard.py`; M01–M09 green; `pytest tests -q` green.
- [ ] `owner_certify_s12.py --milestone M10`: all PASS, sabotage 10/10.
