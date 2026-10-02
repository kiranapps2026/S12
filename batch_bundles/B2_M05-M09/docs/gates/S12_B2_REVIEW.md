# B2 golden review (M5–M9, M8a)

2026-09-30, on the owner's "review B2". **Self-review**: the reviewer also drafted B2 and will implement it, so this
does not replace an independent review by the test-author session; it is an adversarial pass of every golden file
against its plan §4 card and the gate text. Each fix was re-validated: red on `s12-work`, green on a scratch reference
(all 486 M01–M09 cases together), every sabotage patch caught.

## Fixed (defects in the drafts)

| File | Finding | Gate | Fix |
|---|---|---|---|
| M09 | Every reserver operation opened its own transaction, so `pending → running` and `reserved → locked` could never be one transaction | Appendix A.2 guard, I-3 | `lock/commit/release(..., connection=None)` join the caller's `fenced_write`; new case `test_lock_joins_the_callers_transaction`; sabotage `M09_lock_in_own_transaction.py` |
| M07 | Nothing stopped a second Worker Runtime from leasing an execution whose lease is still usable (the ownership compare-and-set always succeeds: the sequence only grows) | WORKER_LIFECYCLE §14 (transfer on failover), suite 17 "one owner at a time" | acquisition refused while the execution has a usable lease; new case `test_a_live_execution_cannot_be_taken_over`; sabotage `M07_steal_live_execution.py` |
| M08a | I18 was only checked on the pure filter, never through selection and a real lease ("filter after locality scoring" trap untested) | I18, §8 step 2 | two cases: live candidates → filters → selection → `PostgresLeaseManager`; only the eligible worker is leased; none eligible → `no_worker`, zero leases |
| M06 | "manifest persisted byte-identical to S11's" skipped `created_at` | M6 card | `created_at` compared with the S11 value |

Counts after the fixes: M05 30, M06 23, M07 15, M08 36, M08a 49, M09 17 (170 B2 cases; 486 with B1).

## Rulings (owner, 2026-09-30)

CONF-015, CONF-016 and CONF-018 accepted as proposed; CONF-017 ruled DELAY: gates 9 and 11 now DELAY in golden M08
(39 cases, reference 39/39, 4 sabotage patches including `M08_backpressure_rejects.py`); the DELAY retry case uses a
snapshot instead of swapping `evaluate`. DEF-003 is still the owner's decision.

## Needed a ruling (recorded in S12_RECORDS.md)

| ID | Finding | Proposal |
|---|---|---|
| CONF-017 | Gates 9 (`db_pool_pressure`) and 11 (`system_overloaded`) are REJECT in the golden, which cancels an admitted run under momentary load; §11 calls backpressure a DELAY | make them DELAY (bounded retry, then `admission_exhausted`); 2 golden cases change |
| CONF-018 | `confirmation_unavailable` is a reason code the gate does not name | accept (fail closed, like `binding_unavailable`) |
| CONF-015, CONF-016 | (from drafting) AdmissionDecision shape; filter-14 inputs | as proposed there |
| DEF-003 | (from drafting) frozen confirmation store has no `tenant_id` predicate | owner: §19.3 change control or accept RLS as the guard |

## Known gaps, left as they are (reasons)

| Gap | Why it stays |
|---|---|
| M5 does not re-run the certified S0–S11 confirmation tests (`tests/stages/test_s10_confirmation.py`) against the PostgreSQL store; it has its own matrix of the same behaviours | those tests are bound to the in-memory store; the matrix covers once-only, wrong user/hash/tenant, unknown id, expiry, reject and required ids over both stores |
| M8/M8a: per-step admission decisions and the `no_worker` filter reasons go to an injected ledger; nothing persists them | no execution ledger table exists yet; persistence and the `no_worker` event content belong with the loop (M12 golden, batch B3) |
| M8a fixes `workers.capability_profile` as a JSON array of capability ids | DATABASE.md says only `JSONB`; any shape works if recorded; an array is the simplest the filter needs |
| M08 `test_delay_is_handled_like_queue` swaps the module's `evaluate` to produce a DELAY | no gate produces DELAY unless CONF-017 is ruled that way; then the case can use a snapshot instead |
| `fixtures/certified.py` imports `tests/fixtures/{pipeline,multi,scenarios}.py`, which the golden pins do not cover | they are S0–S11 test fixtures, which the S12 autopilot does not allow Fable to change; S12-PIN cannot enforce it without a certifier change |
