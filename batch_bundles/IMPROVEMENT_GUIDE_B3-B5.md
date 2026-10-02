# Improvement guide for B3, B4, B5 (M10–M21): extra points, fix method, tests, cross-stage checks

**What this is.** A second-pass review of the B3–B5 guides, golden tests and draft reference code, written for an agent
whose B3–B5 implementation already exists, at least partly. Every item below is something the golden tests do **not**
fully pin, a place where a correct-looking implementation can still fail silently, or a dependency between stages
that a local fix can break.

**What it is not.** It does not replace the milestone guides (`B3_M10-M14/`, `B4_M15-M18/`, `B5_M19-M21/`) and it
changes no existing flow:

- Milestone order, the golden files, the autopilot loop and the "files you may change" lists stay exactly as they are.
- Every improvement here is **additive**. Each one comes with an agent test in `tests_agent/` (never counted by the
  certifier, allowed by the autopilot). Where an item would touch a frozen or pinned file, or needs a ruling, it says
  so and stops there.

**Basis.** These sources only: the golden tests on `s12-work` (`tests_golden/s12/M10…M21`, `tests_golden/sabotage/`),
the B3–B5 draft reference in `batch_bundles/*/src/`, the gate, the plan, and the records (`S12_RECORDS.md`,
`S12_DEFECTS.md`, `S12_STOPS.md`). The agent's own implementation on its VPS was **not** visible to this review. Run
the checks in §5 against it.

---

## 1. Baseline the guides were checked against (2026-10-01)

| Milestone | Golden cases | Test functions | Sabotage | Draft reference result |
|---|---|---|---|---|
| M10 guard | 64 | 35 | 10 | 64/64 |
| M11 idempotency and retry | 46 | 25 | 10 | 46/46 |
| M12 loop | 33 | 30 | 8 | 33/33 |
| M13 probe | 13 | 13 | 4 | 13/13 |
| M14 revocation and cancel | 28 | 18 | 7 | 28/28 |
| M15 verification | 51 | 29 | 3 | 51/51 |
| M16 consolidation | 31 | 15 | 3 | 31/31 |
| M17 dead letter | 37 | 27 | 3 | 37/37 |
| M18 response | 16 | 10 | 3 | 16/16 |
| M19 recovery | 40 | 25 | 4 | 40/40 |
| M20 multiprocess | 10 | 8 | 4 (2 SQL) | 10/10, x5 |
| M21 journeys | 18 | 18 | 2 | 18/18 |
| **Total** | **387** | | **61** | **387/387**; with M01–M09 (490) and `tests/` (836) green |

**Doc consistency (checked mechanically):**

- Every function count, sabotage name and module path in the B3–B5 guides exists.
- Every "state (reason)" pair they mention is a legal Appendix A edge in `transitions.py`.
- Every class and function they name exists in the drafts, the goldens or `s12-work`.
- One omission: the B5 milestone files do not state their case counts (40 / 10 / 18 above).

**Schema:** migrations 001–015 are byte-identical in every draft layer. B3–B5 need **only** 016 (M12) and 017 (M19).
See `B1_M01-M04/SCHEMA.md`.

---

## 2. Method: how to apply any item without disturbing the flow

Use the same loop for every item. Never fix two items in one commit.

```text
1. LOCATE    find the item's files (column "Files"); read the golden docstring of the milestone that owns them.
2. PROVE     write the agent test named in the item under tests_agent/ (e.g. tests_agent/test_imp_m11_conflict.py).
             Run it: it must FAIL on the current code if the item is a real gap, or PASS if the code already
             handles it (then keep the test as a guard and stop: nothing to fix).
3. FIX       smallest change in a file the milestone may change. Additive only: new parameters get defaults,
             new LoopDeps / LoopSettings fields get defaults, no renamed or moved symbol (README "Names the tests patch").
4. VERIFY    a) the agent test passes;
             b) the owning milestone's golden file and its sabotage patches;
             c) every DOWNSTREAM golden file listed for that milestone in §3 (the hub rule);
             d) python -m pytest tests -q (836) and python tools/owner_certify.py (19/19, PYTHONPATH=src);
             e) python tools/owner_certify_s12.py --milestone <highest built> --fast.
5. RECORD    commit "s12: Mxx IMP-nn <what>"; one line in docs/gates/s12_autopilot_log.md (append only).
6. STOP      instead of fixing when the item says "ruling" or "owner", when a golden case would have to change,
             or when a frozen/pinned file is involved. Write STOP-nnn / CONF-nnn as the autopilot says.
```

**Agent-test rules:**

- Use the golden fixtures (`db_schema`, `run`, the `tests_golden.s12.Mxx` helpers). Import them; never copy them.
- Never import from `batch_bundles/`.
- A database test needs `TEST_DATABASE_URL` ending in `_test`.

---

## 3. Cross-stage dependency map (what a change can break)

The golden files reuse each other's helpers. A change to the interface behind a helper breaks every file that
imports it:

| Hub (defined in) | Imported by golden files | Built from (reference) | Rule |
|---|---|---|---|
| `M12_loop._admit, _deps, _loop, _mock, _state, _steps, _order, _ops, _moves, _events, PASSING, CHAIN, Credentials, _take_over, _snapshot, Recorder, _force_plan_update, _retamper` | **M13, M14, M15, M16, M17, M18, M19, M20, M21** | `run_execution`, `LoopDeps`, `LoopSettings`, S12 entry (`admit_run`, `PostgresExecutionAdmission`), `PostgresSelectionReader`, `PostgresLeaseManager`, `PostgresBudgetReserver`, `PostgresExecutionStore`, `PostgresExecutionEvents`, `MockAdapter`, `AdmissionSnapshot` | any change to these signatures → re-run M12–M21 |
| `M17_dead_letter._dl_deps` (the full runtime: guard, verification, consolidation, dead letters) | **M18, M19, M20 (and its subprocess fixture `runtime_process.py`), M21** | `StepVerifier`, `PostgresConsolidator`, `PostgresDeadLetters`, `PostgresEpisodes`, `ReliabilityGuard`, `InverseBudget` | → re-run M17–M21, and M20 five times |
| `M15_verification._verifying, ScriptedVerification, _outcome` | M16, M17 | `StepVerifier`, `VerificationOutcome` | → re-run M15–M17 |
| `M16_consolidation._holder, _consolidating` | M17, M19 | `PostgresConsolidator`, `FenceHolder` | → re-run M16, M17, M19 |
| `M10_guard._guard, _binding, _context` | M15, M17 | `ReliabilityGuard`, components, `MockAdapter` | → re-run M10, M15, M17 |
| `M19_recovery.CrashAt, _crash, _sweep, _time_passes` | M21 | `fault_injection`, `RecoverySweeper`, `recover_execution` | → re-run M19, M21 |

Code that later milestones change in **earlier** files (all additive; the full list is in the B1/B2 guides §4/§5):

| File (owner) | Changed by |
|---|---|
| `adapters/postgres/leases.py` (M7) | M12 `holder=`; M19 `skip_locked=`, `expire_lapsed` |
| `adapters/postgres/budget_reserver.py` (M9) | M10 `reservation()`; M17 `settle_dead_letter_reservation()` |
| `adapters/postgres/execution.py` (M2 prototype) | M12 `PostgresExecutionStore`; M14 `cancel_requested`; M15 verifiers on the loaded run |
| `adapters/postgres/reconciliation.py` (M13) | M15 refuses NOT_EXECUTED for VERIFICATION; M19 `find_open` |
| `adapters/postgres/execution_events.py` (M12) | M19 `layer_verdicts` |
| `adapters/runtime/mock_adapter.py` (M10) | M13 `timeout_not_executed` with `n`; M15 `data["id"]`, `observe=`, `observe_unknown=` |
| `engine/stages/s12_execute/reliability.py` (M10) | M17 `InverseBudget` |
| `engine/stages/s12_execute/loop.py` (M12) | M13 probe path; M14 live and cancel; M15 verification; M16 `cancel_run`; M17 `dead_letters`; M19 `faults`, `recover_execution`; M21 `metrics` |
| `engine/stages/s13_reconciliation/probe.py` (M13) | M19 `faults=`, `metrics=`; M21 probe counter |
| `contracts/execution_states.py` (M1) | M16 `ConsolidationOutcome` |
| `engine/stages/s12_execute/settings.py` (M2) | M19 `recovery_sweep_interval_s` |

**Rule:** a later milestone that edits an earlier file re-runs **that earlier milestone's golden file and sabotage**
too, not only its own.

---

## 4. Improvement items

Format: **ID — title.** Why (gate, ruling or review) · Files · Fix method · Agent test · Validate and cross-check.
"Pinned" means a golden case already covers it, so the item is a guard test only.

### 4.1 Cross-cutting (apply in whichever milestone you are in)

**IMP-X1: Keep the hub interfaces stable.**
- Why: §3. A renamed `LoopDeps` field, or a required parameter added to `StepVerifier` or `PostgresDeadLetters`, breaks
  6–9 golden files at once, including the M20 subprocesses.
- Files: `loop.py`, `s13_reconciliation/verification.py`, `adapters/postgres/{dead_letters,consolidation,reconciliation}.py`.
- Fix: new fields and parameters always get defaults; never reorder the required `LoopDeps` fields.
- Agent test: `tests_agent/test_imp_x1_hub_signatures.py`. Use `inspect.signature` / `dataclasses.fields` to assert
  the required `LoopDeps` fields are exactly `runtime_instance_id, store, events, admission, selection, leases,
  budget, kernel_policy, preflight, guard, idempotency, attempts, live, verify, consolidate, sleep, settings`, in
  that order, and that every later field has a default.
- Validate: M12–M21 golden.

**IMP-X2: The unfenced-write registry.**
- Why: README rule 7; M21 `test_no_durable_execution_write_happens_outside_fenced_write` only checks that a writing
  file *mentions* `fenced_write`/`check_fence`. A file that uses it once and writes unfenced elsewhere passes.
- Files: every `adapters/postgres/*.py`.
- Fix: none unless the test finds one.
- Agent test: `tests_agent/test_imp_x2_unfenced_writes.py`. Parse each adapter; for every `INSERT/UPDATE/DELETE` on
  an execution table, assert it sits in a function whose body is passed to `fenced_write`, calls `check_fence`, or is
  one of the four designed exceptions: `admission.py` (§7.2), `cancellation.py` (C16), `PostgresDeadLetters.create_rollback`,
  `budget_reserver.settle_dead_letter_reservation` (D4/C27).
- Validate: M21 architecture cases.

**IMP-X3: Patched names exist.**
- Why: sabotage patches replace names by string at run time. A rename makes a patch error out, so the X-row fails
  for the wrong reason.
- Agent test: `tests_agent/test_imp_x3_patched_names.py`. For each module and symbol in README "Names the tests
  patch", import it and assert the attribute exists.
- Validate: `owner_certify_s12.py --milestone Mxx` (full: X rows).

**IMP-X4: Call through the module, never a frozen alias.**
- Why: `M21_probe_uncounted` patches `probe.resolve_execution` and `M19_ledger_blind_recovery` patches
  `PostgresIdempotencyLedger.lookup`. Code that did `from …probe import resolve_execution` at import time keeps the
  unpatched function, so the sabotage is never caught.
- Files: `loop.py`, `recovery.py`, `attempts.py`.
- Fix: `from engine.stages.s13_reconciliation import probe` then `probe.resolve_execution(...)`; call ledger methods
  on the instance.
- Agent test: `tests_agent/test_imp_x4_late_binding.py`. Monkeypatch `probe.resolve_execution` with a recorder, run
  one uncertain step (M13 helpers), and assert the recorder was called.
- Validate: X-M13, X-M19, X-M21.

**IMP-X5: Redaction everywhere, not just where M18 looks.**
- Why: §12, §21 S6. M18 checks 9 tables and the log records of three scenarios. A new `logger.error(f"…{exc}")` in an
  untested path leaks.
- Agent test: `tests_agent/test_imp_x5_no_exception_text_in_logs.py`, an AST scan of S12–S15 files. A logging call
  whose arguments contain `str(exc)`, `repr(exc)`, `f"{exc}"`, `exc.args` or `traceback.format_*` fails. Only
  `type(exc).__name__` is allowed.
- Validate: M10 leak case, M18 redaction cases.

**IMP-X6: `SimulatedCrash` is never swallowed.**
- Why: §15.2, M19. An `except BaseException:` that does not re-raise hides a crash point.
- Agent test: `tests_agent/test_imp_x6_no_swallowed_baseexception.py`, an AST scan of S12–S15 files. Every
  `except BaseException` / bare `except:` handler must end in `raise`.
- Validate: M19 `test_the_ten_points_are_named_inert_by_default_and_a_crash_is_never_swallowed`.

**IMP-X7: A step longer than the lease TTL (silent takeover).**
- Why: CONF-045 (open). There is no lease renewal during a step, and settings do not relate `step_timeout_s` to
  `lease_ttl_s`. The golden "valid" settings even set both to 30 s. A step running past the TTL can be taken over
  mid-call; the old owner's result is then fenced out and probed (safe, but wasteful and noisy).
- Fix: **do not add a hard check**: it would fail the pinned M02 and M21 settings cases. Optionally log one WARNING
  at startup when `step_timeout_s >= lease_ttl_s` (no behaviour change). Otherwise wait for the CONF-045 ruling.
- Agent test: `tests_agent/test_imp_x7_ttl_warning.py`, only if the warning is added.
- Validate: M02, M21 settings cases unchanged.

**IMP-X8: Hard-coded admission timings (§21 S1).**
- Why: `admission_control.QUEUE_RETRY_AFTER_MS = 1000` and `DELAY_RETRY_AFTER_MS = 500` are module constants. §21 S1
  wants infrastructure timings in the settings object, and the M8 log noted "retry delays to settings" for M12.
- Fix: optional `ExecutionSettings` fields with these defaults; `admit_step` keeps working without them. This is a
  B2 file: additive only, and re-run M08 and its 4 patches.
- Agent test: `tests_agent/test_imp_x8_admission_timing_settings.py`. With env unset the defaults are 1000/500; with
  env set they are read.
- Validate: M08, M12, M21 settings.

**IMP-X9: Review the two bundle-authored files.**
- Why: `dispatch.py` and the reworked `live_authorization.py` in the B3 bundle were written while assembling the
  bundle (MANIFEST). They are UNREVIEWED, like all draft code, but newer.
- Fix: if your implementation was derived from them, re-read them against M12 and M14.
- Agent test: `tests_agent/test_imp_x9_live_check_order.py`. Kill switch beats a deactivated user, a retired
  capability beats an inactive binding, an inactive binding beats an invalid credential: assert the reason when
  several are revoked at once (the golden checks one at a time).
- Validate: M14 and its 7 patches.

**IMP-X10: Keep `s12-work`'s `admission_control.py` wording.**
- Why: the draft copies carry older docstrings, from before CONF-032 and DEF-005.
- Fix: never copy the draft file over; diff and keep `s12-work`.
- Validate: `git diff origin/s12-work -- src/engine/stages/s12_execute/admission_control.py` shows only your
  intended changes.

### 4.2 B3: M10–M14

**IMP-M10-1: Breaker key granularity (CONF-022).**
- Why: the breaker is per provider in this phase; per (provider, operation) comes later (ADR-5). The retry-storm
  guard **is** per (provider, operation).
- Fix: none now. Keep the two keys distinct.
- Agent test: `tests_agent/test_imp_m10_breaker_keys.py`. Opening the breaker for provider P blocks every operation
  of P; a retry storm on (P, op1) does not block (P, op2).
- Validate: M10.

**IMP-M10-2: Prototype `guard.py` still exists.**
- Why: M21 allows its direct adapter call as "a guard too", but M13 forbids `.probe(` in it.
- Fix: do not extend it; new code uses `ReliabilityGuard`. If nothing imports it after M12, leave the deletion to
  change control (CONF-011).
- Agent test: `tests_agent/test_imp_m10_no_new_guard_users.py`. No S12–S15 module except the prototype loop imports
  `s12_execute.guard`.
- Validate: M13, M21 scans.

**IMP-M11-1: Ledger store without an RLS bypass (pinned, but often broken).**
- Why: §8 step 8 (gate lines ~1612–1617). This is exactly where the earlier attempt deleted golden cases and bypassed
  RLS.
- Fix: `INSERT … ON CONFLICT (idempotency_key) DO NOTHING`, then `SELECT` under the tenant's RLS. Not visible means
  `IdempotencyConflict`.
- Agent test: `tests_agent/test_imp_m11_no_rls_bypass.py`, a scan: no `row_security`, `set_config('app.current_tenant'`
  outside `database.py`, `SET ROLE`, or a second pool in `adapters/postgres/idempotency.py`.
- Validate: M11 conflict and fenced cases; M18 `M18_ledger_keeps_bodies`.

**IMP-M11-2: A failure row keeps the class only.**
- Why: §21 S6. M18 pins it later, so building it right in M11 avoids an M18 regression.
- Agent test: `tests_agent/test_imp_m11_failure_row_has_no_body.py`. Store `AdapterResult("error", False,
  "client_error", {"body": "token=abc"})`; the row's `result` contains no `body` and no `"token"`.
- Validate: M11, M18.

**IMP-M11-3: An expired record never authorises a call.**
- Why: gate lines ~1618–1621. "Keep the TTL filter" is right, but re-calling after expiry is wrong.
- Agent test: pinned (`test_an_expired_record_is_no_record_and_never_authorises_a_blind_call`). Add
  `tests_agent/test_imp_m11_expired_with_marker.py`: an expired row **plus** a dispatch marker at n gives `uncertain /
  dispatched_without_record`, and 0 calls.
- Validate: M11, M19 expired-record case.

**IMP-M12-1: Close DEF-002 and DEF-004 explicitly.**
- Why: `S12_DEFECTS.md` lists both as "open, fix in M12".
- Fix: the rewrite removes them. Append the closing rows with the commit.
- Agent test: `tests_agent/test_imp_m12_step_start_atomic.py`. Inject a failure between the step start and the lock
  (wrap `reserver.lock` to raise after its SQL); after rollback the step is still `pending` **and** the reservation
  still `reserved`.
- Validate: M12 (`M12_lock_in_own_transaction`), I5.

**IMP-M12-2: Port the prototype loop tests (CONF-035).**
- Why: `tests_postgres/test_step_loop.py` and `test_chain_full_stack.py` stop importing once M12 lands.
- Fix: port them to `LoopDeps`/`run_execution` with the same scenarios. Never delete them.
- Validate: `pytest tests_postgres` total stays 330 (log it).

**IMP-M12-3: The loop result equals the database.**
- Why: a sabotage once survived by persisting other states (B3 review).
- Agent test: `tests_agent/test_imp_m12_result_matches_rows.py`. For every M12 scenario helper, compare
  `LoopResult.steps` with `execution_steps`.
- Validate: M12.

**IMP-M13-1: `IdempotencyConflict` on the probe path (not pinned).**
- Why: B3 review known gap. The draft raises it in `probe.py`, but no golden case covers it.
- Agent test: `tests_agent/test_imp_m13_probe_conflict.py`. Seed a ledger row for the step's key with another
  `kernel_op_id`, force an uncertain attempt, and assert `IdempotencyConflict` and 0 probes.
- Validate: M13, M11.

**IMP-M13-2: The in-line loop never enters RECONCILING (CONF-029).**
- Agent test: `tests_agent/test_imp_m13_no_reconciling_inline.py`. Across all M13 scenarios, no run transition
  `running → reconciling` appears in `state_transitions`.
- Validate: M13, M19 (where RECONCILING is allowed).

**IMP-M13-3: The inconclusive backoff never shrinks.**
- Why: pinned for the defaults only.
- Agent test: with `probe_backoff_s=0.2`, record the sleeps: each is ≥ 0.2, non-decreasing, and none after the last.
- Validate: M13.

**IMP-M14-1: Priority when several revocations hold.**
- Why: the golden revokes one thing at a time. See IMP-X9.

**IMP-M14-2: Credential-check exception.**
- Why: the golden accepts `authorization_revoked` **or** `credential_invalid` for a failing `credential_valid`; the
  draft returns `authorization_revoked`.
- Fix: pick one and pin it.
- Agent test: `tests_agent/test_imp_m14_credential_error_reason.py` asserts your choice. Record the choice in the
  milestone report (CONF-030 spirit: fail closed).

**IMP-M14-3: A pause mid-run (C39) also holds across recovery.**
- Agent test: set a tenant pause after admission, then run M19's `_crash`/`_sweep`; nothing is cancelled and the run
  completes.
- Validate: M14, M19.

### 4.3 B4: M15–M18

**IMP-M15-1: CONF-005 is open.**
- Why: no AutonomyLevel source; layer selection is by mutation and risk only (CONF-041).
- Fix: none. Report M15 as blocked on S12-REC until the owner rules.

**IMP-M15-2: Semantic and human layers are not exercised in the loop.**
- Why: B4 review known gap: certified risks are below 0.7, and IRREVERSIBLE cannot be certified here.
- Agent test: `tests_agent/test_imp_m15_semantic_in_loop.py`. Use `ScriptedVerification`-style injection, or a
  binding row with `effective_risk = 0.7`, through `StepVerifier` in the loop: the semantic layer runs, malformed
  output gives a VERIFICATION episode, and the model sees only (expected, observed).
- Validate: M15, M17.

**IMP-M15-3: Layer events before the commit, on every path.**
- Agent test: for success, FAIL and UNKNOWN, every `verification_layer` event's `seq` is lower than the step's
  terminal transition (join `execution_events` with `state_transitions` by time order).
- Validate: M15, M19 (Crash B and C rely on it).

**IMP-M16-1: Refund edge cases.**
- Agent test: `tests_agent/test_imp_m16_refund_edges.py`:
  - a run created exactly at a period boundary refunds the period that contains `created_at`;
  - a run with a workspace quota but no tenant quota refunds only the workspace row.
- Validate: M16 (`M16_refund_always`).

**IMP-M16-2: Consolidation is the only path that ends a run.**
- Agent test: an AST scan; outside `consolidation.py` and admission, no S12–S15 code calls `transition_run(...)` to
  a terminal state once `cancel_run` is wired.
- Validate: M16, M14.

**IMP-M17-1: Dead-letter schema facts.**
- Why: `B1_M01-M04/SCHEMA.md`. Evidence goes in `context`; `resolved` must follow the status
  (`chk_dead_letters_resolved`); `mutation_type` defaults to `R`; `is_idempotent` is never written.
- Fix: pass the step's mutation. Optionally set `is_idempotent` from the kernel op's `retry_safety != 'never'` (not
  pinned, harmless).
- Agent test: `tests_agent/test_imp_m17_record_columns.py`. A W step's record has `mutation_type = 'W'`; `resolved`
  flips with resolve and abandon.
- Validate: M17, I11.

**IMP-M17-2: No production path to retry a dead letter.**
- Why: B4 review: `retry_dead_letter` takes injected `probe`/`reverify` callables, and "an operator entry point is
  M21", but no M21 golden pins one.
- Fix: none without an owner assignment. Add the item to the deferred register at M21.

**IMP-M17-3: Records for errors §11 does not list.**
- Why: no record for `adapter_defect` or guard refusals (§11 is exhaustive).
- Fix: do not add records.
- Agent test: `tests_agent/test_imp_m17_no_record_for_defect.py`. An adapter defect leaves the step FAILED and 0
  `dead_letters` rows.

**IMP-M17-4: The unfenced writes stay narrow.**
- Agent test: `settle_dead_letter_reservation` on a reservation whose step is not DEAD_LETTER, or whose run is not
  terminal, raises `ValueError` and writes nothing; `create_rollback` on a live run raises.
- Validate: M17, IMP-X2.

**IMP-M18-1: Soft-quota upgrade text (CONF-020).**
- Why: the ruling says S15 adds upgrade text for `quota_exhausted`, but the draft `response.py` has none, M18 pins
  none, and an entry DENY never produces a run summary (S12 entry denials keep the S0–S11 `ExecuteResponse`
  mapping).
- Fix: ask the owner where the text goes (entry response vs envelope). Do not invent a mapping.

**IMP-M18-2: Redaction beyond the three M18 scenarios.**
- See IMP-X5. Also add `tests_agent/test_imp_m18_probe_failure_redaction.py`: a probe that raises with a secret in
  its message leaves no trace of the secret in `step_reconciliations.evidence` or the logs.

### 4.4 B5: M19–M21

**IMP-M19-1: Six open rulings.**
- CONF-042, 043, 044, 046 and 047 (M19) and CONF-045 (M20). Implement the proposal text, but report each milestone
  as blocked on S12-REC until the owner rules.

**IMP-M19-2: Checkpoints are never read.**
- Why: §13, CONF-044. Recovery must work from database state alone.
- Agent test: `tests_agent/test_imp_m19_no_checkpoint_reads.py`. Scan: no `SELECT … FROM checkpoints` in S12–S15
  code. Run one crash point with the `checkpoints` table emptied mid-run; the result is the same.
- Validate: M19.

**IMP-M19-3: The sweeper never blocks on one bad run.**
- Pinned (`test_one_run_that_cannot_be_recovered_does_not_stop_the_sweep`). Extend it in
  `tests_agent/test_imp_m19_sweep_isolation.py`: a run whose plan does not decode **and** a healthy run in the same
  batch; the healthy one completes and the bad one is DEAD_LETTER `plan_integrity`.

**IMP-M19-4: The discovery function stays the only `SECURITY DEFINER`.**
- Pinned. Also add a check that 017 sets `search_path` with `pg_temp` **last**, and that `EXECUTE` is not granted
  beyond what CONF-046 says.

**IMP-M20-1: Stability over speed.**
- Why: the C-row needs 5 passes in a row. A 4/5 pass is a race (usually a missing `FOR UPDATE` or `SKIP LOCKED`),
  never a flake.
- Method: run `for i in 1 2 3 4 5; do pytest -q tests_golden/s12/M20_multiprocess.py || break; done` before every
  M20 commit.
- Never touch `tests_golden/fixtures/runtime_process.py`.

**IMP-M20-2: Portability.**
- Pinned scan. Also run the agent tests on the certifier's OS; §21 S9 records the OS in the report.

**IMP-M21-1: Architecture scans read comments too.**
- Why: `localhost`, `postgres://`, `http://`, `:5432` and `laya` anywhere in S12 sources (docstrings included) fail
  the M21 scan.
- Agent test: run M21's architecture cases after every commit in B3–B5. They are fast and have no DB for the scans.

**IMP-M21-2: Metrics counts are exact.**
- Agent test: `tests_agent/test_imp_m21_metric_counts.py`. On the M13 inconclusive-x3 scenario, `probe` counts
  exactly 3; `dead_letter` counts 1 with `error_type=unknown_unresolved`; `step_outcome` counts once per terminal
  step.
- Validate: M21, `M21_probe_uncounted`.

**IMP-M21-3: The deferred register is complete.**
- Why: gate §21: every §14 deferred item and every open question, with a target phase.
- Checklist:
  - CONF-005, CONF-008, CONF-027 (production admission snapshot and pre-flight sources: **no producer exists in the
    drafts**), CONF-042–047 if still open;
  - the 14 unused columns in `SCHEMA.md`;
  - IMP-M17-2, IMP-M18-1, IMP-X7;
  - batch (C40) and replanning (C41);
  - vector memory, Laya (LB1–LB11), real adapters.

---

## 5. Validation runbook (run against your VPS implementation)

```bash
export TEST_DATABASE_URL=postgresql://…/<name>_test PYTHONPATH=$PWD/src
# 0. guardrails
git diff origin/s12-work -- tests_golden docs/gates/*.sha256        # must be empty
python tools/owner_certify_s12.py --selftest                         # every row OK
python tools/owner_certify.py                                        # 19/19 (needs PYTHONPATH=src)
# 1. golden by batch (stop at the first red)
python -m pytest -q tests_golden/s12/M0*.py                          # 490
python -m pytest -q tests_golden/s12/M1[0-4]_*.py                    # 184
python -m pytest -q tests_golden/s12/M1[5-8]_*.py                    # 135
python -m pytest -q tests_golden/s12/M19_*.py tests_golden/s12/M2*.py   # 68
# 2. sabotage of the highest built milestone (and of any earlier one whose files you touched)
for p in tests_golden/sabotage/M1[0-9]_* tests_golden/sabotage/M2*_*; do echo $p; done   # then GOLDEN_SABOTAGE=$PWD/$p per file
python tools/owner_certify_s12.py --milestone M14                    # full: X rows + C rows (x5)
# 3. regression suites
python -m pytest -q tests && python -m pytest -q tests_agent && python -m pytest -q tests_postgres   # 836 / all / 330
# 4. this guide's agent tests
python -m pytest -q tests_agent/test_imp_*.py
```

**Done** for an item: its agent test passes; the owning golden file and every downstream file in §3 pass; the
sabotage of every touched milestone is still caught; and the three regression suites hold their counts.

---

## 6. Item index

| ID | Stage | Kind | Needs a ruling? |
|---|---|---|---|
| X1 hub signatures | all | guard test | no |
| X2 unfenced-write registry | all | guard test | no |
| X3 patched names | all | guard test | no |
| X4 late binding | M13, M19, M21 | fix if red | no |
| X5 redaction scan | all | guard test | no |
| X6 crash not swallowed | M19+ | guard test | no |
| X7 step vs lease TTL | M12, M20 | warning only | CONF-045 |
| X8 admission timings to settings | M8/M12 | additive | no |
| X9 bundle-authored files | M12, M14 | review + test | no |
| X10 keep `admission_control` text | M12+ | process | no |
| M10-1, M10-2 | M10 | guard tests | no |
| M11-1, M11-2, M11-3 | M11 | guard tests | no |
| M12-1, M12-2, M12-3 | M12 | close DEF-002/004; port tests | no |
| M13-1, M13-2, M13-3 | M13 | guard tests | no |
| M14-1, M14-2, M14-3 | M14 | decide and pin; guard | no |
| M15-1 | M15 | block | CONF-005 |
| M15-2, M15-3 | M15 | agent tests | no |
| M16-1, M16-2 | M16 | agent tests | no |
| M17-1, M17-3, M17-4 | M17 | agent tests | no |
| M17-2 | M17/M21 | deferred register | owner |
| M18-1 | M18 | ask owner | CONF-020 placement |
| M18-2 | M18 | agent test | no |
| M19-1 | M19/M20 | block | CONF-042–047 |
| M19-2, M19-3, M19-4 | M19 | agent tests | no |
| M20-1, M20-2 | M20 | process | no |
| M21-1, M21-2 | M21 | agent tests | no |
| M21-3 | M21 | checklist | owner |
