# M5: PostgreSQL confirmation store and the C20 entry check (gate commit D, part 1) ⚙ (built)

| | |
|---|---|
| Status | Built in `77c26e2`. Golden 30/30, x5 (C-M5 PASS), sabotage 3/3 |
| Gate | C20, §14 "now in scope", suite 13; S0–S11 ruling R-Z |
| Rulings | CONF-003 (R-Z satisfied: `tenant_id`/`execution_id` reach the store as required arguments; no code change), CONF-010 (red-first per file: the store cases pass already), CONF-018 (`confirmation_unavailable` is an S12 entry DENY reason) |
| Open | **DEF-003** (owner): the frozen store's consume/expire/reject UPDATEs have no `tenant_id` predicate; forced RLS is the guard under the app role |
| Golden | `tests_golden/s12/M05_confirmation_store.py`: 30 cases, 14 functions; 5 consecutive runs |
| Sabotage (3) | `M05_accept_pending`, `M05_consume_read_then_update`, `M05_ignore_execution_id` |

## What M5 is (and is not)

The PostgreSQL confirmation store itself is **certified S0–S11 code** (`src/adapters/postgres/confirmations.py`,
**frozen**). Its cases pass already and stay as regression. M5 built the **S12 side of C20**: before admitting a run
whose plan needed a confirmation, check the store row really was consumed **for this run**. S10 logic is untouched.

## Files (as built)

| File | Interface |
|---|---|
| `src/contracts/confirmation_record.py` | `ConsumedConfirmation(status, execution_id, plan_hash, user_id)`; protocol `ConsumedConfirmationReader.read(confirmation_id, *, tenant_id)` |
| `src/adapters/postgres/confirmation_records.py` | `PostgresConsumedConfirmationReader(database).read(...)`: tenant-scoped; `None` when the row is not visible to that tenant |
| `src/engine/stages/s12_entry/confirmation.py` | `confirmation_denial(state, reader) -> str \| None`. Writes nothing |
| `src/engine/stages/s12_entry/checks.py` | `check_entry(..., confirmations=reader)` applies it **after** the numbered §7.1 checks |
| `src/engine/stages/s12_entry/admission.py` | `admit_run(..., confirmations=None)` passes it through |

## Logic and conditions

**`confirmation_denial(state, reader)`:**

| Situation | Result |
|---|---|
| the plan needed no confirmation | `None`; the reader is **not** read |
| the reader is missing, or `read` raises | `"confirmation_unavailable"` (fail closed, like `binding_unavailable`) |
| the row is not visible to the run's tenant, or `status != consumed`, or its `execution_id` ≠ `state.plan.execution_id`, or its `plan_hash` ≠ `state.execution_manifest.plan_hash` | `"confirmation_mismatch"` |
| consumed for this tenant, execution and plan hash | `None` (allowed) |

**The frozen store (regression cases):**

- It consumes exactly once.
- Mismatches consume nothing, and a genuine consume still works afterwards.
- An expired or rejected confirmation is never consumed.
- `save` requires both `tenant_id` and `execution_id`.
- The stored status is `consumed`, together with its execution.
- **20 concurrent consumers → exactly one winner**, under real transactions (5 runs).
- There is **no foreign key** from confirmations to `execution_runs` (C20 forbids it).

**A denial writes nothing** (`test_entry_check_writes_nothing`).

## Sabotage

| Patch | Breaks |
|---|---|
| `M05_accept_pending` | a never-consumed confirmation is accepted (status not checked) |
| `M05_ignore_execution_id` | a confirmation consumed for **another** run is accepted |
| `M05_consume_read_then_update` | read-then-update instead of one conditional UPDATE: several winners under concurrency |

## Traps

- Changing S10, or the frozen store, to make a case pass. Report it as a STOP (§19.3) instead; DEF-003 is the
  example.
- Adding a foreign key from confirmations to runs.
- Reading the store when no confirmation was needed.

## Regression checklist

- [ ] 30/30, 5 runs in a row; 3 patches caught.
- [ ] `adapters/postgres/confirmations.py` byte-identical to the tag (S12-FRZ).
