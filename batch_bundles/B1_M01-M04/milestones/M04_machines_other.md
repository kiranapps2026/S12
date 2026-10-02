# M4: state machines II (lease, worker, dead letter, episode, confirmation, breaker) ⚙ (built)

| | |
|---|---|
| Status | Built in `8f38edb`. Golden 79/79, sabotage 2/2. The same commit removed the bare state literals from the prototype loop, guard, budget reserver, admission and circuit breaker (DEF-002 recorded the remaining loop reasons for M12) |
| Gate | Appendix A.4–A.9 (A.5 = STATE_TRANSITIONS §4 exactly), C18, C21, C26, C28 (bare-literal architecture test), C37 |
| Rulings | CONF-012 (worker and confirmation list no reasons: any non-empty reason), CONF-013 (machine names exempt from the bare-literal rule; `DEAD_LETTER` stays forbidden) |
| Golden | `tests_golden/s12/M04_machines_other.py`: 79 cases, 11 functions |
| Sabotage (2) | `M04_closed_episode_moves`, `M04_expired_lease_renewed` |

## Files (as built)

| File | Change |
|---|---|
| `src/engine/stages/s12_execute/transitions.py` | machines `lease`, `worker`, `dead_letter`, `episode`, `confirmation`, `breaker`; `closed=True` makes every episode move illegal |
| `src/contracts/execution_states.py` | `CircuitBreakerState` (closed, open, half_open) |
| prototype loop, guard, budget reserver, admission, circuit breaker, worker handler | enums instead of bare literals |

## Logic and conditions

1. **Closed episodes are immutable.** `validate("episode", …, closed=True)` raises for every move (`closed_at` is
   set).
2. **An exhausted episode is not a transition.** It keeps status `pending_probe`; only `outcome = EXHAUSTED` and
   `closed_at` are written (C18).
3. **Episode creation** is `None → pending_probe` (reason `opened`). `none` is never a stored status; the M13
   log row is written through `ReconciliationStatus.NONE` as the "from" side only.
4. **A lease renews only while `active`.** `active → active` (`renewed`). An expired lease never renews (C26).
5. **Pause is not a worker state.** `paused_until` / `scheduled_activation_at` are columns and filters (C39).
6. **Worker states** are the frozen `WorkerStatus` values; any non-empty reason is accepted (CONF-012).
7. **The bare-literal rule (C28):** no string equal to a state value appears in S12 code outside the enums and
   migrations. Machine names are exempt (CONF-013).

## The machines (generated from `transitions.py` at `f4a8d5f`)

### Machine `lease` (created `None → active`, reason `acquired`)

| From | To | Allowed reasons |
|---|---|---|
| `active` | `active` | `renewed` |
| `active` | `expired` | `ttl_elapsed` |
| `active` | `released` | `fenced_out`, `run_terminal`, `work_complete` |

### Machine `worker` (no creation row: worker states are S0–S11 `WorkerStatus`)

| From | To | Allowed reasons |
|---|---|---|
| `ACTIVE` | `DRAINING` | any non-empty reason |
| `ACTIVE` | `TERMINATED` | any non-empty reason |
| `DRAINED` | `ACTIVE` | any non-empty reason |
| `DRAINED` | `TERMINATED` | any non-empty reason |
| `DRAINING` | `ACTIVE` | any non-empty reason |
| `DRAINING` | `DRAINED` | any non-empty reason |
| `REGISTERED` | `ACTIVE` | any non-empty reason |
| `REGISTERED` | `TERMINATED` | any non-empty reason |

### Machine `dead_letter` (created `None → pending`, reason `created`)

| From | To | Allowed reasons |
|---|---|---|
| `pending` | `resolved` | `human_resolved` |
| `pending` | `retrying` | `retry_started` |
| `retrying` | `abandoned` | `abandoned_after_retries` |
| `retrying` | `pending` | `retry_inconclusive` |
| `retrying` | `resolved` | `retry_resolved` |

### Machine `episode` (created `None → pending_probe`, reason `opened`)

| From | To | Allowed reasons |
|---|---|---|
| `pending_probe` | `reconciling` | `attempt_started` |
| `reconciling` | `confirmed_failure` | `executed_failure`, `ledger_hit_failure`, `not_executed`, `verified_fail` |
| `reconciling` | `confirmed_success` | `executed_success`, `ledger_hit`, `verified_pass` |
| `reconciling` | `pending_probe` | `inconclusive` |

### Machine `confirmation` (created `None → pending`, reason `created`)

| From | To | Allowed reasons |
|---|---|---|
| `pending` | `consumed` | any non-empty reason |
| `pending` | `expired` | any non-empty reason |
| `pending` | `rejected` | any non-empty reason |

### Machine `breaker`

| From | To | Allowed reasons |
|---|---|---|
| `closed` | `open` | `failure_threshold` |
| `half_open` | `closed` | `trial_success` |
| `half_open` | `open` | `trial_failure`, `trial_inconclusive` |
| `open` | `half_open` | `recovery_timeout` |


## Sabotage

| Patch | Breaks |
|---|---|
| `M04_closed_episode_moves` | a closed episode can still move (`closed_at` ignored) |
| `M04_expired_lease_renewed` | an expired lease renews (C26: never) |

## Traps

- Writing a state as a string literal (`"dead_letter"`, `"pending_probe"`) instead of the enum member.
- Treating EXHAUSTED as a status.
- Re-opening a closed episode instead of opening a new one.

## Regression checklist

- [ ] 79/79; 2 patches caught.
- [ ] `test_no_bare_state_literals_in_s12_code` passes after every later change. B3–B5 code is scanned too, and
      the B4 drafting tripped it twice (outcome and rollback strings equal to state names).
