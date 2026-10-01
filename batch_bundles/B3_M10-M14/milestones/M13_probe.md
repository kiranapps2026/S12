# M13: probe path and EXECUTION episodes (gate commit H, part 2) ⚙

| | |
|---|---|
| Gate | §9, C6, C12, C13, C18, §8 step 12, suite 8; Appendix A.2, A.7; invariants I6 and the C13 condition (from the transition log) |
| Rulings | CONF-028 (read re-execution episode: NOT_EXECUTED, evidence `read_reexecution_safe`), CONF-029 (the in-line loop probes with the run RUNNING; RECONCILING only in recovery) |
| Golden | `tests_golden/s12/M13_probe.py`: 13 cases |
| Sabotage (4) | `M13_inconclusive_guessed`, `M13_ledger_not_consulted`, `M13_retry_beyond_ceiling`, `M13_uncertain_as_failure` |
| Reference | `src/engine/stages/s13_reconciliation/probe.py` (54 lines, `resolve_execution`), `src/adapters/postgres/reconciliation.py` (`PostgresEpisodes`), `loop.py` (`_probe_and_settle`, `_not_executed`) |

## Files

| File | Action |
|---|---|
| `src/adapters/postgres/reconciliation.py` | **new**: `PostgresEpisodes(database)`, the `step_reconciliations` store. Every move validated by `transitions.validate("episode", …)`, logged and fenced |
| `src/engine/stages/s13_reconciliation/probe.py` | **new**: `resolve_execution(...)`, the probe path, called from the loop (C12). Keep that name: sabotage `M21_probe_uncounted` patches it later |
| `src/engine/stages/s12_execute/loop.py` | additive: `LoopSettings.step_timeout_s=None` (effective timeout `min(step.timeout, step_timeout_s)`), `probe_max_attempts=3`, `probe_backoff_s=1.0`; `LoopDeps.episodes=None`; the uncertain path |
| `src/adapters/runtime/mock_adapter.py` | `probes` list; `timeout_not_executed` with `n > 0` times out without executing `n` times, then succeeds |

## Logic and conditions

**Entering uncertainty** (`AttemptOutcome.kind == "uncertain"`):

| Cause | Step moves | Episode |
|---|---|---|
| timeout | `running → timeout (step_timeout) → pending_probe (step_timeout_probe)` | EXECUTION episode opened, logged `none → pending_probe (opened)` (`none` through `ReconciliationStatus.NONE`) |
| dispatched attempt without a record | `running → pending_probe (execution_uncertain)` | same |
| a **read** step | never probed: episode opened **and closed in one transaction** as NOT_EXECUTED (evidence `read_reexecution_safe`, CONF-028); step `pending (read_reexecution_safe)`, retried within its ceiling | |

**Each probe attempt:**

1. `pending_probe → reconciling (attempt_started)`.
2. **The ledger first.** A hit closes the episode as `ledger_hit` / `ledger_hit_failure` with outcome LEDGER_HIT and
   **no probe** (sabotage `M13_ledger_not_consulted`).
3. Otherwise `guard.probe(...)`:

| Probe answer | Episode | Step | Budget |
|---|---|---|---|
| EXECUTED_SUCCESS → verify PASS | `confirmed_success (executed_success)` | `completed (probe_executed_success)` | committed |
| EXECUTED_SUCCESS → verify FAIL | `confirmed_failure (verified_fail)`, outcome VERIFIED_FAIL | `failed (verification_failed)`, dependents SKIPPED | released |
| EXECUTED_FAILURE | `confirmed_failure (executed_failure)` | `failed (probe_executed_failure)`, dependents SKIPPED | released |
| NOT_EXECUTED | `confirmed_failure (not_executed)` | `pending (probe_not_executed)`, then retried as attempt `n + 1` with a **new reservation** if within the ceiling, else `cancelled (not_executed_no_retry)` (never for IRREVERSIBLE or a non-idempotent D; sabotage `M13_retry_beyond_ceiling`) | released |
| INCONCLUSIVE | `reconciling → pending_probe (inconclusive)`; `await sleep(d)` with `d >= probe_backoff_s`, never shrinking, **none after the last**; try again | | stays LOCKED |
| INCONCLUSIVE × `probe_max_attempts` | closed with outcome EXHAUSTED (status stays `pending_probe`; event `episode_closed`) | `dead_letter (probe_exhausted)`; every remaining PENDING step `cancelled (run_dead_lettered)` | stays **LOCKED** (D4) |

- **Never guess.** INCONCLUSIVE is never treated as success or failure (sabotage `M13_inconclusive_guessed`), and
  an uncertainty is never a plain failure (sabotage `M13_uncertain_as_failure`).
- **Run state (CONF-029):** the in-line loop probes with the run **RUNNING** and resolves before the next step.
  RECONCILING is entered only by recovery (M19), only when every other step is terminal (C13).
- **I6:** no uncertainty reaches a terminal state without passing through PENDING_PROBE. This is checked from the
  transition log.
- **Placement (C12):** probe and episode handling live in `s13_reconciliation/`. The string `.probe(` appears in no
  S12 file outside `s13_reconciliation/`, `s12_execute/reliability.py`, `contracts/adapter_interface.py` and
  `adapters/runtime/mock_adapter.py` (case `test_probe_handling_lives_in_the_s13_package`). That includes the
  prototype `guard.py`.

## Traps

- The probe module named or placed elsewhere (`s13_probe/`, `s12_execute/probe.py`). The path is
  `src/engine/stages/s13_reconciliation/probe.py`, and that file must exist.
- Returning `ProbeOutcome` as `.name` strings. Compare and return enum members.
- A NOT_EXECUTED retry that reuses the released reservation. It takes a new one.

## Done when

- [ ] 13/13 in `M13_probe.py`; M01–M12 green; I6 and the C13 condition pass.
- [ ] `owner_certify_s12.py --milestone M13`: all PASS, sabotage 4/4.
