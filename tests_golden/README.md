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
| `s12/M02_…`–`M04_…` | M2–M4 | — | not drafted yet | — | — |

The 30 cases that already pass cover schema the tag already has (migrations 009/010: step `terminal_reason` CHECK and
trigger, `execution_plans`, the run/step status CHECKs apart from the enum import, no cascades, key types). Plan §5.2
says "a golden test that already passes is rejected"; for M1 that rule is applied per file, not per case (CONF-010).

"Reference implementation" means a throw-away `contracts/execution_states.py` plus migration `015` written only to prove
that every case can pass together (a golden set that cannot all pass would force a STOP). It was run in a scratch
worktree and deleted; nothing of it is in `src/`.

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

## Sabotage (owner verify)

`tests_golden/sabotage/*.sql` run after the migrations when `GOLDEN_SABOTAGE=<file>` is set; each must turn at least one
case of its milestone FAIL (an assertion, not a setup error):

| Patch | Caught by |
|---|---|
| `M01_no_terminal_reason_trigger.sql` | `test_terminal_reason_is_written_once` |
| `M01_two_open_episodes.sql` | `test_one_open_episode_per_step`, `test_required_indexes[step_reconciliations…]` |
| `M01_check_wider_than_enum.sql` | `test_check_constraint_equals_its_enum[execution_steps-status]` |
| `M01_cascade_delete.sql` | `test_no_on_delete_cascade` |

```powershell
Get-ChildItem tests_golden\sabotage\M01_*.sql | ForEach-Object {
  $env:GOLDEN_SABOTAGE = $_.FullName; python -m pytest tests_golden\s12\M01_schema.py -q -p no:cacheprovider }
Remove-Item Env:GOLDEN_SABOTAGE
```
