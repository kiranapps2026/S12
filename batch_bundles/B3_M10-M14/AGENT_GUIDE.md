# B3 agent guide: M10–M14 (guard, idempotency and retry, the S12 loop, probe path, revalidation and cancellation)

Read `../README.md` first: precedence, the ten rules, the module map and the names the tests patch. This file
covers what is specific to B3. Each milestone has its own file in `milestones/`.

B3 builds the **execution core**. Everything in B4 and B5 plugs into the loop, the guard and the ledger built here.
Get the seams right: later batches only add fields with defaults. They never change what B3 fixes.

## Entry conditions (all must hold before the first B3 commit)

- [ ] `docs/gates/s12_milestones.json`: M0–M9 (including M8a) are `green` or `reviewed`.
- [ ] `python tools/owner_certify_s12.py --selftest` shows every row OK.
- [ ] `python tools/owner_certify_s12.py --milestone M9` exits 0 on the current head.
- [ ] `git diff origin/s12-work -- tests_golden docs/gates/*.sha256` is empty, and S12-FRZ passes.
- [ ] All B3 rulings are `ruled`: CONF-021 to CONF-035. No open CONF blocks B3.
- [ ] Red first: each B3 golden file fails on the current head for the right reason. The review records the expected
      red counts: M10 63/64, M11 45/46, M12 29/33, M13 13/13, M14 all. The cases that already pass are standing
      rules: no module-level mutable state, empty-schema invariants, the prototype `topological_order`, no task
      scheduling.

## What B3 builds on (M1–M9, already on `s12-work`)

| From | B3 calls it |
|---|---|
| M1 | migration 015 (`idempotency_ledger`, `step_reconciliations`, `execution_steps.dispatched_attempt`, …) |
| M2 | `fenced_write`, `FenceHolder`, repositories, the transition log |
| M3/M4 | `transitions.validate`, the enums in `contracts.execution_states`, `IllegalStateTransition` |
| M6 | S12 entry and admission (the run is RUNNING with an ownership row) |
| M7 | `PostgresLeaseManager.acquire / release` (B3 adds the `holder=` keyword) |
| M8/M8a | `admit_step`, `reject_outcome`, selection, eligibility, operation quota |
| M9 | `PostgresBudgetReserver` (B3 adds `reservation(tenant_id, reservation_id)`) |

## Order and targets

Work strictly M10 → M11 → M12 → M13 → M14.

| Milestone | Golden file (cases) | Sabotage | New modules | Changed modules (additive) | Target |
|---|---|---|---|---|---|
| [M10](milestones/M10_guard.md) | `M10_guard.py` (64) | 10 | `contracts/adapter_interface.py`, `s12_execute/reliability.py`, `adapters/runtime/reliability.py`, `adapters/runtime/mock_adapter.py` | `circuit_breaker.py` (+`allow`, `record_ignored`), `budget_reserver.py` (+`reservation`) | 64/64, 10/10 |
| [M11](milestones/M11_idempotency_retry.md) | `M11_idempotency_retry.py` (46) | 10 | `contracts/idempotency.py`, `adapters/postgres/idempotency.py`, `adapters/postgres/step_attempts.py`, `s12_execute/retry_policy.py`, `s12_execute/attempts.py` | none | 46/46, 10/10 |
| [M12](milestones/M12_loop.md) | `M12_loop.py` (33) | 8 | `016_execution_events.sql`, `adapters/postgres/execution_events.py`, `adapters/postgres/kernel_policy.py`, `s12_execute/dispatch.py` | `loop.py` (rewrite of the prototype), `execution.py` (`PostgresExecutionStore`), `leases.py` (+`holder=`), `eligibility.py` (+`binding_requirements`, `step_context`); port `tests_postgres/test_step_loop.py` and `test_chain_full_stack.py` (CONF-035) | 33/33, 8/8 |
| [M13](milestones/M13_probe.md) | `M13_probe.py` (13) | 4 | `adapters/postgres/reconciliation.py`, `s13_reconciliation/probe.py` | `loop.py` (+`step_timeout_s`, probe settings, `episodes`), `mock_adapter.py` (`timeout_not_executed` with `n`) | 13/13, 4/4 |
| [M14](milestones/M14_revocation_cancel.md) ★ | `M14_revocation_cancel.py` (28) | 7 | `adapters/postgres/cancellation.py` | `live_authorization.py` (rework of the prototype), `adapter_interface.py` (+`credential_valid`), `loop.py` / `attempts.py` (live check and cancellation) | 28/28, 7/7, then the owner's ★ review |

Batch target: **184/184 B3 cases, 39/39 sabotage caught**, M01–M09 still green (490), `pytest tests -q` green (836),
`tests_postgres` total reported in the log, S0–S11 certifier 19/19.

## Files B3 may create or change

```text
src/contracts/adapter_interface.py                 M10 new; M14 adds CredentialProvider.credential_valid
src/contracts/idempotency.py                       M11 new
src/engine/stages/s12_execute/reliability.py       M10 new (BudgetTracker, TimeoutManager, ReliabilityGuard)
src/engine/stages/s12_execute/retry_policy.py      M11 new
src/engine/stages/s12_execute/attempts.py          M11 new; M14 live check before each call
src/engine/stages/s12_execute/dispatch.py          M12 new
src/engine/stages/s12_execute/loop.py              M12 rewrite of the prototype (CONF-011); M13, M14 additive
src/engine/stages/s12_execute/eligibility.py       M12 additive
src/engine/stages/s13_reconciliation/probe.py      M13 new
src/adapters/runtime/circuit_breaker.py            M10 (prototype file)
src/adapters/runtime/reliability.py                M10 new
src/adapters/runtime/mock_adapter.py               M10 new; M13 additive
src/adapters/postgres/budget_reserver.py           M10 add reservation() (prototype file)
src/adapters/postgres/idempotency.py               M11 new
src/adapters/postgres/step_attempts.py             M11 new
src/adapters/postgres/execution.py                 M12 PostgresExecutionStore (prototype file)
src/adapters/postgres/execution_events.py          M12 new
src/adapters/postgres/kernel_policy.py             M12 new
src/adapters/postgres/migrations/016_execution_events.sql   M12 new (never edit 001–015)
src/adapters/postgres/leases.py                    M12 add holder= to acquire
src/adapters/postgres/reconciliation.py            M13 new
src/adapters/postgres/cancellation.py              M14 new
src/adapters/postgres/live_authorization.py        M14 rework (prototype file)
tests_postgres/test_step_loop.py, test_chain_full_stack.py   M12 port only (CONF-035): same scenarios, never weaker
tests_agent/**                                     any
```

## Do not touch in B3

- `src/engine/stages/s12_execute/guard.py` (prototype). The new guard is `ReliabilityGuard` in `reliability.py`.
  `guard.py` may stay, but must not call `.probe(` (M13 scan).
- `src/contracts/step_execution.py` is **frozen**. `AdapterResult`, `FencedOut`, `Revoked`, `StepAdapter` are used
  as they are (CONF-021, CONF-031). `Revoked` carries only `reason`; the failing check's name goes to the log.
- `src/engine/stages/s12_execute/admission_control.py` and `settings.py`. B3 calls them. The reference copies have
  **older docstrings** than `s12-work`: `s12-work` carries CONF-032 (gate 8 is a DELAY) and DEF-005
  (`admission_exhausted`). Keep `s12-work`'s text. `settings.py`'s `recovery_sweep_interval_s` belongs to M19.
- The S8 handler. `live_authorization.py` reuses `engine.stages.s8_safety_gate.checks` (the check library, C23),
  never the handler.
- Anything owned by B4/B5 that the merged reference loop imports (`contracts/verification.py`, `contracts/metrics.py`,
  `fault_injection.py`, …). Build them in their own milestones.

## Conflict avoidance (B3-specific)

| Risk | Rule |
|---|---|
| Fixing a test instead of the code | Never. A golden case you think is wrong → STOP (§19.1). The last attempt at M11 deleted five cases; that is exactly what the pins catch |
| RLS bypass for a cross-tenant conflict | `store` uses `INSERT … ON CONFLICT (idempotency_key) DO NOTHING`. When nothing was inserted, a row **the tenant cannot see** is an `IdempotencyConflict`. No raw connection, no `row_security = off`, no reset of `app.current_tenant` |
| Breaker knows error classes | It doesn't. The guard decides: `ok` → `record_success`, `client_error` → `record_ignored`, everything else → `record_failure`; refused before the adapter → `record_ignored` |
| Mock counting globally | `MockAdapter` programs are **per `kernel_op_id`**; `n` counts calls of that operation. The side-effect ledger is per idempotency key |
| `ProbeOutcome` mangled to strings | The guard returns the `ProbeOutcome` enum (a `StrEnum`); never `.name`, never upper-case strings |
| Loop takes over a run | Only recovery (M19) takes ownership. The in-line loop passes `holder=` to `acquire`, which raises `FencedOut` when ownership moved (CONF-033) |
| Two places schedule tasks | Only `dispatch.py` may use `create_task` / `ensure_future` / `TaskGroup` (M12 scan) |
| Runtime types in the loop | The loop never names a runtime type (M08a RD-9). It builds `SelectionContext` through `eligibility` |
| Module-level mutable state | None in S12 code (M10 §21 S3 scan): no module-level `list` / `dict` / `set` you mutate, no class attributes patched at import |
| Exception text in logs | Log `type(exc).__name__` and record attributes (`attempt_id`, `kernel_op_id`), never `str(exc)` (M10 leak case; later M18) |

## Milestone end (each of M10–M14)

1. `python tools/owner_certify_s12.py --milestone Mxx` (full run): every row PASS.
2. `git diff --name-only <milestone start>..HEAD` lists only the files above (plus `tests_agent/**` and log appends).
3. Append `MILESTONE Mxx REACHED at <commit>` to `docs/gates/s12_autopilot_log.md`, push `origin s12-work`, and send
   the report. M10–M13 are ⚙: continue. **M14 is ★:** STOP and wait for "continue per S12 AUTOPILOT". The owner
   reviews the milestone summary and a sample of transition logs before M15 (plan §4: "the riskiest point").

## STOP conditions (B3 examples)

- A fix would need `contracts/step_execution.py`, the S8 handler, or another frozen file.
- `tests_postgres` prototype tests cannot be ported without weakening a scenario (CONF-035 forbids it).
- The same check still fails after 3 iterations aimed at it, or the PASS count drops and one more iteration does not
  restore it.
- Record the STOP as `STOP-nnn` in `S12_STOPS.md` before reporting (format in `S12_AUTOPILOT.md`).
