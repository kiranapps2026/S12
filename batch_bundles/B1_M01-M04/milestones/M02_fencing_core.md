# M2: `fenced_write()`, repositories, transition log, settings (gate commit C, part 2) ⚙ (built)

| | |
|---|---|
| Status | Built in `838ebcf` (+ `check_fence` split in M9 `32fa999`). Golden 18/18, x5 (C-M2 PASS), sabotage 3/3 |
| Gate | C5 (`fenced_write`, `FencedOut`), C24 (reason on every transition; log columns), C25 (per-execution fence, no session middleware), C34 (tenant filter), C37 (timeout ordering), §21 S1 (one settings object), S3 (no module state); invariant **I5 starts here** |
| Rulings | CONF-011 (frozen = tag minus the prototype list; prototype repositories reworked here) |
| Defect | DEF-001 (admission logged non-Appendix-A reasons; fixed in M6) |
| Golden | `tests_golden/s12/M02_fencing_core.py`: 18 cases, 14 functions; runs 5 consecutive times |
| Sabotage (3) | `M02_check_without_lock`, `M02_settings_unvalidated`, `M02_skip_fence_check` |

## Files (as built; line numbers at `f4a8d5f`)

| File | Interface |
|---|---|
| `src/adapters/postgres/fencing.py` | `FenceHolder(tenant_id, execution_id, runtime_instance_id, fence_token)` (frozen, :27); `async check_fence(connection, holder)` (:35); `async fenced_write(database, holder, write)` (:44) |
| `src/adapters/postgres/transition_log.py` | `async log_transition(connection, *, tenant_id, machine, entity_id, from_state, to_state, reason, runtime_instance_id, fence_token, execution_id=None)` (:11) |
| `src/engine/stages/s12_execute/settings.py` | `ExecutionSettings` (:34); `from_env(mapping)` (:59) |
| prototype repositories | `adapters/postgres/{admission,budget_reserver,execution}.py` write through `fenced_write`; every query filters on `tenant_id` |

## Logic and conditions

**`fenced_write(database, holder, write)`:**

1. Open **one** tenant transaction (`database.tenant_transaction(holder.tenant_id)`, which sets
   `app.current_tenant` for RLS).
2. `check_fence`: `SELECT 1 FROM execution_ownership WHERE tenant_id = $1 AND execution_id = $2 AND
   runtime_instance_id = $3 AND fencing_token = $4 FOR SHARE`. The **row lock** makes a concurrent takeover wait
   until this write commits.
3. No row → raise `contracts.step_execution.FencedOut` and **do not call `write`**.
4. Otherwise `return await write(connection)`. An exception from `write` rolls back everything.

| Holder | Result |
|---|---|
| current token and runtime | write runs |
| stale token, other runtime, other tenant, or no ownership row | `FencedOut`, 0 rows |
| a takeover starts while a fenced write is open | the takeover waits for it, then the old owner is fenced |

**Joining a caller's transaction:** an operation called with the caller's `connection` runs `check_fence(connection,
holder)` again there (M9's `lock/commit/release(..., connection=)`). It never opens a second transaction.

**`log_transition`:** inserts **exactly one** `state_transitions` row with from, to, reason, `runtime_instance_id`,
`fence_token`, and `execution_id` when given. Callers validate first with `transitions.validate` (M3). I5 then
checks every log row against Appendix A.

**`ExecutionSettings.from_env`:**

| Env var | Field |
|---|---|
| `S12_ADAPTER_CLIENT_TIMEOUT_S` | `adapter_client_timeout_s` |
| `S12_STEP_TIMEOUT_S` | `step_timeout_s` |
| `S12_PROBE_TIMEOUT_S` | `probe_timeout_s` |
| `S12_LEASE_TTL_S` | `lease_ttl_s` |
| `S12_LEASE_RENEWAL_INTERVAL_S` | `lease_renewal_interval_s` |
| `S12_QUOTA_RETRY_MAX`, `S12_QUOTA_BACKOFF_S`, `S12_QUOTA_RETRY_AFTER_MS` (optional, M8a) | quota retry (defaults 3, 0.05, 1000) |
| `S12_RECOVERY_SWEEP_INTERVAL_S` (optional) | `recovery_sweep_interval_s` (default 10, must be < 30). **Not on `s12-work` yet: M19 adds it** (M21 then tests it) |

Validation at construction raises `ValueError`:

- a required value is missing, not a number, or not > 0;
- `adapter_client_timeout_s >= step_timeout_s` or `probe_timeout_s >= step_timeout_s`;
- `lease_ttl_s < 3 × lease_renewal_interval_s`.

The boundary (`lease_ttl_s == 3 × interval`) is allowed.

**Architecture cases:**

- `fencing.py` and `transition_log.py` exist as S12 code.
- Every S12 SQL query filters on `tenant_id`.
- S0–S11 code is unchanged since the tag. This is a standing rule for every later milestone.

## Sabotage

| Patch | Breaks | Why it matters |
|---|---|---|
| `M02_skip_fence_check` | writes without checking | a stale owner overwrites the new owner's state |
| `M02_check_without_lock` | the fence read without `FOR SHARE` | a takeover commits between the check and the write |
| `M02_settings_unvalidated` | inverted timeouts accepted | the adapter timeout outlives the step deadline (C37) |

## Traps

- A "session middleware" fence (C25 forbids). The fence is per execution, per write.
- Singletons or module-level state at import time (§21 S3; M10 scans it later).
- A fence check in one transaction and the write in another.
- A repository query without `tenant_id` in its `WHERE`, even under RLS (C34).

## Regression checklist

- [ ] 18/18, five runs in a row; the 3 patches caught.
- [ ] New durable writes in later batches go through `fenced_write`. M21 scans for SQL writes on execution tables
      outside it. The designed exceptions (no live owner to fence) are: `admission.py` (the §7.2 transaction creates
      the ownership row), `cancellation.py` (C16, the user's request), M17 `create_rollback` and
      `settle_dead_letter_reservation` (terminal run, D4/C27). Each still uses a tenant transaction and
      `transitions.validate`.
