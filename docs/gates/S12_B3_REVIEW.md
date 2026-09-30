# B3 golden review (M10–M14)

2026-09-30, drafted on the owner's instruction "draft B3". **Self-review**: the drafter will also implement B3, so this
does not replace an independent review; it records how every file was validated and what needs a ruling before pinning.

## Validation (every file)

Each file was run three ways: red on `s12-work` (for the right reason: missing modules, not test errors), green on a
scratch reference implementation (a detached worktree in the session scratchpad; nothing of it is in `src/`), and
under every sabotage patch (each must turn an assertion red, never a setup error). All 15 golden files M01–M14 pass
together on the reference (677 cases); each B3 file passed 10 consecutive reference runs.

| File | Cases | Red on `s12-work` | Reference | Sabotage caught |
|---|---|---|---|---|
| `s12/M10_guard.py` | 55 | 54 fail, 1 standing rule passes (no module-level mutable state) | 55 / 55 | 8 / 8 |
| `s12/M11_idempotency_retry.py` | 43 | 42 fail, 1 passes (invariants of an empty schema) | 43 / 43 | 8 / 8 |
| `s12/M12_loop.py` | 24 | 20 fail, 4 pass (prototype `topological_order`, no task scheduling) | 24 / 24 | 6 / 6 |
| `s12/M13_probe.py` | 10 | 10 fail | 10 / 10 | 4 / 4 |
| `s12/M14_revocation_cancel.py` | 26 | 26 fail | 26 / 26 | 6 / 6 |

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

## Sabotage patches added

M10: `M10_breaker_before_bulkhead`, `M10_client_error_counts`, `M10_trial_leak`, `M10_budget_unchecked`,
`M10_timeout_from_text`, `M10_probe_through_breaker`, `M10_unsafe_default_probe`, `M10_mock_no_dedup`
(helper `_guard_base.py`). M11: `M11_key_per_attempt`, `M11_irreversible_retried`, `M11_expired_counts`,
`M11_conflict_ignored`, `M11_no_dispatch_marker`, `M11_hit_ignored`, `M11_timeout_retried`, `M11_marker_not_checked`.
M12: `M12_topology_ignored`, `M12_lock_in_own_transaction`, `M12_dependents_cancelled.sql`, `M12_ledger_mutable.sql`,
`M12_consolidate_again`, `M12_log_without_ids`. M13: `M13_ledger_not_consulted`, `M13_uncertain_as_failure`,
`M13_inconclusive_guessed`, `M13_retry_beyond_ceiling`. M14: `M14_live_check_allows_all`, `M14_validity_ignored`,
`M14_kill_switch_as_revoked`, `M14_no_check_before_call`, `M14_anyone_can_cancel`, `M14_live_check_writes`.
