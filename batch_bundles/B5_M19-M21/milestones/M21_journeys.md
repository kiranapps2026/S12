# M21: journeys, architecture suite, seams, certification (gate commit M) ★

| | |
|---|---|
| Gate | suites 2, 15, 19; §17 (the invariant checker after every journey); §20 (certification report template); §21 S1–S9, the performance baseline, the deferred register |
| Golden | `tests_golden/s12/M21_journeys.py` (18 functions) |
| Sabotage | `M21_resolver_after_s11`, `M21_probe_uncounted` |
| Reference | `src/contracts/metrics.py`; metrics calls in `loop.py` and `probe.py` |
| Checkpoint | **★ final owner review.** STOP after the milestone report |

## Files

| File | Action |
|---|---|
| `src/contracts/metrics.py` | **new**: `MetricsHook` (Protocol: `increment(name, **labels)`, `timing(name, value, **labels)`), `NoMetrics`, and the names `STEP_OUTCOME`, `PROBE`, `DEAD_LETTER`, `FENCED_OUT`, `STEP_DURATION_MS` |
| `src/engine/stages/s12_execute/loop.py` | additive: `LoopDeps.metrics = NoMetrics()`; emit the counters below |
| `src/engine/stages/s13_reconciliation/probe.py` | count every provider probe attempt (`metrics=` parameter from M19) |
| any S12 file | only to satisfy an architecture scan (remove a banned pattern, move a write into its adapter) |

## Metrics (exact)

| Name | When | Labels |
|---|---|---|
| `step_outcome` | once per step reaching a terminal state | `status` |
| `probe` | once per provider probe attempt | |
| `dead_letter` | once per dead-letter record | `error_type` |
| `fenced_out` | once per loop stopped by `FencedOut` | |
| `step_duration_ms` | once per step the loop runs (admission through settlement), via `timing` | |

The default `NoMetrics` returns `None` from both methods. The method is `timing`, never `observe`: `.observe(` is
reserved for verification (M15 scan).

## The eight journeys (S0 → S15)

Each journey follows the same frame:

1. Start from a state the **real** S0–S11 pipeline certified (`fixtures/certified.py`).
2. Admit through the S12 entry (M06).
3. Run the S12 loop with every B3–B4 component (M17's dependencies).
4. End with the S15 envelope (M18).
5. Run the invariant checker.

Throughout, a trap is armed: it fails the journey if S5 resolves again after S11.

| Journey | Expected end |
|---|---|
| happy path with dependencies | COMPLETED, in dependency order |
| retry then success | COMPLETED after a retryable error |
| timeout executed, resolved by the probe | COMPLETED, no second call |
| timeout not executed, then retry | COMPLETED on the retry |
| verification mismatch | PARTIAL, with a `data` dead letter |
| budget exhaustion mid-plan | CANCELLED `budget_exhausted`; the envelope lists the completed step |
| inconclusive probe | DEAD_LETTER, with metrics |
| crash mid-plan, then resume | COMPLETED through recovery |

Plus: a fenced-out loop is counted (`fenced_out` 1, `step_outcome{status=completed}` 1); the metrics hook is a
no-op by default; the per-step baseline over ≥ 200 steps is **recorded, with no threshold** (p50 / p95 printed).

## Architecture suite (scans over every S12 source file)

Six of these are standing rules that already pass. Keep them passing; never weaken them.

| Case | Rule |
|---|---|
| no re-resolution, no stage handler import | S12–S15 code imports no `engine.*` outside `engine.stages.s12`–`s15` and `ALLOWED_OUTSIDE` (`engine.stages.plan_steps`, `engine.control_plane.scope`, `engine.stages.s8_safety_gate.checks`, `.dependencies`, `engine.stages.s0_entry.activation`); never `s8_safety_gate.handler`. The frozen binding is used as is (sabotage `M21_resolver_after_s11`) |
| no adapter call outside the guard | `\w*adapter\w*.(call\|probe\|observe)(` only in `s12_execute/reliability.py` (and the prototype `guard.py`); no engine import of `adapters.runtime.mock_adapter` or `engine.providers` |
| no durable write outside `fenced_write` | no `INSERT INTO` / `UPDATE` / `DELETE FROM` on execution tables in `src/engine/**`; every adapter that writes them uses `fenced_write` or `check_fence` (exceptions by design: `admission.py`, `cancellation.py`) |
| no filesystem, hosts or Laya | none of: builtin `open(`, `.write_text(`, `.write_bytes(`, `pickle`, `shelve`, `localhost`, `127.0.0.1`, `postgres://` / `postgresql://`, `http(s)://`, `:5432`, `laya` (any case). This includes **comments and docstrings** |
| fault injection has no switch | `fault_injection.py` has no `environ` / `getenv`; `LoopDeps.faults` defaults to `NoFaults()` |
| settings from the environment, validated | `ExecutionSettings.from_env(env)`; inverted timeouts → `ValueError`; `0 < recovery_sweep_interval_s < 30` (`"30"`, `"0"`, `"soon"` refused) |
| every move legal | each journey's transitions are legal per Appendix A |

## Traps

- Probe attempts not reported to the hook (sabotage `M21_probe_uncounted`). Count inside `resolve_execution`, once
  per attempt, so the count follows the module name the sabotage patches.
- Asking the resolver, or recomputing risk or mutation, after S11 (sabotage `M21_resolver_after_s11`).
- A docstring that quotes a URL or `localhost` trips the hosts scan. Write "the database URL from settings".
- Treating the performance baseline as a target. Record it; do not tune for it.

## Done when (★)

- [ ] Every case of `M21_journeys.py` passes; M01–M20 green; every M10–M21 sabotage caught.
- [ ] `python tools/owner_certify_s12.py --milestone M21` (full) exits 0, i.e. `owner_certify_s12.py` N/N PASS.
- [ ] Milestone report sent, then **STOP** for the owner's final review.
- [ ] Owner work, never the agent's: the §20 certification report sign-off, the deferred register,
      `owner_verify_s12.ps1`, and the tag `s12-s15-certified`.
