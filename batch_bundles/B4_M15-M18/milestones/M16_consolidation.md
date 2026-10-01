# M16: consolidation (gate commit I, part 2) ⚙

| | |
|---|---|
| Gate | §10 (as corrected by C8), C13, C39 (quota refund), suite 10; invariants I2, I3, I13 |
| Rulings | CONF-034 (a run whose steps were cancelled `run_dead_lettered` is DEAD_LETTER), CONF-037 (which quota rows are refunded) |
| Golden | `tests_golden/s12/M16_consolidation.py`: 31 cases (15 functions) |
| Sabotage | `M16_cancelled_counts_as_completed`, `M16_live_step_consolidated`, `M16_refund_always` |
| Depends on | M15 `verification_layer` events, M14 cancel path, M9 budget reserver, M8a quota rows |
| Reference | `src/engine/stages/s13_reconciliation/consolidation.py` (33 lines), `src/adapters/postgres/consolidation.py` (136 lines), `execution_states.py` patch |

## Files

| File | Action |
|---|---|
| `src/contracts/execution_states.py` | add `ConsolidationOutcome(StrEnum)`: SUCCESS, PARTIAL, FAILURE. Stored in `execution_runs.consolidation` (column exists since migration 009) |
| `src/engine/stages/s13_reconciliation/consolidation.py` | **new**: `consolidation_outcome(steps)`, pure |
| `src/adapters/postgres/consolidation.py` | **new**: `PostgresConsolidator(database)` with `consolidate`, `__call__`, `cancel` → `ConsolidationResult(run_status, outcome, refunded)` |
| `src/engine/stages/s12_execute/loop.py` | additive: `LoopDeps.cancel_run=None`. When set, every CANCELLED ending goes through it |

## Logic and conditions

**`consolidation_outcome(steps)`.** `steps` are `(status, terminal_reason)` pairs. Raise `ValueError` if the list
is empty or any step is not terminal (pending, running, timeout, pending_probe). Terminal means completed, failed,
cancelled, skipped or dead_letter. Use the `StepState`, `ExecutionStatus` and `StepTerminalReason` enums, not
strings. Apply the rows in this order:

| Condition (first match wins) | Run status | Outcome |
|---|---|---|
| any step `dead_letter`, or any step `cancelled` with reason `run_dead_lettered` | `dead_letter` | FAILURE |
| at least one `completed`, and every other step `completed` or `skipped` (no failed/cancelled) | `completed` | SUCCESS |
| at least one `completed` and at least one `failed` or `cancelled` | `partial` | PARTIAL |
| no `completed` | `failed` | FAILURE |

`cancelled` and `skipped` **count as not completed**. A run with a cancelled step is never COMPLETED (I13): check the
reasons `admission_rejected`, `user_cancelled`, `not_executed_no_retry`, `lease_unavailable`. The golden table pins
11 rows: all-completed, completed-skipped, partial-failed, partial-cancelled, partial-no-worker, failed-skipped,
all-cancelled, preflight, dead-letter-mixed, dead-letter, plan-integrity.

**`PostgresConsolidator.consolidate(holder, tenant_id, execution_id)`** (also `__call__`, so it serves as
`LoopDeps.consolidate`) and **`.cancel(holder, tenant_id, execution_id, *, reason)`** (serves as
`LoopDeps.cancel_run`). Each runs as ONE fenced transaction:

1. Lock the run row. Refuse with `ValueError`, nothing written, if:
   - the run is not RUNNING or RECONCILING (so nothing ends or refunds twice);
   - any step is non-terminal;
   - the execution is another one than the holder's (a stale token raises `FencedOut`).
2. Release every RESERVED reservation of the run with reason `budget_released_before_start` (consolidate) or
   `run_cancelled` (cancel). Nothing stays RESERVED. LOCKED stays only under D4 (dead-lettered uncertainty).
3. Write event `VERIFICATION_STARTED` with `{"steps": {plan_step_id: [required layers]}}`. Then write
   `VERIFICATION_COMPLETED` with `{"steps": {plan_step_id: [{"layer", "verdict"}, ...]}}`, built from the persisted
   `verification_layer` events (latest verdict per layer). The cancel path writes both too.
4. Move the run by the matrix: reason `consolidated`. For `cancel`, the given reason is both the transition reason
   and the run's `terminal_reason`. Store `consolidation`.
5. **Refund** only when `cancel` ends the run CANCELLED **with no step COMPLETED**:
   - decrement, once (`used_count > 0`), the run's tenant-level and workspace-level `operation_quotas` rows where
     `resource_type = 'executions'` and the period contains `execution_runs.created_at` (CONF-037);
   - in the same transaction, record a `quota_refunded` event with `{"quota_ids": [...]}`;
   - never refund another workspace's or another period's rows, never after a completed step, never for a FAILED
     run.

**Concurrency:** two endings that both start while the run row is locked must end the run once and refund once.
Keep the row lock (`SELECT ... FOR UPDATE`) at the start of the transaction.

## Traps

- Counting CANCELLED as completed (sabotage `M16_cancelled_counts_as_completed`).
- Ignoring non-terminal steps instead of refusing (sabotage `M16_live_step_consolidated`).
- Refunding on every ending (sabotage `M16_refund_always`).
- A second path that moves the run row outside the consolidator once `cancel_run` is wired.
- A refund query without the workspace or period filter, or without the run-row lock (hand mutations in the B4
  review turned the golden red).
- An admission reject after a completed step must give PARTIAL, never COMPLETED.

## Done when

- [ ] 31/31 in `M16_consolidation.py`; M01–M15 green; invariants I2, I3, I13 pass after every integration case.
- [ ] `owner_certify_s12.py --milestone M16`: all PASS, sabotage 3/3.
