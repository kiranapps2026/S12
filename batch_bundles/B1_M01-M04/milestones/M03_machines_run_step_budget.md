# M3: state machines I (run, step, budget reservation) (gate commit C, part 3) ⚙ (built)

| | |
|---|---|
| Status | Built in `b9e6123` (machines extended in M4 `8f38edb`). Golden 130/130, sabotage 3/3 |
| Gate | Appendix A.1–A.3, C6, C7, C13, C22, C24, C27 (I-3, I-8) |
| Sources | STATE_TRANSITIONS §1–§3; DATA_CONTRACTS §19 (repaired), §16.3 |
| Rulings | CONF-006 (`contracts/state_validators.py` is non-canonical; S12 code must not import it), CONF-012 (machines without listed reasons accept any non-empty reason) |
| Golden | `tests_golden/s12/M03_machines_run_step_budget.py`: 130 cases, 11 functions. Pairs are generated over the enums and read from the pinned gate text by `tests_golden/fixtures/appendix_a.py` |
| Sabotage (3) | `M03_old_data_contracts_edges`, `M03_reason_ignored`, `M03_retry_is_a_transition` |

## File (as built)

`src/engine/stages/s12_execute/transitions.py` (prototype file, reworked under CONF-011):

- `validate(machine, from_state, to_state, *, reason, closed=False) -> None` (:144). It returns for a legal move and
  raises `IllegalStateTransition` otherwise.
- `IllegalStateTransition` (:33), a `StateTransitionError` subclass.
- The edges live in `_EDGES` (immutable `MappingProxyType`); the creation rules live in `_INITIAL`.
- `check_run`, `check_step`, `check_budget` (:193–201) are kept for the prototype loop (pair-only checks). New
  code calls `validate` with a reason.

## Logic and conditions

1. **Creation** (`from_state=None`): legal only to the machine's initial state with its creation reason, logged
   `(none) → initial` (C24).
2. **A move:** the pair must be an edge, and the reason must be in that edge's set. A legal pair with another reason
   is **illegal**.
3. **Every other pair raises**, including any move out of a terminal state.
4. **Not-produced edges** with no listed reason (`running → partial`, `unknown → …`) accept any non-empty reason.
   The golden asserts them neither legal nor illegal.
5. **A retry is not a transition** (C24). There is no `running → running`; a retry is a `step_attempt` event
   (M11).
6. **No code path writes `StepState.UNKNOWN`.** This is an architecture case over all S12 code.
7. `step pending → cancelled` takes any `StepTerminalReason` (C22). `pending → skipped` only
   `dependency_failed`.
8. A reservation **never** commits from `reserved` (C3). It must be `locked` first.
9. An unknown machine name raises.

## The machines (generated from `transitions.py` at `f4a8d5f`; Appendix A is authoritative)

### Machine `run` (created `None → pending`, reason `created`)

| From | To | Allowed reasons |
|---|---|---|
| `pending` | `cancelled` | `authorization_revoked`, `binding_invalid`, `credential_invalid`, `kill_switch_engaged`, `user_cancelled` |
| `pending` | `running` | `admitted` |
| `reconciling` | `cancelled` | `authorization_revoked`, `binding_invalid`, `budget_exhausted`, `credential_invalid`, `kill_switch_engaged`, `user_cancelled` |
| `reconciling` | `completed` | `consolidated` |
| `reconciling` | `dead_letter` | `consolidated` |
| `reconciling` | `failed` | `consolidated` |
| `reconciling` | `partial` | `consolidated` |
| `running` | `cancelled` | `authorization_revoked`, `binding_invalid`, `budget_exhausted`, `credential_invalid`, `kill_switch_engaged`, `user_cancelled` |
| `running` | `completed` | `consolidated` |
| `running` | `dead_letter` | `consolidated` |
| `running` | `failed` | `consolidated` |
| `running` | `partial` | `consolidated` |
| `running` | `reconciling` | `awaiting_resolution` |

### Machine `step` (created `None → pending`, reason `created`)

| From | To | Allowed reasons |
|---|---|---|
| `pending` | `cancelled` | any `StepTerminalReason` value (C22) |
| `pending` | `running` | `started` |
| `pending` | `skipped` | `dependency_failed` |
| `pending_probe` | `completed` | `ledger_hit_success`, `probe_executed_success`, `verification_passed` |
| `pending_probe` | `dead_letter` | `human_verification_pending`, `probe_exhausted`, `verification_exhausted` |
| `pending_probe` | `failed` | `ledger_hit_failure`, `probe_executed_failure`, `verification_failed` |
| `pending_probe` | `pending` | `no_dispatch_marker`, `probe_not_executed`, `read_reexecution_safe` |
| `running` | `cancelled` | `user_cancelled` |
| `running` | `completed` | `ledger_hit_verified`, `verified` |
| `running` | `failed` | `ledger_hit_failure`, `non_retryable_error`, `retries_exhausted`, `verification_failed` |
| `running` | `partial` | any non-empty reason |
| `running` | `pending_probe` | `execution_uncertain`, `recovery`, `verification_uncertain` |
| `running` | `timeout` | `step_timeout` |
| `timeout` | `pending_probe` | `step_timeout_probe` |
| `unknown` | `dead_letter` | any non-empty reason |
| `unknown` | `pending_probe` | any non-empty reason |

### Machine `reservation` (created `None → reserved`, reason `reserved`)

| From | To | Allowed reasons |
|---|---|---|
| `locked` | `committed` | `dead_letter_abandoned`, `dead_letter_resolved_executed`, `dead_letter_resolved_undetermined`, `step_completed` |
| `locked` | `released` | `dead_letter_resolved_not_executed`, `no_dispatch_marker`, `probe_not_executed`, `step_failed` |
| `reserved` | `locked` | `step_started` |
| `reserved` | `released` | `budget_released_before_start`, `preflight_failed`, `run_cancelled` |


Run cancel reasons: `pending → cancelled` excludes `budget_exhausted` (no budget is used before admission).

## Sabotage

| Patch | Breaks |
|---|---|
| `M03_old_data_contracts_edges` | brings back the pre-v9 DATA_CONTRACTS edges (`timeout → dead_letter`, `unknown → failed`) |
| `M03_reason_ignored` | checks only the pair, so any reason passes a guarded edge |
| `M03_retry_is_a_transition` | logs a retry as `running → running` |

## Traps

- Using DATA_CONTRACTS' old §19.2 edges.
- Importing `contracts/state_validators.py` (CONF-006; scanned).
- Adding `running → running` for retries.
- A reason that is a free string instead of the Appendix A code (I5 rejects such log rows).

## Regression checklist

- [ ] 130/130; 3 patches caught.
- [ ] Any new reason a later card needs exists in Appendix A first. Otherwise STOP (a gate amendment, never a
      local edit).
