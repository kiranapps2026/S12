# Register entry — XS-1: Step cancellation semantics and terminal reason

For `SUPERSESSION_AWARE_BLOCKER_REGISTER.md`, in the format required by S12_S15_EXECUTION_GATE §0 item 5.

| Field | Value |
|---|---|
| **ID** | XS-1 |
| **Documents** | STATE_TRANSITIONS.md §2 (step machine) and invariant I-1; DATA_CONTRACTS.md StepState annotations; DATABASE.md `execution_steps`; S12_S15_EXECUTION_GATE §8 steps 1, 5, 6 and §9 |
| **Phase** | S12–S15 (current gate). Pre-existing; not introduced by the Laya note. |
| **Status** | OPEN — ruling required before S12–S15 certification |

## Conflicting statements

1. STATE_TRANSITIONS §2 and DATA_CONTRACTS annotate step `PENDING → CANCELLED` as "user cancelled before start". The S12–S15 gate moves steps to CANCELLED for system reasons: admission REJECT (§8 step 1), `budget_exhausted` (§8 step 5, C15), pre-flight failure (§8 step 6), and NOT_EXECUTED on IRREVERSIBLE or non-idempotent D steps (§9). The run-level machine already defines CANCELLED as "user or system cancelled".
2. The gate requires "the specific reason" for these cancellations, but `execution_steps` has no structured column for it; only free-text `error` exists.
3. The `execution_steps.status` column comment lists `pending, running, completed, failed, skipped, partial, UNKNOWN, PENDING_PROBE, DEAD_LETTER` and omits `cancelled`, although CANCELLED is a canonical step state.
4. STATE_TRANSITIONS invariant I-1 lists terminal step states as `completed, failed, skipped, DEAD_LETTER` and omits `cancelled`, while §2 lists CANCELLED as terminal. As written, I-1 would flag every run containing a cancelled step.

## Proposed ruling

- `PENDING → CANCELLED` means "did not start: cancelled by the user or by the system". Correct the annotation in STATE_TRANSITIONS §2 and DATA_CONTRACTS. No new state or transition.
- Add an additive column `execution_steps.terminal_reason TEXT NULL`, written with the terminal transition through `fenced_write()`, with these invariants:
  - `CHECK (status <> 'cancelled' OR terminal_reason IS NOT NULL)`: every cancelled step has a reason.
  - `terminal_reason` must belong to the closed enum (CHECK constraint or foreign key to a reason-code table).
  - Immutable once written: the write path rejects any update to a non-null `terminal_reason`, and the state machine already forbids leaving a terminal state. Values come from a closed reason-code enum defined in DATA_CONTRACTS (initially: `user_cancelled`, `admission_rejected`, `admission_exhausted`, `no_worker`, `lease_unavailable`, `budget_exhausted`, `preflight_failed`, `not_executed_no_retry`, `dependency_failed`, `run_dead_lettered`). Free-text `error` stays for diagnostics and is never used for logic.
- Add `cancelled` to the `execution_steps.status` comment and to invariant I-1's terminal list.
- **SKIPPED stays reserved** for "dependency failed, step not needed". It must never be used for a required step that did not run, because consolidation treats COMPLETED + SKIPPED with no failures as SUCCESS.

## Tests

- Every system cancellation path in §8 and §9 writes the expected `terminal_reason`.
- A cancelled step with a null or unknown `terminal_reason` is rejected by the database.
- A second write to a non-null `terminal_reason` is rejected.
- I-1 passes for a run containing CANCELLED steps.
- A run with a CANCELLED required step never consolidates to COMPLETED.

## Dependents

- LAYA_DECISION_ADAPTER.md §7.6 (future LLM-layer phase) will add `reflex_*` reason codes to the enum. It does not block on anything beyond this ruling.
