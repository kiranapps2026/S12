# S12–S15 golden tests

Owner-pinned tests, one file per milestone (`s12/Mxx_*.py`), drafted by Claude from the gate text (plan §5).
**Fable never edits anything under `tests_golden/`.** If a golden test looks wrong, STOP with the test name, the gate
section and the reasoning (gate §19.1); Claude rules; the owner re-pins.

## Run

```powershell
$env:TEST_DATABASE_URL = "postgresql://<user>@localhost:5432/suprpg_test"   # name must end in _test
python -m pytest tests_golden\s12\M01_schema.py -q -p no:cacheprovider
```

Each module gets its own schema in that database (created, migrated, dropped: gate §15.1). Without
`TEST_DATABASE_URL` the run errors; golden tests are never skipped.

**Why not `tests\golden\s12` (plan §3):** a golden file is red until its milestone is built, and the S0–S11 certifier
(OWN-13) runs `pytest tests` and must stay 19/19 through S12–S15. Inside `tests\` every red golden file would turn OWN-13
FAIL. Recorded as CONF-009.

## Batch B1 status

| File | Milestone | Cases | Red on `s12-work` (tag schema) | Reference implementation | Sabotage caught |
|---|---|---|---|---|---|
| `s12/M01_schema.py` | M1 | 89 | 59 fail, 30 pass | 89 / 89 pass | 4 / 4 |
| `s12/M02_fencing_core.py` | M2 | 18 | 16 fail, 2 pass | 18 / 18 pass | 3 / 3 |
| `s12/M03_machines_run_step_budget.py` | M3 | 130 | 128 fail, 2 pass | 130 / 130 pass | 3 / 3 |
| `s12/M04_machines_other.py` | M4 | 79 | 78 fail, 1 pass | 79 / 79 pass | 2 / 2 |

The reference implementation passes all 316 cases of M1–M4 in one run. Building it caught two defects in the drafts
before they could reach Fable (M02: a sabotage run could hang the schema teardown; M04: the machine name
`dead_letter` is spelled like a state value, so the bare-literal rule was unsatisfiable). Both are fixed.
The cases that already pass on `s12-work` are fixture self-tests (`test_invariant_checker_rejects_illegal_rows`),
standing rules the tree already obeys (`test_s0_s11_code_unchanged_since_the_tag`, `test_no_code_writes_step_state_unknown`,
`test_s12_code_does_not_use_the_non_canonical_validator`, `test_worker_pause_is_not_a_state`).

The 30 cases that already pass cover schema the tag already has (migrations 009/010: step `terminal_reason` CHECK and
trigger, `execution_plans`, the run/step status CHECKs apart from the enum import, no cascades, key types). Plan §5.2
says "a golden test that already passes is rejected"; for M1 that rule is applied per file, not per case (CONF-010).

"Reference implementation" means throw-away code (enums, migration `015`, `fencing.py`, `transition_log.py`,
`settings.py`, a `transitions.py` generated from Appendix A, the circuit breaker on the enum, and the other prototype
files deleted) written only to prove that every case can pass together (a golden set that cannot all pass would force a
STOP). It ran in a scratch worktree and was deleted; nothing of it is in `src/`. It does not show that the prototype
tests in `tests/` stay green; that is Fable's job under CONF-011.

## Interfaces fixed by M01 (what Fable must build)

- Module `contracts.execution_states` with `StrEnum`s: `ExecutionStatus`, `StepState`, `StepTerminalReason`,
  `ReservationState`, `ReconciliationStatus`, `ReconciliationKind`, `ReconciliationOutcome`, `LeaseStatus`,
  `DeadLetterStatus`, `DeadLetterErrorType`, `RetryMode`, `ResolutionOutcome`, `DeadLetterOrigin`,
  `ConfirmationStatus`, `RuntimeType`. Values are the ones the gate states (C18, C21, C26, C27, C28, DATA_CONTRACTS).
  Every CHECK on the mapped column equals the enum's value set (`step_reconciliations.status` excludes `none`).
- New migration files 015+ only; 001–014 are inside the tag.
- Tables `workers`, `worker_leases`, `step_reconciliations`, `dead_letters`, `idempotency_ledger`, `checkpoints`;
  sequence `fence_token_seq`; the §7.3 columns and indexes; C39 columns; `operation_quotas.worker_id` with
  `CHECK (worker_id IS NULL)` in the unique key (CONF-007); `state_transitions` able to log all seven machines.
- `tenant_id NOT NULL` and forced RLS with a policy on every C34 table.
- Timestamps of new tables are `TIMESTAMPTZ`; minimal inserts in the test helpers must be valid.

## Interfaces fixed by M02–M04

- `adapters.postgres.fencing`: `FenceHolder(tenant_id, execution_id, runtime_instance_id, fence_token)`;
  `fenced_write(database, holder, write)` checks and **locks** the `execution_ownership` row in the same tenant
  transaction, then returns `await write(connection)`; otherwise `contracts.step_execution.FencedOut` and nothing written.
- `adapters.postgres.transition_log.log_transition(connection, *, tenant_id, machine, entity_id, from_state, to_state,
  reason, runtime_instance_id, fence_token, execution_id=None)`: exactly one row.
- `engine.stages.s12_execute.settings.ExecutionSettings` (+ `from_env`, `S12_*` variables), C37 checks at construction.
- `engine.stages.s12_execute.transitions.validate(machine, from_state, to_state, *, reason, closed=False)` and
  `IllegalStateTransition`, for run, step, reservation, lease, worker, dead_letter, episode, confirmation, breaker;
  legal edges and reasons are read from the pinned gate Appendix A by `fixtures/appendix_a.py`.
- `contracts.execution_states.CircuitBreakerState` (closed, open, half_open).
- Static rules over **S12 code** (`fixtures/code_scan.py`: `src/` minus the frozen S0–S11 files; the prototype files
  count as S12 code, CONF-011): every SQL statement on an S12 table names `tenant_id`; no bare state literal (C28);
  no `StepState.UNKNOWN`; no import of `contracts.state_validators` (CONF-006); frozen files byte-identical to the tag.
- `fixtures/invariants.py`: `assert_system_invariants(schema)` with I5 (every logged transition legal per Appendix A).

## Sabotage (owner verify)

`tests_golden/sabotage/*.sql` run after the migrations, and `*.py` patches (`apply()`) monkeypatch the interface under
test, when `GOLDEN_SABOTAGE=<file>` is set; each must turn at least one case of its milestone FAIL (an assertion, not a
setup error):

| Patch | Caught by |
|---|---|
| `M01_no_terminal_reason_trigger.sql` | `test_terminal_reason_is_written_once` |
| `M01_two_open_episodes.sql` | `test_one_open_episode_per_step`, `test_required_indexes[step_reconciliations…]` |
| `M01_check_wider_than_enum.sql` | `test_check_constraint_equals_its_enum[execution_steps-status]` |
| `M01_cascade_delete.sql` | `test_no_on_delete_cascade` |
| `M02_skip_fence_check.py` | `test_stale_or_foreign_holder_is_fenced_out_and_writes_nothing` (3), others |
| `M02_check_without_lock.py` | `test_takeover_waits_for_an_open_fenced_write_then_fences_the_old_owner` |
| `M02_settings_unvalidated.py` | `test_settings_reject_inverted_timeouts` (3) |
| `M03_retry_is_a_transition.py` | `test_every_other_pair_is_illegal[step]`, `test_step_edges_the_gate_names_illegal` |
| `M03_old_data_contracts_edges.py` | `test_step_edges_the_gate_names_illegal` (3 cases) |
| `M03_reason_ignored.py` | `test_legal_edge_rejects_any_other_reason` (15 cases) |
| `M04_closed_episode_moves.py` | `test_no_episode_move_after_closed_at` |
| `M04_expired_lease_renewed.py` | `test_every_other_pair_is_illegal[lease]`, `test_lease_can_only_be_renewed_while_active` |

```powershell
Get-ChildItem tests_golden\sabotage\M0* | ForEach-Object {
  $env:GOLDEN_SABOTAGE = $_.FullName; $m = $_.Name.Substring(0, 3)
  python -m pytest (Get-ChildItem "tests_golden\s12\$m`_*.py").FullName -q -p no:cacheprovider }
Remove-Item Env:GOLDEN_SABOTAGE
```
