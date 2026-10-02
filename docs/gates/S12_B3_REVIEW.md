# B3 golden review (M10–M14)

2026-09-30, drafted on the owner's instruction "draft B3". **Self-review**: the drafter will also implement B3, so this
does not replace an independent review; it records how every file was validated and what needs a ruling before pinning.

## Validation (every file)

Each file was run three ways: red on `s12-work` (for the right reason: missing modules, not test errors), green on a
scratch reference implementation (a detached worktree in the session scratchpad; nothing of it is in `src/`), and
under every sabotage patch (each must turn an assertion red, never a setup error). All 15 golden files M01–M14 pass
together on the reference (672 cases: 489 for M01–M09, 183 for B3), the frozen `tests/` suite passes on it (836), and
the five B3 files passed 10 consecutive reference runs. (The first draft of this page said 677 cases for M01–M14; the
recount for that version is 647 = 489 + 158.)

| File | Cases | Red on `s12-work` | Reference | Sabotage caught |
|---|---|---|---|---|
| `s12/M10_guard.py` | 64 | 63 fail, 1 standing rule passes (no module-level mutable state) | 64 / 64 | 10 / 10 |
| `s12/M11_idempotency_retry.py` | 46 | 45 fail, 1 passes (invariants of an empty schema) | 46 / 46 | 10 / 10 |
| `s12/M12_loop.py` | 33 | 29 fail, 4 pass (prototype `topological_order`, no task scheduling) | 33 / 33 | 8 / 8 |
| `s12/M13_probe.py` | 13 | 13 fail | 13 / 13 | 4 / 4 |
| `s12/M14_revocation_cancel.py` | 27 | 27 fail | 27 / 27 | 7 / 7 |

Fixtures changed with B3: `certified_state(chain=[...])` certifies any linear chain; the invariant checker gains I16
(M12), I6 and the C13 condition (M13), I14 (M14). M01–M09 stay green on `s12-work` with the new fixtures.

## Defects caught while drafting (before pinning)

| Where | Finding | Fix |
|---|---|---|
| B2 M08 + `admission_control.py` | an exhausted admission was mapped to `admission_rejected`; §8 step 1 and C22 say `admission_exhausted` | DEF-005, fixed in 2cd2f9d |
| M10 draft | the mock mode `"none"` would force a bare state literal (C28, M04) | renamed `"default"` |
| M11 draft | a fenced-out case ran on a step with a legitimate ledger hit (no fenced write, false failure); D + `safe` pinned to 1 attempt | case uses a step without a row; D + safe = 2 (RELIABILITY) |
| M11 (amended in M12) | no `step_attempt` / `ProviderCalled` events, so I16 could not be checked from the ledger | events pinned (C24, I16) |
| M12 draft | the loop may not name `runtime_type` (M08a RD-9 scan) although it carries the binding's runtime list (CONF-019) | the context is built through `eligibility`; stated in the docstring |
| M12 draft | tests read only the loop's in-memory result, so a sabotage persisting other states survived | every loop result must equal the persisted rows |
| M12 / M13 drafts | a shared module schema was mutated (a dropped FK); a missing workspace FK; `fetchrow` on the fixture | rewritten |
| M13 draft | IRREVERSIBLE / D chains cannot be certified here (S10 requires a confirmation) | the no-retry path is tested with `retry_safety = never` (same ceiling path, M11 matrix) |
| M14 draft | certified states share global ids (`user-1`, `ws-1`, `conn-1`), so the live check of a second tenant read the first tenant's rows | per-tenant user, workspace and connection |
| reference | a module-level list in new code | caught by M10's §21 S3 rule (the S0–S11 OWN-08 scan skips `s12_*`) |

## Expert re-review (second pass)

The owner asked for a second, deeper pass over B3 ("expert and enterprise level… fail proof… guard drills… the flows
from previous steps"). Every draft was re-read against the gate clause by clause, with one question per case: which
wrong implementation would still pass? 25 cases and 7 sabotage patches were added; 3 rulings were opened.

| File | Added cases (the defect each one catches) |
|---|---|
| M10 | an adapter defect raises exactly one ERROR alert carrying `attempt_id` and `kernel_op_id`; the breaker opens on *consecutive* failures only (a success resets, a client error neither counts nor resets); a half-open trial refused by the retry storm is released; a call cancelled mid-flight (`CancelledError`) releases its trial and its slot, so the breaker is never stuck half-open; the retry-storm window slides and is per (provider, operation); a `GuardedCall` for two tenants, attempt 0 or a non-positive deadline cannot be built (C34, fail closed) |
| M11 | a ledger row under the step's key written by another operation is an `IdempotencyConflict`, never a cached result; a result whose ledger write is fenced out is discarded (no row; the side effect happened once; the new owner probes); a `BudgetStateError` propagates before any provider call |
| M12 | the section 8 order including the lease (acquired before the reservation, released after the commit); a run that is not RUNNING is left untouched; a run owned by another runtime is never taken over; a takeover between steps stops the loop with no further write; a lease is never acquired once ownership has moved (atomic check inside `acquire`); a takeover during a provider call discards the result, leaves the step RUNNING with its budget LOCKED for the new owner, and releases the lease `fenced_out`; a tampered plan (params changed; plan row re-hashed but the manifest not; undecodable) executes nothing, cancels every step `run_dead_lettered` and raises an ERROR alert |
| M13 | a probe EXECUTED_SUCCESS that fails verification fails the step (`verification_failed`, episode `verified_fail` / VERIFIED_FAIL, dependents skipped); a failure found in the ledger at probe time fails the step without a probe (`ledger_hit_failure`); inconclusive probes back off between attempts, never after the last |
| M14 | a repeated cancel request is idempotent (the first time is kept) and a finished run cannot be cancelled |

Defects the second pass found (all in the scratch reference, none in `src/`):

| Where | Finding | Fix |
|---|---|---|
| reference loop | the rewrite for M12 had dropped two protections the prototype loop had: the plan digest check on load (gate §7.3) and `FencedOut` handling (§8 step 8: stop at once); a fenced-out loop crashed out holding its lease | both restored and pinned (M12); CONF-034 |
| reference loop + M07 `acquire` | between steps the loop holds no lease, and `acquire` takes ownership from any holder when no usable lease exists: an in-line loop could take an execution back from the runtime that took it over | `acquire(..., holder=)` checks ownership under its lock (additive; M07 unchanged); CONF-033 records the sweeper rule for M19 |
| reference runner and probe | a ledger row of another `kernel_op_id` under the step's key was accepted as a hit | `IdempotencyConflict` (M11) |
| reference guard | a cancelled call left its half-open trial held (the breaker refused every later call) | released with `record_ignored` (M10) |
| reference store | a `cancel_requested` method attached to the class at import time (module-level mutation) | an ordinary method |
| cross-milestone flow | `tests_postgres/test_step_loop.py` and `test_chain_full_stack.py` test the prototype loop and stop importing once M12 lands (the M9 log reports tests_postgres 330) | CONF-035: port them at M12, never delete |

## Rulings needed (recorded in S12_RECORDS.md)

| ID | Question | Proposal |
|---|---|---|
| CONF-021 | frozen `KernelResult` has no error class | adapters and the guard use the frozen `AdapterResult` |
| CONF-022 | breaker per (provider, operation) vs frozen S8 `state(provider_id)` | per provider in this phase |
| CONF-023 | half-open 4xx; an adapter's own `TimeoutError` | release the trial; `timeout` (probed) |
| CONF-024 | key `request_id:step_id` vs `request_id:plan_step_id` | `plan_step_id` |
| CONF-025 | ledger rows for exhausted retries / guard refusals | none |
| CONF-026 | no `execution_events` table defined | migration 016, append-only, RLS |
| CONF-027 | live admission snapshot and pre-flight sources have no milestone | injected; owner assigns a milestone |
| CONF-028 | episode close for the read re-execution path | NOT_EXECUTED, evidence `read_reexecution_safe` |
| CONF-029 | when RECONCILING is entered | never by the in-line loop; recovery only; C13 as an invariant |
| CONF-030 | credential validity source | `CredentialProvider.credential_valid` |
| CONF-031 | "the check that failed" vs frozen `Revoked(reason)` | reason in the event, check name in the log |
| CONF-032 | gate 8 REJECT (C30, §10, golden M08) vs "provider unavailable → QUEUE/DELAY" (C35) | gate 8 DELAY; M14 pins only "no revocation for an outage" until ruled |
| CONF-033 | an in-line run has no usable lease between steps; `acquire` takes over from anyone | the loop never takes over (`acquire(holder=)`); the M19 sweeper skips its own runtime's executions |
| CONF-034 | plan digest check on the in-line load; which stored hash; A.1 has no direct `running → dead_letter` | both hashes; steps `run_dead_lettered`, alert, consolidation decides DEAD_LETTER (M16) |
| CONF-035 | prototype loop tests in `tests_postgres/` (not named by the autopilot rules) | port them at M12 like CONF-011's `tests/` prototype tests |

## Known gaps, left as they are (reasons)

| Gap | Why it stays |
|---|---|
| Crash cases (suite 6 A–C, suite 16b crash recovery, the dispatched-without-record probe path in recovery) | M19 (crash recovery and fault injection) |
| Verification is an injected verdict; VERIFICATION episodes | M15 |
| Consolidation is an injected callable; runs stay RUNNING after the loop unless cancelled | M16 |
| No `dead_letters` row at DEAD_LETTER | M17 |
| Checkpoints (§8 steps 7, 11) and lease renewal at TTL/3 are not asserted | no M12 card item; M19 / M20 exercise them |
| IRREVERSIBLE and non-idempotent D steps in the loop | the certified fixture cannot confirm them; their ceilings are pinned in M11 |
| S5 logs: correlation attributes are asserted, not the JSON formatter | the formatter is deployment configuration |
| A plan-integrity sabotage patch | the digest function is shared with entry (M06), so no public-interface patch can weaken only the load check; the three tamper cases were mutation-checked on the reference instead (each fails when the check is removed; the manifest case fails when only the plan row's hash is compared) |
| `IdempotencyConflict` raised from the probe path | the reference raises it (same rule as M11); not pinned separately, M11 pins the rule at the runner |

## Sabotage patches added

M10: `M10_breaker_before_bulkhead`, `M10_client_error_counts`, `M10_trial_leak`, `M10_budget_unchecked`,
`M10_timeout_from_text`, `M10_probe_through_breaker`, `M10_unsafe_default_probe`, `M10_mock_no_dedup`
(helper `_guard_base.py`). M11: `M11_key_per_attempt`, `M11_irreversible_retried`, `M11_expired_counts`,
`M11_conflict_ignored`, `M11_no_dispatch_marker`, `M11_hit_ignored`, `M11_timeout_retried`, `M11_marker_not_checked`.
M12: `M12_topology_ignored`, `M12_lock_in_own_transaction`, `M12_dependents_cancelled.sql`, `M12_ledger_mutable.sql`,
`M12_consolidate_again`, `M12_log_without_ids`. M13: `M13_ledger_not_consulted`, `M13_uncertain_as_failure`,
`M13_inconclusive_guessed`, `M13_retry_beyond_ceiling`. M14: `M14_live_check_allows_all`, `M14_validity_ignored`,
`M14_kill_switch_as_revoked`, `M14_no_check_before_call`, `M14_anyone_can_cancel`, `M14_live_check_writes`.
Second pass: `M10_trial_held_on_cancel`, `M10_call_unchecked`, `M11_foreign_hit_accepted`, `M11_fenced_result_kept`,
`M12_acquire_steals`, `M12_lease_kept_when_fenced`, `M14_cancel_time_moves`.
