# Batch bundles: agent guide index (B1 = M1–M4, B2 = M5–M9, B3 = M10–M14, B4 = M15–M18, B5 = M19–M21)

These folders tell the coding agent **what to build, where, and under which rules** for all five batches of the
S12–S15 plan. They do not replace the plan, the gate or the autopilot; they point into them. When this folder
and a pinned document disagree, the pinned document wins and the agent STOPs (see "Precedence").

| Read in this order | What it gives you |
|---|---|
| 1. This file | Status of every batch, rules for all batches, the S12→S15 module map, the names the tests patch, how layers depend on each other |
| 2. `B1_M01-M04/`, `B2_M05-M09/`, `B3_M10-M14/`, `B4_M15-M18/` or `B5_M19-M21/` + `AGENT_GUIDE.md` | Batch entry conditions, order, per-file ownership, milestone targets, exit checks |
| 3. `<batch>/milestones/Mxx_*.md` | One milestone: interface, logic and conditions, rulings, traps, done checklist |
| 4. `<batch>/MANIFEST.md` | Every file the batch's golden tests load; for B3–B5, how to run the reference layer in a scratch checkout |
| 5. [`IMPROVEMENT_GUIDE_B3-B5.md`](IMPROVEMENT_GUIDE_B3-B5.md) | Extra points for an existing B3–B5 implementation: fix method, agent tests, validation runbook, cross-stage dependency map (does not change the flow above) |
| 6. [`IMPROVEMENT_GUIDE_B1-B2.md`](IMPROVEMENT_GUIDE_B1-B2.md) | The same for the built B1/B2 code: guard tests, silent-failure points, what B3–B5 rely on, and behaviour that must not be "fixed" |
| 7. [`ROADMAP_AFTER_S12.md`](ROADMAP_AFTER_S12.md) | Everything left after S12: owner close-out, M10–M21, certification, then the deferred phases in the gate's order with every leftover placed |
| 8. [`LAYER_A/ADAPTER_SPECS/README.md`](LAYER_A/ADAPTER_SPECS/README.md) | Layer A provider adapter specs: the standard (contract, before-send/after-send error rule, probe, observe, credentials, recorded-response tests), a template, and per-provider files for GoHighLevel (`crm`) and Gmail (`mail`) |

## Status of every batch (verified 2026-10-01 on `s12-work` `f4a8d5f`, PostgreSQL 16)

| Batch | Milestones | Code on `s12-work` | Golden | Sabotage | What is still open |
|---|---|---|---|---|---|
| [B1](B1_M01-M04/AGENT_GUIDE.md) | M1–M4 | **built** | 316 / 316 | 12 / 12 | owner rows only: re-pin, STOP-001 `applied`, M1 ★ schema review, `owner_verify` |
| [B2](B2_M05-M09/AGENT_GUIDE.md) | M5–M9, M8a | **built** | 174 / 174 | 21 / 21 | owner rows only: pin B2, close STOP-002, M8a ★ review, DEF-003 decision, `owner_verify` |
| [B3](B3_M10-M14/AGENT_GUIDE.md) | M10–M14 | not started (STOP-004, STOP-005 to close) | reference 184 / 184 | reference 39 / 39 | the next agent work; M14 ★ |
| [B4](B4_M15-M18/AGENT_GUIDE.md) | M15–M18 | not started | reference 135 / 135 | reference 12 / 12 | CONF-005 open (M15) |
| [B5](B5_M19-M21/AGENT_GUIDE.md) | M19–M21 | not started | reference 68 / 68 | reference 10 / 10 | CONF-042–047 open; M21 ★ |

On `s12-work`, `owner_certify_s12.py --milestone M9` (full) gives 18/21. The three failures are the owner rows
**S12-PIN** and **S12-REC**, plus **S12-S011** when the package is not importable: run with `PYTHONPATH=src` (then
`owner_certify.py` is 19/19). `docs/gates/s12_milestones.json` still shows M1 `red_confirmed` and the rest
`not_started`, because only the owner's checkpoint moves a status. **The agent's next milestone is M10, after the
owner closes the B1/B2 rows and STOP-004/005.**

**Reference layers (B3–B5).** B1 and B2 have none: their code is the live `s12-work` code. The B3–B5 folders carry the same merged reference `src/` (built through M21). B3 adds the two
files B4/B5 never load (`dispatch.py`, the reworked `live_authorization.py`); B5 adds `recovery.py`; B4 adds
`s14_dead_letter/`. Verified on 2026-10-01 (PostgreSQL 16) with all of them layered together: M01–M09 490, B3 184,
B4 135, B5 68 passed; every B3 sabotage patch caught (39/39); the frozen `tests/` suite 836 passed.

## Precedence (never invert it)

1. `docs/gates/S12_AUTOPILOT.md` (owner-pinned process) and the gate `docs/implementation/S12_S15_EXECUTION_GATE.md`.
   Inside the gate: Appendix A > rulings (C*, D*) > sections > repaired documents > code sketches.
2. Owner rulings in `docs/gates/S12_RECORDS.md` (status `ruled` or `fixed`).
3. The golden test file of the milestone (`tests_golden/s12/Mxx_*.py`). **Its module docstring is the interface
   contract**; its cases are the acceptance criteria.
4. The milestone card in `docs/implementation/S12_S15_IMPLEMENTATION_PLAN.md` §4.
5. These guides.
6. The reference implementation in `<batch>/src/`: **an example that passes, not a specification.** It is
   UNREVIEWED.

A conflict between 1–4 is a `CONF-nnn` row in `S12_RECORDS.md` (quote both sides with file:line) and, without a
ruling, a STOP. Never resolve it by editing a test or a pinned document.

## Ten rules for every batch

1. **Milestone order is fixed.** Work the first row of `docs/gates/s12_milestones.json` that is not `green` or
   `reviewed`. B1 and B2 are built: change them only additively, as their guides list. B3 starts only after M9 is `green`; B4 only after M14 (★) is `green`; B5 only after M18 is `green`.
   Never start a later card early "because the module is missing".
2. **Never edit:** `tests_golden/**` (including `tests_golden/sabotage/**` and fixtures), `tools/owner_*`,
   `tools/doc_consistency.py`, `tools/s12_tracker.py`, `docs/gates/*.sha256`, `docs/gates/s12_milestones.json`,
   `S12_PROGRESS.md`, `S12_TRACKER.md`, `S12_AUTOPILOT.md`, `docs/implementation/**`, migrations 001–015 (and
   016 / 017 once their milestone is green: add a new migration instead), and every
   frozen S0–S11 file (`src/` at tag `s0-s11-certified`, except the prototype list in
   `tests_golden/fixtures/code_scan.py`). Frozen files that S12 code imports include `src/contracts/step_execution.py`
   (`AdapterResult`, `FencedOut`, `Revoked`) and `src/contracts/worker.py`.
3. **Never skip, xfail, delete, weaken or re-parametrize a test**, and never change an expected value. A golden
   case you believe is wrong → STOP (gate §19.1).
4. **Additive only.** B3 fixes the execution-core interfaces; B4 and B5 add fields, methods and modules. Every
   signature that M10–M14 golden files fixed stays exactly as it is (`LoopDeps` field names and order of the required
   ones, `run_execution(deps, tenant_id, execution_id)`, `ReliabilityGuard`, `MockAdapter.program(...)`, ledger
   methods). New `LoopDeps` fields always have a default, so earlier golden files construct `LoopDeps` unchanged.
5. **Module paths and symbol names below are contracts.** Golden tests import them and sabotage patches
   monkeypatch them by name. Do not rename, move, split or merge them (see "Names the tests patch").
6. **Layering. These are the rules the scans enforce. Nothing else is assumed.**
   - `contracts/` imports nothing from `engine/` or `adapters/`.
   - `engine/stages/s12_execute/reliability.py` has no SQL and imports no `adapters.*` or `asyncpg` (M10).
   - No SQL write to an execution table in `src/engine/**` (M21). Every SQL statement lives in `adapters/postgres/`.
   - `*adapter*.call(` / `.probe(` / `.observe(` appear only in `s12_execute/reliability.py` (and the prototype
     `guard.py`). No engine file imports `adapters.runtime.mock_adapter` (M21).
   - `.probe(` (M13) and `.observe(` (M15) appear in no S12 file outside `s13_reconciliation/`,
     `s12_execute/reliability.py`, `contracts/adapter_interface.py` and `adapters/runtime/mock_adapter.py`. That is
     why the metrics method is `timing`, not `observe`.
   - S12–S15 code imports no `engine.*` module outside `engine.stages.s12`–`s15`, `engine.stages.s8_safety_gate`
     (the check library, never its `handler`) and M21's allowed list (M21).
   - The engine may import small adapter types where the reference does (`adapters.postgres.fencing.FenceHolder`
     in `loop.py`, `adapters.postgres.database.Database` in `recovery.py`). It never calls a repository's SQL
     directly. Wiring happens through `LoopDeps`.
7. **Every durable execution write goes through `fenced_write()`** (or a method that runs inside one fenced
   transaction). M21 scans for SQL writes outside it. The only designed exceptions are writes with no live owner to
   fence: `admission.py` (§7.2 creates the ownership row), `cancellation.py` (C16, the user's request),
   `PostgresDeadLetters.create_rollback` and `budget_reserver.settle_dead_letter_reservation` (M17, terminal run,
   D4/C27). They still run in a tenant transaction and validate every move. Add no others without a ruling.
8. **Row-level security is never bypassed.** No `SET row_security = off`, no reset of `app.current_tenant`, no
   second "raw" connection. Cross-tenant facts come from constraints (a primary-key conflict) or from the one
   `SECURITY DEFINER` function of migration 017 (ids only, CONF-042/046).
9. **No bare state strings.** States and reasons come from `contracts.execution_states` enums (M04 scans for bare
   literals). New enum members go there (e.g. `ConsolidationOutcome`).
10. **The reference `src/` is read, not copied.** Diff against it to understand a passable shape; write each file in
    the milestone that owns it, only the parts the card asks for, checked against the gate. Never `cp -r` the layer
    over `s12-work`. Never run `ruff --fix` over a directory (it rewrote two frozen files once): fix files one by one.

## S12 → S15 module map (target state after M21)

Owner milestone = the milestone whose golden file first requires the file. "Ref" = present in the bundle's `src/`;
"live" = built and verified on `s12-work` (B1/B2; owner sign-off pending), so there is no bundle copy.

| Layer | Path | Owner | What it holds | Ref |
|---|---|---|---|---|
| contracts | `contracts/execution_states.py` | M1, +M4, +M16 | Run/step/budget/lease/episode/dead-letter states and reasons; `ConsolidationOutcome` (M16) | yes |
| contracts | `contracts/confirmation_record.py` | M5 | `ConsumedConfirmation`, `ConsumedConfirmationReader` | live |
| contracts | `contracts/step_admission.py` | M8 | `AdmissionStatus`, `AdmissionDecision` (WORKER_LIFECYCLE §11, CONF-015), `DecisionLedger` | live |
| engine S12 entry | `engine/stages/s12_entry/{checks,admission,verifiers,confirmation}.py` | M5–M6, M8a | `check_entry` (§7.1 order), `admit_run`, `build_verifiers`, `confirmation_denial` | live |
| engine S12 | `engine/stages/s12_execute/transitions.py` | M3–M4 | `validate(machine, from, to, *, reason, closed=False)`, `IllegalStateTransition` | live |
| engine S12 | `engine/stages/s12_execute/settings.py` | M2, +M8a, +M19 | `ExecutionSettings.from_env` (C37) | live |
| engine S12 | `engine/stages/s12_execute/admission_control.py` | M8 | `AdmissionSnapshot`, `evaluate`, `admit_step`, `reject_outcome` | live |
| engine S12 | `engine/stages/s12_execute/{selection,eligibility}.py` | M8, M8a, +M12 | `select_worker`, `lease_for_step`; `WorkerCandidate`, `SelectionContext`, `filter_workers` | live |
| adapters pg | `adapters/postgres/{fencing,transition_log}.py` | M2, +M9 | `FenceHolder`, `check_fence`, `fenced_write`; `log_transition` | live |
| adapters pg | `adapters/postgres/execution.py` | M2 (prototype, fenced), +M12 (`PostgresExecutionStore`), +M14 (`cancel_requested`), +M15 (verifiers on the loaded run) | the loop's store | live + ref |
| adapters pg | `adapters/postgres/budget_reserver.py` | M9, +M10 (`reservation`), +M17 (`settle_dead_letter_reservation`) | `PostgresBudgetReserver`: the only budget writer (C31) | live |
| adapters pg | `adapters/postgres/{admission,confirmation_records,selection}.py` | M5–M8a | durable admission (§7.2, quota), the C20 reader, the selection reader | live |
| adapters pg | `adapters/postgres/migrations/015_s12_schema.sql` | M1 | the S12 schema (workers, leases, episodes, dead letters, ledger, checkpoints, C39); full as-built reference in [`B1_M01-M04/SCHEMA.md`](B1_M01-M04/SCHEMA.md). 001–015 are byte-identical in every reference layer: B3–B5 add only 016 and 017 | live |
| contracts | `contracts/adapter_interface.py` | M10 | `CallMeta`, `GuardedCall`, `ErrorClass`, `RETRYABLE`, `BaseAdapter` (probe/observe defaults), `ProbeOutcome`, `Observation`, `BudgetStateError` | yes |
| contracts | `contracts/idempotency.py` | M11 | `IdempotencyConflict`, ledger record types | yes |
| contracts | `contracts/verification.py` | M15 | `Verdict`, `VerificationLayer`, `LayerResult`, `VerificationOutcome` | yes |
| contracts | `contracts/envelope.py` | M18 | `Envelope`, `EnvelopeError` | yes |
| contracts | `contracts/metrics.py` | M21 | `MetricsHook`, `NoMetrics`, metric names | yes |
| engine S12 | `engine/stages/s12_execute/reliability.py` | M10, +M17 | `ReliabilityGuard`, `BudgetTracker`, `TimeoutManager`; `InverseBudget` (M17). No adapter imports, no SQL | yes |
| engine S12 | `engine/stages/s12_execute/retry_policy.py` | M11 | Retry ceilings per mutation, backoff | yes |
| engine S12 | `engine/stages/s12_execute/attempts.py` | M11–M12 | One step's attempts: live check, ledger, dispatch marker, guarded call | yes |
| engine S12 | `engine/stages/s12_execute/dispatch.py` | M12 | `InProcessDispatcher` | B3 only |
| engine S12 | `engine/stages/s12_execute/loop.py` | M12, +M13–M21 | `topological_order`, `LoopSettings`, `LoopDeps`, `LoopResult`, `run_execution`; `recover_execution` (M19) | yes (786 lines, all milestones merged) |
| engine S12 | `engine/stages/s12_execute/fault_injection.py` | M19 | `POINTS`, `SimulatedCrash`, `NoFaults` | yes |
| engine S12 | `engine/stages/s12_execute/recovery.py` | M19 | `RecoverySweeper` | B5 only |
| engine S13 | `engine/stages/s13_reconciliation/probe.py` | M13 | `resolve_execution` (EXECUTION episode probe path). The only engine module besides `reliability.py` that may call `.probe(` | yes |
| engine S13 | `engine/stages/s13_reconciliation/verification.py` | M15 | `required_verification_layers`, `parse_semantic`, `StepVerifier` | yes |
| engine S13 | `engine/stages/s13_reconciliation/consolidation.py` | M16 | `consolidation_outcome(steps)` (pure) | yes |
| engine S14 | `engine/stages/s14_dead_letter/retry.py` | M17 | `retry_dead_letter` | B4 only |
| engine S14 | `engine/stages/s14_dead_letter/rollback.py` | M17 | `rollback_execution`, `RollbackReport`, `RollbackStep` | B4 only |
| engine S15 | `engine/stages/s15_final_state/response.py` | M18 | `StepSummary`, `RunSummary`, `build_envelope` (pure) | yes |
| adapters runtime | `adapters/runtime/circuit_breaker.py` | M10 | `InProcessCircuitBreaker` with `allow`, `record_success`, `record_failure`, `record_ignored` | yes (patch) |
| adapters runtime | `adapters/runtime/reliability.py` | M10 | `InProcessBulkhead`, `InProcessRetryStormGuard`, `InProcessHealthMonitor`, `InProcessBilling` | yes |
| adapters runtime | `adapters/runtime/mock_adapter.py` | M10, +M15 | `MockAdapter` (per-`kernel_op_id` programs, side-effect ledger per key; M15 adds `data["id"]`, `observe=`, `observe_unknown=`) | yes |
| adapters pg | `adapters/postgres/idempotency.py` | M11 | `PostgresIdempotencyLedger` (claim/lookup/store; failure rows keep the class, never the body) | yes |
| adapters pg | `adapters/postgres/step_attempts.py` | M11–M12 | `PostgresStepAttempts` (`mark_dispatched`, `dispatched`) | yes |
| adapters pg | `adapters/postgres/execution_events.py` + migration 016 | M12 | Append-only ledger (`insert_event`, recorder); M19 adds `layer_verdicts` | yes |
| adapters pg | `adapters/postgres/kernel_policy.py` | M12 | Retry safety per kernel op | yes |
| adapters pg | `adapters/postgres/reconciliation.py` | M13, +M15, +M19 | `PostgresEpisodes` (`open`, `close`; M15 refuses NOT_EXECUTED for VERIFICATION; M19 `find_open`) | yes |
| adapters pg | `adapters/postgres/cancellation.py` | M14 | `PostgresCancellation` | yes |
| adapters pg | `adapters/postgres/live_authorization.py` | M14 | `PostgresLiveAuthorization(scopes, *, database, credentials)` (rework of the prototype) | B3 only |
| adapters pg | `adapters/postgres/consolidation.py` | M16 | `PostgresConsolidator` (`consolidate`, `__call__`, `cancel`) | yes |
| adapters pg | `adapters/postgres/dead_letters.py` | M17 | `PostgresDeadLetters` | yes |
| adapters pg | `adapters/postgres/run_summary.py` | M18 | `PostgresRunSummaries.load` | yes |
| adapters pg | `adapters/postgres/leases.py` | M7, +M12 (`holder=`), +M19 | `PostgresLeaseManager`; M19 adds `acquire(..., skip_locked=False)`, `expire_lapsed` | yes (patch) |
| adapters pg | migration `017_recovery_candidates.sql` | M19 | `s12_recovery_candidates(runtime_instance_id, limit, orphan_after_s)`, `SECURITY DEFINER`, ids only | yes |

Prototype files that the gate supersedes (`s13_reconciliation/handler.py`, `s14_verification/handler.py`,
`s15_final_state/handler.py`, `s12_execute/guard.py`) are not frozen, but **no B4/B5 card asks to rework them**. Leave
them alone unless a golden case fails because of them. M13 fails if `guard.py` (or any S12 file outside the allowed
list) contains `.probe(`.

## How the stages hand over (one run)

```text
S12 entry (M6) ──► run_execution(deps)                                   engine/s12_execute/loop.py
  per step, in topological order:
    admission (M8) → lease (M7) → reserve/lock budget (M9) → faults.hit(...)                 (M19 seams)
    attempts (M11–M12): live check (M14) → ledger lookup → dispatch marker → guard.call (M10)
       ok ─────────────► verification (M15, S13) ─ PASS ─► commit COMPLETED, budget COMMITTED
       │                       ├─ FAIL ──► FAILED (verification_failed), dead letter data/NONE (M17)
       │                       └─ UNKNOWN ► VERIFICATION episode ×3 ─► DEAD_LETTER, budget LOCKED, dead letter VERIFY
       timeout/uncertain ► probe path (M13, S13 probe.py) EXECUTION episode ×3
                               └─ INCONCLUSIVE ×3 ─► DEAD_LETTER, budget LOCKED, dead letter PROBE (M17)
       retryable error ──► retry (M11)  → exhausted ► FAILED, dead letter transient/NONE (M17)
  run ends ──► PostgresConsolidator.consolidate / .cancel (M16, S13) ─ one fenced transaction
           ──► PostgresRunSummaries.load → build_envelope (M18, S15)
  crash anywhere ──► RecoverySweeper.sweep → recover_execution (M19); real processes (M20)
  operator ──► retry_dead_letter / rollback_execution (M17, S14)
```

## Names the tests patch (keep them exactly)

Sabotage patches import these and replace them at run time. If a name moves, the sabotage errors instead of failing,
and the certifier's X-row refuses it.

| Module | Symbols (patched by name; keep them) |
|---|---|
| `engine.stages.s12_execute.loop` | `run_execution`, `topological_order` |
| `engine.stages.s12_execute.reliability` | `ReliabilityGuard.__init__` and its keyword names `adapter, bulkhead, breaker, budget, retry_storm, timeouts, health, billing, probe_timeout_s` (the M10 helper `_guard_base.py` wraps them), `ReliabilityGuard.call`, `.probe`, `BudgetTracker.check` |
| `engine.stages.s12_execute.recovery` | `RecoverySweeper.__init__`, `RecoverySweeper.candidates` |
| `engine.stages.s13_reconciliation.probe` | `resolve_execution` |
| `engine.stages.s13_reconciliation.verification` | `required_verification_layers`, `parse_semantic` |
| `engine.stages.s13_reconciliation.consolidation` | `consolidation_outcome` |
| `engine.stages.s14_dead_letter.retry` | `retry_dead_letter` |
| `engine.stages.s15_final_state.response` | `build_envelope` |
| `engine.stages.s5_provider_resolution.handler` | `handle` (the M21 re-resolution trap: S12–S15 never call it) |
| `adapters.runtime.mock_adapter` | `MockAdapter.call` |
| `adapters.postgres.idempotency` | `PostgresIdempotencyLedger.__init__`, `.lookup`, `.store` |
| `adapters.postgres.step_attempts` | `PostgresStepAttempts.mark_dispatched`, `.dispatched` |
| `adapters.postgres.leases` | `PostgresLeaseManager.__init__`, `.acquire`, `.release` |
| `adapters.postgres.budget_reserver` | `PostgresBudgetReserver.lock` |
| `adapters.postgres.reconciliation` | `PostgresEpisodes.open` |
| `adapters.postgres.cancellation` | `PostgresCancellation.__init__`, `.request` |
| `adapters.postgres.live_authorization` | `PostgresLiveAuthorization.__init__`, `.check` |
| `adapters.postgres.consolidation` | `PostgresConsolidator.__init__`, `.consolidate` |
| `adapters.postgres.dead_letters` | `PostgresDeadLetters.__init__`, `.create`, `.resolve` |
| `adapters.postgres.run_summary` | `PostgresRunSummaries.load` |
| `adapters.postgres.fencing` | `fenced_write` |
| `contracts.adapter_interface` | `ProbeOutcome` (`EXECUTED_SUCCESS`, `NOT_EXECUTED`, `INCONCLUSIVE`), `BaseAdapter.probe`, `GuardedCall` |
| `contracts.idempotency` / `contracts.step_execution` | `IdempotencyConflict` / `AdapterResult`, `FencedOut`, `Revoked` (frozen) |
| SQL (`.sql` patches) | triggers `execution_events_no_update` and `execution_events_no_delete` on `execution_events` (migration 016); policy `tenant_isolation` on every S12 table; `FORCE ROW LEVEL SECURITY` on `execution_steps`; the `execution_steps` row moves (a patch adds its own trigger there) |

The engine must **call through these names at run time** (`ledger.lookup(...)`, `probe.resolve_execution(...)`),
not hold a private copy taken at import (`from ... import resolve_execution as _r` bound before the patch), or the
sabotage never reaches the code and the X-row fails.

## Rulings that bind B3, B4 and B5 (B1/B2 rulings: CONF-002–020, listed in their guides)

Ruled (apply them): CONF-019 (runtime list in `SelectionContext`), CONF-021 (frozen `AdapterResult`), CONF-022
(breaker per provider), CONF-023 (4xx trial releases, `TimeoutError` = timeout), CONF-024 (key
`{request_id}:{plan_step_id}`), CONF-025 (ledger rows only for adapter results), CONF-026 (the `execution_events`
table), CONF-027 (admission snapshot and pre-flight injected), CONF-028, CONF-029 (in-line loop probes with the run
RUNNING; RECONCILING only in recovery), CONF-030 (`credential_valid`), CONF-031, CONF-032 (gate 8 is a DELAY),
CONF-033 (never take over your own run), CONF-034 (plan digest on every load), CONF-035 (port the `tests_postgres`
prototype loop tests), CONF-036 to CONF-041 (B4). B3 has no open ruling.

**Open (the certifier's S12-REC row fails until the owner rules them):**

| ID | Milestone | Blocks |
|---|---|---|
| CONF-005 | M15 | No `AutonomyLevel` source. CONF-041 already says to select layers by mutation and risk only. The owner still has to close CONF-005 before M15 can certify |
| CONF-042, 043, 044, 046, 047 | M19 | Recovery discovery function, tampered in-flight step, checkpoints as a hint, the orphan rule, RECONCILING resolution |
| CONF-045 | M20 | Lease renewal during a step |

The agent implements the proposal text of an open CONF only after the owner rules it. Until then, M19/M20 code may be
written and run, but the milestone is not reported as reached. List the open ids in the milestone report.

## Commands (repository root)

```bash
python tools/owner_certify_s12.py --selftest                 # every row OK, else STOP
python tools/owner_certify_s12.py --milestone M15 --fast     # loop iterations
python tools/owner_certify_s12.py --milestone M15            # milestone end: sabotage + 5x concurrency
python -m pytest tests -q                                    # OWN-13: must stay green
python -m pytest tests_golden/s12/M15_verification.py -q     # read the first failing case
git diff --name-only <milestone-start-commit>..HEAD          # scope check: only files you may change
```

`TEST_DATABASE_URL` must name a database ending in `_test`. Never print `.env` values.
