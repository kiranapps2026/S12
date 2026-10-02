# M12: the S12 loop, happy path, dependents, terminal reasons (gate commit H, part 1) ⚙

| | |
|---|---|
| Gate | §8 steps 1–12, C11, C15, C22, C24, C25, C30, C35 (dispatch marker), I-3, I16, §21 S2 (dispatcher), S5 (logs); FINAL_ARCHITECTURE §40; Appendix A.1, A.2, A.4 |
| Rulings | CONF-019 (the runtime list in `SelectionContext`), CONF-026 (`execution_events`), CONF-027 (admission snapshot and pre-flight injected), CONF-033 (the loop never takes over), CONF-034 (plan digest on every load), CONF-035 (port the `tests_postgres` prototype loop tests) |
| Golden | `tests_golden/s12/M12_loop.py`: 33 cases |
| Sabotage (8) | `M12_acquire_steals`, `M12_consolidate_again`, `M12_dependents_cancelled.sql`, `M12_lease_kept_when_fenced`, `M12_ledger_mutable.sql`, `M12_lock_in_own_transaction`, `M12_log_without_ids`, `M12_topology_ignored` |
| Reference | `loop.py` (786 lines, merged through M21: read only the M12 parts), `execution.py` (`PostgresExecutionStore`), `execution_events.py`, `kernel_policy.py`, `016_execution_events.sql`, `leases.py` (`holder=`), `eligibility.py`, `dispatch.py` |

## Files

| File | Action |
|---|---|
| `src/adapters/postgres/migrations/016_execution_events.sql` | **new**: the append-only ledger table (below) |
| `src/adapters/postgres/execution_events.py` | **new**: `PostgresExecutionEvents(database).recorder(holder, *, trace_id, step_id=None)` → `async record(kind, payload)` (one fenced write) |
| `src/adapters/postgres/kernel_policy.py` | **new**: `PostgresKernelPolicy(database).retry_safety(kernel_op_id)`; an unknown operation is `never` |
| `src/adapters/postgres/execution.py` | `PostgresExecutionStore(database)`: `load`, `transition_step`, `transition_run`, … Every write fenced, validated by `transitions.validate` and logged |
| `src/adapters/postgres/leases.py` | `acquire(..., holder=None)`: with a holder, the ownership row is checked **under its lock**; if it no longer names the holder → `FencedOut`, nothing written. M07 behaviour unchanged without `holder` |
| `src/engine/stages/s12_execute/eligibility.py` | additive: `binding_requirements(reader, binding_ids)`, `step_context(...)`, so the loop never names a runtime type |
| `src/engine/stages/s12_execute/loop.py` | **rewrite** of the prototype (CONF-011): `topological_order`, `LoopSettings`, `LoopDeps`, `LoopResult`, `run_execution` |
| `src/engine/stages/s12_execute/dispatch.py` | **new**: `InProcessDispatcher(run).dispatch(tenant_id, execution_id)` returns an awaitable handle. The only S12–S15 file allowed to schedule tasks |
| `tests_postgres/test_step_loop.py`, `tests_postgres/test_chain_full_stack.py` | **port** from `StepLoopDeps` to `LoopDeps` / `run_execution`. Same scenarios and assertions, never deleted or weakened (CONF-035); the log keeps reporting the `tests_postgres` total |

## Interface (exact; the field order of the required `LoopDeps` fields is part of the contract)

```python
def topological_order(steps) -> list            # ties by step index; a cycle or unknown id → ValueError
@dataclass(frozen=True)
class LoopSettings:  admission_max_attempts; lease_max_attempts; lease_ttl_s; backoff_base_s; ledger_ttl_s
@dataclass(frozen=True)
class LoopDeps:      runtime_instance_id; store; events; admission; selection; leases; budget; kernel_policy;
                     preflight; guard; idempotency; attempts; live; verify; consolidate; sleep; settings
    # admission(tenant_id, execution_id, plan_step_id) -> AdmissionSnapshot
    # preflight(step, binding) -> str | None   (a failure detail)
    # verify(step, binding, result) -> "PASS" | "FAIL" | "UNKNOWN"
    # consolidate(holder, tenant_id, execution_id)   (once after the loop, unless the run already ended)
@dataclass(frozen=True)
class LoopResult:    run_status; steps; reason=None     # steps: plan_step_id -> (status, terminal_reason)
async def run_execution(deps: LoopDeps, tenant_id: str, execution_id: str) -> LoopResult
```

Later milestones only **append** fields with defaults (M13 `episodes`, M15 `verification`, M16 `cancel_run`, M17
`dead_letters`, M19 `faults`, M21 `metrics`). `LoopDeps` must stay a dataclass: tests and the M20 process fixture
use `dataclasses.replace`.

**Migration 016 `execution_events`:**

- Columns: `seq BIGSERIAL` (order), `event_id TEXT UNIQUE`, `tenant_id TEXT NOT NULL`, `execution_id`,
  `trace_id NOT NULL`, `event_type NOT NULL`, `step_id`, `attempt_id`, `provider_call_id`, `runtime_instance_id`,
  `fence_token`, `payload JSONB`, `created_at`.
- Forced RLS with a tenant policy.
- UPDATE and DELETE are rejected for **every** role, by trigger (sabotage `M12_ledger_mutable.sql`).

## Logic and conditions

**Before any step (§7.3, CONF-033, CONF-034):**

| Condition | Result |
|---|---|
| the run is not RUNNING | return it untouched |
| `execution_ownership.runtime_instance_id` is not this loop's | reason `fenced_out`, **nothing written** (only recovery takes ownership, M19) |
| the plan does not decode, or its digest differs from `execution_plans.plan_hash` **or** `execution_manifests.plan_hash` | nothing executes: every PENDING step `cancelled (run_dead_lettered)`, an ERROR alert naming `plan_integrity`, consolidation, reason `plan_integrity` |

**Per step, in topological order (ties by index; never skipped by admission or lease failure, C11):**

1. **Admission** (`admit_step`). A REJECT maps through `reject_outcome` (C30). QUEUE/DELAY waits and never skips the
   step. Persistent backpressure ends `admission_exhausted` (DEF-005). Every decision is a ledger event.
2. **Eligibility and selection, then the lease.** Acquired **before** the reservation, with `holder=`. `no_worker` /
   `lease_unavailable` end the run like a REJECT.
3. **Reserve the budget.** Exhausted → C15: this step and every remaining step `cancelled (budget_exhausted)`, the run
   CANCELLED.
4. **Pre-flight.** On failure: budget released `preflight_failed`, lease released, **only this step** `cancelled
   (preflight_failed)` with the detail in `error`, its dependents SKIPPED.
5. **Start.** `started` plus `step_started` and the budget LOCK in **one** transaction (I-3; sabotage
   `M12_lock_in_own_transaction`).
6. `run_attempts` (M11).
7. `verify` (injected in M12; M15 replaces it).
8. **Settle.**
   - Success: `verified` / `ledger_hit_verified`, reservation committed.
   - Failure (`non_retryable_error`, `retries_exhausted`, `ledger_hit_failure`, `verification_failed`): FAILED,
     reservation released (`step_failed`).
   - A completed W/D step whose binding has an inverse records an `undo_token`.
9. **Release the lease** `work_complete` (leases bracket each step).
10. **Dependents.** The dependents of a FAILED or CANCELLED step are SKIPPED `dependency_failed` (SKIPPED **only**
    with that reason, C22; sabotage `M12_dependents_cancelled.sql`). A run-ending trigger cancels the step and every
    remaining PENDING step with **its** reason.

**`FencedOut` at any point (§8 step 8, C25):**

- Stop at once with reason `fenced_out`.
- No further execution write and no consolidation.
- A lease the loop holds is released `fenced_out` (A.4; sabotage `M12_lease_kept_when_fenced`).
- A step in flight is left as it is, RUNNING with its budget LOCKED, for the new owner.

**Ledger and logs:**

- Every `ProviderCalled` follows a committed dispatch marker (I16).
- A retry is a `step_attempt` event.
- Every log line carries the correlation ids as record attributes: `tenant_id`, `execution_id`,
  `runtime_instance_id`, `trace_id`, and `step_id` where there is one (sabotage `M12_log_without_ids`).
- The loop's `LoopResult` must equal the persisted rows.
- `consolidate` is called **once** (sabotage `M12_consolidate_again`).

## Open defects this milestone must close (recorded during B1/B2)

| Defect | Where (prototype loop on `s12-work`) | What M12 must do |
|---|---|---|
| **DEF-002** | `src/engine/stages/s12_execute/loop.py` logs step and run reasons Appendix A does not list (`step_started` for `started`, `timeout_probe_queued`, `verification_unknown`, `collateral`, `cancel_requested`, `adapter_error`, `step_completed`, …) | every move goes through `transitions.validate` with an Appendix A reason (I5 rejects the rest); then close DEF-002 in `S12_DEFECTS.md` (append only) |
| **DEF-004** | the prototype moves `pending → running` and `reserved → locked` in two transactions | one transaction: the step start, `step_started` and `reserver.lock(..., connection=)` inside one `fenced_write` (I-3; sabotage `M12_lock_in_own_transaction`) |

Both are listed `open … fix in M12` in `docs/gates/S12_DEFECTS.md`. The rewrite replaces the prototype loop, so they go
away by construction, but the defect rows must be closed with the commit that does it.

## Traps

- Taking over a run because `acquire` found no usable lease between steps. Pass `holder=` (sabotage
  `M12_acquire_steals`).
- Ignoring topological order (sabotage `M12_topology_ignored`).
- `create_task` / `ensure_future` / `TaskGroup` anywhere but `dispatch.py` (case
  `test_no_s12_to_s15_module_schedules_tasks_itself`).
- Naming a runtime type in the loop (M08a RD-9). Go through `eligibility.step_context`.
- Deleting the `tests_postgres` prototype tests instead of porting them.
- Copying the 786-line reference loop wholesale. Build the M12 part; M13–M21 seams come in their own milestones.

## Done when

- [ ] 33/33 in `M12_loop.py`; M01–M11 green; I15 and I16 pass.
- [ ] `tests_postgres` ported (same scenarios); the log reports its total.
- [ ] `owner_certify_s12.py --milestone M12`: all PASS, sabotage 8/8.
