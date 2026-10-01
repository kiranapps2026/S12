# M11: idempotency ledger and retry (gate commit G, part 2) ⚙

| | |
|---|---|
| Gate | §8 step 8, C9, C17, C34, C35 (connect phase), suites 6 (non-crash) and 7; MUTATION_SAFETY §3, §5 |
| Rulings | CONF-024 (key `{request_id}:{plan_step_id}`), CONF-025 (ledger rows only for results the adapter produced) |
| Golden | `tests_golden/s12/M11_idempotency_retry.py`: 46 cases |
| Sabotage (10) | `M11_conflict_ignored`, `M11_expired_counts`, `M11_fenced_result_kept`, `M11_foreign_hit_accepted`, `M11_hit_ignored`, `M11_irreversible_retried`, `M11_key_per_attempt`, `M11_marker_not_checked`, `M11_no_dispatch_marker`, `M11_timeout_retried` |
| Reference | `src/contracts/idempotency.py`, `src/adapters/postgres/{idempotency,step_attempts}.py`, `src/engine/stages/s12_execute/{retry_policy,attempts}.py` (108 lines) |

## Files

| File | Action |
|---|---|
| `src/contracts/idempotency.py` | **new**: `step_idempotency_key`, `attempt_id`, `LedgerRecord`, `IdempotencyConflict` |
| `src/adapters/postgres/idempotency.py` | **new**: `PostgresIdempotencyLedger(database)` with `lookup`, `store` |
| `src/adapters/postgres/step_attempts.py` | **new**: `PostgresStepAttempts(database)` with `dispatched`, `mark_dispatched` |
| `src/engine/stages/s12_execute/retry_policy.py` | **new**: `ceiling`, `max_attempts`, `backoff_s` |
| `src/engine/stages/s12_execute/attempts.py` | **new**: `StepAttempt`, `AttemptDeps`, `AttemptOutcome`, `run_attempts` |

Migration 015 already holds `idempotency_ledger` (with `idempotency_key TEXT PRIMARY KEY`, forced RLS) and
`execution_steps.dispatched_attempt`. **No migration in M11.**

## Interface (exact)

```python
# contracts/idempotency.py
def step_idempotency_key(request_id, plan_step_id) -> str        # f"{request_id}:{plan_step_id}"  (CONF-024)
def attempt_id(step_index, attempt) -> str                        # f"att-{step_index}-{attempt}"
@dataclass(frozen=True) class LedgerRecord: kernel_op_id; kind  # "success" | "failure"
                                            result              # AdapterResult
class IdempotencyConflict(Exception)

# adapters/postgres/idempotency.py
class PostgresIdempotencyLedger:
    async def lookup(self, tenant_id, idempotency_key) -> LedgerRecord | None
    async def store(self, holder, *, idempotency_key, kernel_op_id, result, ttl_s) -> None

# adapters/postgres/step_attempts.py
class PostgresStepAttempts:
    async def dispatched(self, tenant_id, step_id) -> int | None
    async def mark_dispatched(self, holder, step_id, attempt) -> None

# engine/stages/s12_execute/retry_policy.py
def ceiling(mutation, retry_safety) -> int
def max_attempts(mutation, retry_safety, step_max=None) -> int
def backoff_s(mutation, attempt, base_s) -> float

# engine/stages/s12_execute/attempts.py
@dataclass(frozen=True) class StepAttempt: request_id; plan_step_id; step_index; step_id; kernel_op_id; params;
    mutation; retry_safety; step_max_attempts; reservation_id; timeout_s; binding; context
@dataclass(frozen=True) class AttemptDeps: guard; ledger; attempts; live; events; sleep; backoff_base_s; ledger_ttl_s
@dataclass(frozen=True) class AttemptOutcome: kind; result; attempts; cached; reason
async def run_attempts(step, holder, deps, *, first_attempt=1) -> AttemptOutcome
```

## Logic and conditions

**Ledger: `lookup`.** Filter on **both** `tenant_id` and `idempotency_key` (C34). An expired row (`expires_at <=
now()`) is `None`: it counts as no record and never authorises a blind call (MUTATION_SAFETY §5).

**Ledger: `store`, one `fenced_write`, in the caller's tenant transaction. No RLS bypass:**

1. Check the fence. A stale holder raises `FencedOut` and nothing is written.
2. `INSERT INTO idempotency_ledger … ON CONFLICT (idempotency_key) DO NOTHING RETURNING …`
3. A row returned: done.
4. Nothing returned: `SELECT` the key **under the tenant's own RLS**.
   - Visible, same `kernel_op_id`, same kind: a **hit**, return without error.
   - Visible, other `kernel_op_id` or other kind: raise `IdempotencyConflict`.
   - **Not visible** (another tenant owns the key; the primary key is global): raise `IdempotencyConflict`.
5. A failure row stores the error **class**, never the provider body (M18 checks it later).

Do not catch `UniqueViolationError` in the middle of the transaction: it aborts the transaction. `ON CONFLICT DO
NOTHING` avoids that.

**Retry ceilings (`ceiling`):**

| Mutation / retry_safety | Ceiling |
|---|---|
| IRREVERSIBLE, or `retry_safety = never` | 1 (never retried) |
| R | 3 |
| W | 2 |
| D | 2 |

`max_attempts = min(ceiling, step_max)`. `backoff_s > 0`: D is fixed, the others grow exponentially.

**`run_attempts`, per attempt `n`, in this order:**

1. **Live check** (`deps.live.check(...)`). Revoked → kind `revoked` with the reason, no call. (The full loop
   behaviour is M14.)
2. **Ledger lookup.**
   - A hit → the cached kind (`cached=True`), event `idempotency_hit` (`step_id`, `attempt_id`, `kind`), no call.
   - A row under the key whose `kernel_op_id` is not the step's → raise `IdempotencyConflict`, never a hit
     (sabotage `M11_foreign_hit_accepted`).
3. **Dispatch marker already at `n` without a ledger row** → kind `uncertain`, reason `dispatched_without_record`,
   no call (sabotage `M11_marker_not_checked`).
4. `mark_dispatched(holder, step_id, n)` (a fenced write, no state transition), then event `step_attempt` (`step_id`,
   `attempt_id`, `attempt`; C24: a retry is an event, not a transition).
5. **Guarded call** with `CallMeta(key, attempt_id(step_index, n), uuid4(), tenant_id)`. The key is the **same on
   every attempt** (sabotage `M11_key_per_attempt`); `provider_call_id` is a fresh UUID each time.
6. When the adapter was invoked (not `circuit_open` / `retry_storm`): events `ProviderCalled` (`step_id`,
   `attempt_id`, `provider_call_id`, `kernel_op_id`) and `ProviderReturned` (`…`, `status`).

**What happens after the call:**

| Result | Ledger | Outcome |
|---|---|---|
| `ok` | store success | `success` |
| `timeout` | none | `uncertain`, reason `timeout`. **Never retried** (sabotage `M11_timeout_retried`); M13 probes it |
| non-retryable error the adapter produced | store failure (class only) | `failure` |
| `circuit_open` / `retry_storm` (adapter never called) | **none** (CONF-025) | `failure` |
| retryable error, attempts left | none | `await sleep(backoff_s(...))`, then attempt `n + 1`; the step stays RUNNING |
| retryable error, retries exhausted | **none** (CONF-025) | `failure` |

- `FencedOut` and `BudgetStateError` propagate.
- A result whose ledger write is fenced out is **discarded**: no row, and the new owner learns the outcome by
  probing (sabotage `M11_fenced_result_kept`).
- `not_dispatched` (connect refused) is a retryable definitive failure and **never** opens an episode.

## Traps (from the last attempt at this milestone)

- **Deleting or editing golden cases to get green.** Forbidden; the pins and the certifier catch it.
- Bypassing RLS to detect a cross-tenant conflict. Use the primary key and the "not visible" rule above.
- Widening "cached" to every non-pending status, dropping the TTL filter, or splitting `store` across connections.
  The table above is the whole contract; anything else needs a gate citation.
- A mock counter shared across all operations. Count per `kernel_op_id`.
- Passing a connection positionally into a parameter (the earlier `claim(conn, …)` bug). Use keyword arguments for
  every ledger call.

## Done when

- [ ] 46/46 in `M11_idempotency_retry.py` **with the file byte-identical to the pin**; M01–M10 green; invariant I4
      passes.
- [ ] `owner_certify_s12.py --milestone M11`: all PASS, sabotage 10/10.
