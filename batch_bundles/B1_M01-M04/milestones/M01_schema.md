# M1: schema migrations (gate commit C, part 1) ★ (built)

| | |
|---|---|
| Status | Built in `a8f8f58` (enums + migration 015). Golden 89/89, sabotage 4/4. Waiting on owner rows only: S12-PIN (re-pin), S12-REC (STOP-001 `ruled`), ★ schema review |
| Gate | §7.3 (+ v9/v10), C16, C18, C20, C21, C22, C26, C27, C28, C33, C34, C35, C39 |
| Sources | DATABASE.md §3 table notes + "S12–S15 Additive Tables"; FINAL_ARCHITECTURE I-001 |
| Rulings | CONF-007 (`operation_quotas.worker_id`, always NULL), CONF-009 (golden files in `tests_golden/`), CONF-010 (red-first per file: 30 cases passed already on 009/010), CONF-014 (`idx_workers_workspace` exists; owner to confirm at review) |
| Golden | `tests_golden/s12/M01_schema.py`: 89 cases, 26 functions |
| Sabotage (4, all SQL) | `M01_cascade_delete.sql`, `M01_check_wider_than_enum.sql`, `M01_no_terminal_reason_trigger.sql`, `M01_two_open_episodes.sql` |
| Review | `docs/gates/S12_M1_SCHEMA_REVIEW.md` (`\d+` of every touched table) |

> The exact as-built schema (every column, type, default, constraint, index, trigger and RLS flag, generated from a live
> database) and the map of which milestone reads or writes each column are in [`../SCHEMA.md`](../SCHEMA.md).

## Files (as built)

| File | Content |
|---|---|
| `src/contracts/execution_states.py` | The persisted vocabularies (below). The **one source** for every CHECK (C28) and every state literal in S12–S15 code |
| `src/adapters/postgres/migrations/015_s12_schema.sql` | Everything new in this phase's schema (below) |
| Base, inside the tag (never edit) | `009_execution_admission.sql`: `execution_runs`, `execution_steps`, `execution_manifests`, `execution_plans`, `execution_ownership`, `state_transitions`, `operation_quotas`. `010_step_loop.sql`: step `terminal_reason` CHECK and its write-once trigger, the reservation link and dispatch marker columns |

## The enums (`contracts.execution_states`, exact values)

| Enum | Values |
|---|---|
| `ExecutionStatus` | pending, running, reconciling, completed, partial, failed, cancelled, dead_letter |
| `StepState` | pending, running, completed, partial, failed, cancelled, skipped, timeout, unknown, pending_probe, dead_letter |
| `StepTerminalReason` | user_cancelled, admission_rejected, admission_exhausted, no_worker, lease_unavailable, budget_exhausted, preflight_failed, not_executed_no_retry, dependency_failed, run_dead_lettered, authorization_revoked, kill_switch_engaged, binding_invalid, credential_invalid |
| `ReservationState` | reserved, locked, committed, released |
| `ReconciliationStatus` | none, pending_probe, reconciling, confirmed_success, confirmed_failure |
| `ReconciliationKind` | EXECUTION, VERIFICATION |
| `ReconciliationOutcome` | EXECUTED_SUCCESS, EXECUTED_FAILURE, NOT_EXECUTED, LEDGER_HIT, VERIFIED_PASS, VERIFIED_FAIL, EXHAUSTED |
| `LeaseStatus` | pending, active, expired, released |
| `DeadLetterStatus` | pending, retrying, resolved, abandoned |
| `DeadLetterErrorType` | transient, permanent, data, unknown_unresolved |
| `RetryMode` | PROBE, VERIFY, NONE |
| `ResolutionOutcome` | EXECUTED, NOT_EXECUTED, UNDETERMINED |
| `DeadLetterOrigin` | execution, rollback |
| `ConfirmationStatus` | pending, consumed, rejected, expired |
| `RuntimeType` | llm, rules, vision, browser, rpa, data, rag, code, human |
| `CircuitBreakerState` (M4) | closed, open, half_open |

`StepState.unknown` exists in the enum (A.2) but **no code may write it** (M03 architecture case). Worker states are
the frozen S0–S11 `contracts.worker.WorkerStatus` (`REGISTERED`, `ACTIVE`, `DRAINING`, `DRAINED`, `TERMINATED`).

## What migration 015 creates (as built)

| Object | Key rules |
|---|---|
| `fence_token_seq` | The **only** token source (C25); tokens never come from `max()+1` |
| `workers` | `tenant_id NOT NULL`; `workspace_id` (filter 4b; NULL only on legacy rows, ineligible); `state` CHECK = `WorkerStatus`, default `REGISTERED`; `capacity >= 1`; `0 <= current_load <= capacity`; `lease_epoch`; C39: `settings` JSONB `'{}'`, `assigned_user_id`, `paused_until`, `scheduled_activation_at` (filters, **not states**), `runtime_type` CHECK = `RuntimeType`, default `llm`; `idx_workers_workspace`, `idx_workers_tenant` |
| `worker_leases` | `fence_token BIGINT NOT NULL`; `status` CHECK = `LeaseStatus`, default `active`; `expires_at NOT NULL`; partial index on active leases per worker |
| `step_reconciliations` | episodes (C18/C19/C35); `status` CHECK = `ReconciliationStatus` minus `none` (`none` is never stored); **partial unique index `uq_step_reconciliations_open` (one open episode per step, `WHERE closed_at IS NULL`)** |
| `dead_letters` | `retry_mode` (NOT NULL, no default), `resolution_outcome`, `origin` (default `execution`) CHECKs from the enums; `chk_dead_letters_outcome` (resolved/abandoned need an outcome); `chk_dead_letters_resolved` (`resolved` = status in resolved/abandoned); `chk_dead_letters_rollback` (origin rollback ⇒ retry_mode NONE); FKs to run, step, reservation and episode. **The evidence of a record is the `context` JSONB column** (I11 reads it; M17's `evidence=` argument is stored there) |
| `idempotency_ledger` | `idempotency_key TEXT PRIMARY KEY` (global), `tenant_id`, `kernel_op_id`, `result JSONB`, `expires_at` |
| `checkpoints` | `UNIQUE (execution_id, sequence)`. **No code writes it in this phase**: CONF-044 (open) proposes writing it as a hint; recovery never reads it (§13) |
| `bindings.required_runtime_types` | `JSONB NOT NULL DEFAULT '[]'` (filter 17c; empty = any) |
| `operation_quotas.worker_id` | `CHECK (worker_id IS NULL)` and `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)` (CONF-007) |
| `state_transitions` | `chk_state_transitions_machine`: run, step, reservation, lease, dead_letter, episode, confirmation; new `execution_id` column and two indexes |
| RLS | `ENABLE` + `FORCE ROW LEVEL SECURITY` and policy `tenant_isolation` (`USING` **and** `WITH CHECK` on `current_setting('app.current_tenant', true)`) on every new tenant table |

## Pre-tag schema later milestones rely on (009/010, never edit)

| Object | Used by |
|---|---|
| `execution_runs.cancel_requested_at`, `consolidation`, `terminal_reason`, `connection_id` | M14 cancellation, M16 consolidation, M14 live check |
| `execution_steps.dispatched_attempt`, `attempt`, `reservation_id` (FK, the C33 link), `undo_token`, `terminal_reason` | M11 marker, M9 link, M12 inverse token |
| `uq_execution_runs_request` (unique `(tenant_id, request_id)`) | M6 duplicate admission |
| `uq_budget_reservation_open_step` (partial unique `step_id WHERE status <> 'released'`) | I12 at the database level; M13's retry after NOT_EXECUTED needs the old reservation released first |
| triggers `execution_manifests_immutable`, `execution_plans_immutable` (`reject_update()`) | I9: the manifest and plan never change after admission |
| `execution_ownership.fencing_token`, `runtime_instance_id`, `lease_id`, `worker_id` | M2 fence, M7 compare-and-set |

## Logic and conditions the golden pins

| Case group | Condition |
|---|---|
| apply / idempotent / new files | migrations apply to an empty schema and twice in a row; every new object is in a **new** file (015+) |
| enum = CHECK | for each listed column, the CHECK value set equals the enum's exactly |
| types | new tables use `TIMESTAMPTZ` (C33); every FK has the referenced key's type; C39 FKs exist |
| tenancy | every S12–S15 table has `tenant_id NOT NULL` and forced RLS (C34) |
| history | no `ON DELETE CASCADE` on an execution table |
| deferred | none of `worker_spawn_audit`, `worker_groups`, `worker_group_members`, `execution_batches`, `worker_config_versions`, `step_decisions`, and no `parent_execution_id` column |
| step terminal reason | `cancelled` / `skipped` without a reason is rejected; a second write of `terminal_reason` is rejected (trigger) |
| episodes | two open episodes on one step rejected; status `none` rejected |
| quotas | duplicate scope/period rejected; negative count rejected; a non-NULL `worker_id` rejected; `limit_value` cannot drop below `used_count` |
| indexes (exact) | unique `execution_runs(tenant_id, request_id)`; `worker_leases(worker_id) WHERE status = 'active'`; `idempotency_ledger(tenant_id, idempotency_key)`; unique `step_reconciliations(step_id) WHERE closed_at IS NULL`; `workers(workspace_id)` |
| tenant tables | `execution_runs`, `execution_steps`, `execution_manifests`, `execution_plans`, `execution_ownership`, `step_reconciliations`, `checkpoints`, `dead_letters`, `worker_leases`, `idempotency_ledger`, `budget_reservations`, `pending_confirmations`, `state_transitions`, `operation_quotas` (M20 later adds `workers` and `execution_events` to the forced-RLS check) |
| defaults | worker state default canonical; lease status default `active`; C39 JSON defaults; minimal dead-letter row valid with origin `execution` |

## Sabotage (what each proves)

| Patch | Breaks | Caught by |
|---|---|---|
| `M01_cascade_delete.sql` | execution history deleted with its run | the no-cascade case |
| `M01_check_wider_than_enum.sql` | a hand-written CHECK accepting upper-case `PENDING_PROBE` (C28) | enum = CHECK |
| `M01_no_terminal_reason_trigger.sql` | `terminal_reason` rewritable | write-once case |
| `M01_two_open_episodes.sql` | two open episodes per step | one-open-episode case |

## Traps (from the card and the drafting)

- Editing an S0–S11 migration (001–014 are inside the tag).
- Changing column types beyond C33 / §7.3; `TEXT` timestamps in new tables.
- Writing `UNKNOWN`, or storing episode status `none`.
- Treating pause / scheduled activation as worker **states**. They are columns and filters (C39; M04 case
  `test_worker_pause_is_not_a_state`).
- Adding a deferred table "for later".

## Regression checklist (run after any schema change in later batches)

- [ ] `M01_schema.py` 89/89 and the 4 SQL sabotage patches caught.
- [ ] A new enum member arrives with a **new** migration that widens its CHECK from the enum.
- [ ] New tables: `tenant_id NOT NULL`, forced RLS with `USING` and `WITH CHECK`, `TIMESTAMPTZ`, no cascade.
