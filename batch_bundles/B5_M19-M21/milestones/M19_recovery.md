# M19: crash recovery and fault injection (gate commit L, part 1) ⚙

| | |
|---|---|
| Gate | §13, §15.2 (ten points), C14, C26, C35, suite 6 (Crash A/B/C, cached failure and expired record at recovery), suite 14, suite 16b, suite 19 (C35 rows); invariants I1–I16 |
| Rulings | CONF-033 (ruled: never take your own run). **Open:** CONF-042 (discovery function), CONF-043 (tampered in-flight step), CONF-044 (checkpoints as a hint), CONF-046 (orphan rule, amends 042), CONF-047 (RECONCILING resolution) |
| Golden | `tests_golden/s12/M19_recovery.py` (25 functions, crash points parametrized ×10) |
| Sabotage | `M19_ledger_blind_recovery`, `M19_marker_never_written`, `M19_sweeper_takes_its_own`, `M19_takeover_steals` |
| Reference | `fault_injection.py` (40 lines), `recovery.py` (73), `loop.py` (`recover_execution`, `_take_over`, `_resolve_in_flight`, …), `017_recovery_candidates.sql`, `CHANGES_vs_s12-work.patch` (leases) |

## Files

| File | Action |
|---|---|
| `src/engine/stages/s12_execute/fault_injection.py` | **new**: `POINTS`, `SimulatedCrash(BaseException)`, `NoFaults` |
| `src/engine/stages/s12_execute/recovery.py` | **new**: `RecoverySweeper(database, deps, *, batch=10)` |
| `src/adapters/postgres/migrations/017_recovery_candidates.sql` | **new**: `s12_recovery_candidates(runtime_instance_id, limit, orphan_after_s)` |
| `src/engine/stages/s12_execute/loop.py` | additive: `LoopDeps.faults = NoFaults()`; `faults.hit(point)` at each point; `recover_execution`; a retried step resumes at the attempt after its last dispatched one |
| `src/engine/stages/s12_execute/attempts.py` | `AttemptDeps.faults` |
| `src/engine/stages/s13_reconciliation/probe.py` | `resolve_execution(..., faults=, metrics=)` |
| `src/engine/stages/s12_execute/settings.py` | `ExecutionSettings.recovery_sweep_interval_s` (`S12_RECOVERY_SWEEP_INTERVAL_S`, default 10, `0 < x < 30`, else `ValueError`) |
| `src/adapters/postgres/leases.py` | `acquire(..., skip_locked=False)`; `expire_lapsed(tenant_id, execution_id)` |
| `src/adapters/postgres/reconciliation.py` | `PostgresEpisodes.find_open(tenant_id, step_id)` |
| `src/adapters/postgres/execution_events.py` | `PostgresExecutionEvents.layer_verdicts(tenant_id, step_id)`. Recovery reads verdicts through this, never through a private DB handle |

## The ten fault points (names and order are pinned)

| # | Point | State when hit | What recovery must do with that step |
|---|---|---|---|
| 1 | `after_lease_acquire` | lease held, nothing reserved | start fresh |
| 2 | `after_budget_reserve` | reservation RESERVED | **reuse** that reservation |
| 3 | `after_budget_lock` | step RUNNING, reservation LOCKED, no dispatch marker | NOT_EXECUTED **without a probe**; a new reservation only for the retry |
| 4 | `after_dispatch_marker_before_call` | marker written | probe → NOT_EXECUTED → retry as attempt 2 |
| 5 | `after_adapter_call_before_ledger` | executed, no ledger row | Crash A: the probe finds EXECUTED_SUCCESS; never called again |
| 6 | `after_ledger_before_verification` | ledger success | Crash B: VERIFICATION episode, no probe |
| 7 | `during_verification` | the first layer result persisted | Crash B |
| 8 | `after_verification_before_step_commit` | every required layer PASS recorded | Crash C: VERIFICATION episode opened and closed LEDGER_HIT, `completed (ledger_hit_success)` |
| 9 | `after_commit_before_checkpoint` | step COMPLETED, lease held | continue with the next step |
| 10 | `during_probe` | a probe attempt started | continue the **same** episode: the lost attempt is recorded `inconclusive`, then resolved |

- `NoFaults.hit(point)` raises `ValueError` for an unknown name and does nothing otherwise.
- `SimulatedCrash` is raised only by a test's injector, never by product code.
- No environment switch: `fault_injection.py` contains no `environ` or `getenv`.

## Logic and conditions

**`recover_execution(deps, tenant_id, execution_id) -> LoopResult`:**

1. Expire the execution's **lapsed** leases (`ttl_elapsed`). Never expire a live one.
2. Take over through `acquire(..., skip_locked=True)` (holder None) on an eligible worker, with a new, **larger**
   token and the ownership compare-and-set. If none is possible: reason `not_orphaned`, nothing else written.
3. §13 step 1a, live check: on REVOKED, resolve the in-flight step first (an executed one completes; a provably
   unexecuted one is `cancelled (not_executed_no_retry)`), then cancel the rest with the reason. Never resume.
4. §13 step 2, plan digest (CONF-034/043): on mismatch, the in-flight step is **never probed, verified or re-run**.
   It goes RUNNING/TIMEOUT → `pending_probe` → `dead_letter (probe_exhausted)`, budget LOCKED, with a PROBE dead letter
   (evidence `plan_integrity`). PENDING steps are `cancelled (run_dead_lettered)`; the run consolidates DEAD_LETTER.
5. §13 step 3, the single in-flight rule, first match wins:

| In-flight state | Action |
|---|---|
| RUNNING | `pending_probe (recovery)` |
| TIMEOUT | `pending_probe (step_timeout_probe)` |
| an open episode exists | continue it; a lost `reconciling` attempt becomes `inconclusive` |
| ledger success and every required layer PASS recorded | VERIFICATION episode opened and closed LEDGER_HIT → `completed (ledger_hit_success)` |
| ledger success otherwise | VERIFICATION episode (`verification_passed` on success) |
| ledger failure | EXECUTION episode closed LEDGER_HIT → `failed (ledger_hit_failure)`; no probe, no call |
| no ledger record, **no dispatch marker** | EXECUTION episode closed NOT_EXECUTED (evidence `no_dispatch_marker`) → `pending (no_dispatch_marker)`, budget released `no_dispatch_marker`; no probe |
| otherwise (marker, no record; or an expired record) | EXECUTION episode and the probe. Never a blind call |

6. §13 step 4: continue the normal loop from the first PENDING step. A RECONCILING run is resolved and
   **consolidated** (CONF-047: a NOT_EXECUTED step there ends `cancelled (not_executed_no_retry)`, never called).
7. A user cancellation requested while the runtime was down is honoured by recovery. Recovery is itself
   recoverable (a crash during recovery recovers again).

**`RecoverySweeper`:**

- `candidates()` calls `s12_recovery_candidates(own_runtime_id, batch, lease_ttl_s)`. Discovery writes nothing.
- `sweep()` returns `[(tenant_id, execution_id, LoopResult)]` and takes at most `batch` runs; a later sweep takes
  the rest.
- Each run is isolated: an `Exception` while recovering one is logged at ERROR (`recovery_failed`, run, error
  type) and the sweep goes on. A `SimulatedCrash` is never caught.
- `run(stop, *, interval_s) -> int` sweeps until the `asyncio.Event` is set, waiting `interval_s` between sweeps.
  `ValueError` unless `0 < interval_s < 30`.

**Orphan rule (CONF-046, open; the function implements it).** A run is judged by its **latest** lease (highest
token):

| Latest lease | Orphaned? |
|---|---|
| active and unexpired | never |
| active but lapsed, or expired | at once |
| released | one lease TTL after its release (a live run between two steps is not taken; a silent one is) |
| none | one lease TTL after its ownership row was written |
| owned by the caller's own runtime | never (CONF-033) |

**Migration 017 hardening** (case `test_the_discovery_function_is_hardened`):

- `SECURITY DEFINER`, `STABLE`, returns `TABLE(tenant_id text, execution_id text)`.
- `SET search_path = <schema>, pg_temp` with **pg_temp last**: a temp table must not shadow `execution_runs`.
- It is the **only** `SECURITY DEFINER` function in the schema.
- It covers runs in `running` / `reconciling` only and writes nothing.

## Traps

- A recovered step probed although the ledger has its result (sabotage `M19_ledger_blind_recovery`).
- No dispatch marker written before the call (sabotage `M19_marker_never_written`). Recovery cannot then tell a
  dispatched attempt from one that never left.
- The sweeper taking its own runtime's runs (sabotage `M19_sweeper_takes_its_own`).
- Expiring every lease of the execution, live or not (sabotage `M19_takeover_steals`).
- Relying on the sweeper's acquisition to expire the crashed lease. With two workers the sweeper must expire it first
  (C26; this survived until the two-worker case was added).
- Reading checkpoints during recovery. The database is the truth (§13, CONF-044).

## Done when

- [ ] Every case of `M19_recovery.py` passes, including the 10 crash points.
- [ ] M01–M18 green; the invariant checker I1–I16 passes after every integration case.
- [ ] `owner_certify_s12.py --milestone M19`: all PASS, sabotage 4/4.
- [ ] CONF-042, 043, 044, 046, 047 ruled. Otherwise report M19 as blocked on S12-REC and list them.
