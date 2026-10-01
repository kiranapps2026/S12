# M9: BudgetReserver (gate commit F) ⚙ (built)

| | |
|---|---|
| Status | Built in `32fa999` (with `check_fence` split out of `fenced_write`). Golden 17/17, x5 (C-M9 PASS), sabotage 4/4. S12-S011 held after an OWN-08 fix (module tables immutable) |
| Gate | C3 (per step; availability; lock the tenant row; insert only if available ≥ cost), C14 (LOCKED resolved only by a probe, verification or dead-letter outcome, never a timer), C31 (the reserver is the **only** writer of budget state; one fenced write and one legal transition per operation), C33 (period start from database time, UTC; the step ↔ reservation link in one transaction), suite 4; invariants I1, I2, I5, I12 (non-dead-letter parts) |
| Golden | `tests_golden/s12/M09_budget.py`: 17 cases, 13 functions; 5 consecutive runs |
| Sabotage (4) | `M09_all_periods_count`, `M09_commit_from_reserved`, `M09_lock_in_own_transaction`, `M09_no_tenant_lock` (helper `_budget_base.py`) |

## Files (as built)

`src/adapters/postgres/budget_reserver.py` (a prototype file, reworked):

- `Reservation(reservation_id, status, reason)` (frozen, :62). When exhausted: `reservation_id` is None and
  `reason` is `"budget_exhausted"`.
- `PostgresBudgetReserver(database)` (:68):

```python
async reserve(holder, *, user_id, step_id, cost) -> Reservation                        # :72
async lock(holder, reservation_id, *, reason, connection=None) -> None                 # :98
async commit(holder, reservation_id, *, reason, connection=None) -> None               # :102
async release(holder, reservation_id, *, reason, connection=None) -> None              # :106
async status(tenant_id, reservation_id) -> str | None                                  # :110
```

`src/adapters/postgres/budget.py` (frozen, shared with S8): `AVAILABLE_SQL`, `PERIOD_START_SQL`.

## Logic and conditions

**Availability (C3, C33):**

```text
available = tenants.budget_pool − Σ cost of the tenant's reservations
            with status in (reserved, locked, committed)
            and created_at >= the start of the CURRENT period
period start = date_trunc(day | week | month by tenants.budget_period, now() AT TIME ZONE 'UTC')
```

**`reserve`, inside `fenced_write` for the holder's execution:**

1. **Lock the tenant row**. Without the lock, concurrent reservations over-reserve (sabotage
   `M09_no_tenant_lock`).
2. Lock the step and check it belongs to the holder's execution (`LookupError` otherwise).
3. If the step already has a **live** reservation (`reserved` or `locked`), return it (idempotent per step).
4. `available < cost` → `Reservation(None, None, "budget_exhausted")`, **nothing written**.
5. Insert `reserved`, set `execution_steps.reservation_id` **in the same transaction** (C33), and log
   `None → reserved` (reason `reserved`).

`cost` must be a non-negative int.

**`lock` / `commit` / `release`:**

- One Appendix A.3 move each, validated with its reason (`transitions.validate`) and logged.
- An illegal move raises `IllegalStateTransition` and writes nothing. **`commit` only from `locked`** (sabotage
  `M09_commit_from_reserved`). A disallowed reason is rejected.
- A stale holder raises `FencedOut` and writes nothing.
- **With `connection=`** (a connection inside the caller's `fenced_write` for the same holder), the move **joins
  that transaction** and runs `check_fence` there. Appendix A.2 requires the step's `pending → running` and its
  reservation's `reserved → locked` in **one** transaction (I-3; sabotage `M09_lock_in_own_transaction`).

| From | To | Allowed reasons (Appendix A.3, exact) |
|---|---|---|
| `reserved` | `locked` | `step_started` |
| `reserved` | `released` | `budget_released_before_start`, `preflight_failed`, `run_cancelled` |
| `locked` | `committed` | `step_completed`, `dead_letter_resolved_executed`, `dead_letter_resolved_undetermined`, `dead_letter_abandoned` |
| `locked` | `released` | `step_failed`, `probe_not_executed`, `no_dispatch_marker`, `dead_letter_resolved_not_executed` |

The table comes from `transitions.py` at `f4a8d5f`. Never a timer: a LOCKED reservation is resolved only by an
outcome (C14).

**Invariants:**

- **I1:** per tenant and period, reserved + locked + committed ≤ pool.
- **I2:** no `reserved` reservation for a terminal run; a `locked` one only under D4.
- **I12** (non-dead-letter parts): a non-terminal step has at most one live reservation.

**Concurrency:** 20 concurrent reservations against a small pool never over-reserve (5 runs). Released budget is
available again. Only the current period counts (boundary test).

## Sabotage

| Patch | Breaks |
|---|---|
| `M09_no_tenant_lock` | availability read without the tenant row lock |
| `M09_all_periods_count` | every period counts, not just the current one |
| `M09_commit_from_reserved` | `reserved → committed` shortcut |
| `M09_lock_in_own_transaction` | `lock` ignores the caller's connection (I-3 broken) |

## Later additive changes (do not break M09)

- M10: `reservation(tenant_id, reservation_id)`, a read used by the guard's `BudgetTracker` (C31: a read-only
  precondition, it never writes).
- M17: `settle_dead_letter_reservation(conn, …)`, which settles a LOCKED reservation inside a dead-letter
  resolution.
- The reserver stays the only writer of `budget_reservations`.

## Traps

- A `tenant_budget` table; reserving per execution; committing from RESERVED; releasing LOCKED budget on a timer
  (`test_no_tenant_budget_table_and_no_timer_release`).

## Regression checklist

- [ ] 17/17, 5 runs in a row; 4 patches caught; I1, I2, I12 after a full lifecycle.
