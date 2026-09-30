# S12-S15 tracker

Generated 2026-09-30 by `tools/s12_tracker.py report`. Do not edit by hand: change status with `python tools/s12_tracker.py set Mxx <status>`. The owner certifier output (S12_PROGRESS.md), when it exists, overrides this file.

**Summary:** 21 not_started, 1 red_confirmed, 0 in_progress, 0 green, 1 reviewed of 23 milestones. Open: 4 conflicts, 0 stops, 0 defects.

**Next:** M1 Schema: migrations (model: sonnet, complexity: medium-high, status: red_confirmed)

| Milestone | Batch | Status | Complexity | Model | Review | Prototype state | Commits | Open CONF | Open STOP | Open DEF |
|---|---|---|---|---|---|---|---|---|---|---|
| M0 Preflight | B0 | reviewed | low | sonnet | ★ | not done | 2 | 0 | 0 | 0 |
| M1 Schema: migrations | B1 | red_confirmed | medium-high | sonnet | ★ | partial | 0 | 0 | 0 | 0 |
| M2 fenced_write(), repositories, transition log | B1 | not_started | medium | sonnet |  | partial | 0 | 1 | 0 | 0 |
| M3 State machines I: run, step, budget | B1 | not_started | medium | sonnet |  | prototype | 0 | 0 | 0 | 0 |
| M4 State machines II: lease, worker, dead letter, episode, confirmation, breaker | B1 | not_started | medium | sonnet |  | not done | 0 | 2 | 0 | 0 |
| M5 PostgreSQL confirmation store | B2 | not_started | medium | sonnet |  | built (S0-S11) | 0 | 0 | 0 | 0 |
| M6 S12 entry and durable admission | B2 | not_started | medium-high | sonnet |  | prototype | 0 | 0 | 0 | 0 |
| M7 Leases, fencing, ownership | B2 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M8 Admission controller and worker selection | B2 | not_started | medium | sonnet |  | not done | 0 | 0 | 0 | 0 |
| M8a Worker management: entry checks, eligibility, operation quota | B2 | not_started | high | sonnet | ★ | quota built | 0 | 0 | 0 | 0 |
| M9 BudgetReserver | B2 | not_started | high | opus |  | prototype | 0 | 0 | 0 | 0 |
| M10 Mock adapter, adapter interface, reliability guard | B3 | not_started | high | opus |  | guard built | 0 | 0 | 0 | 0 |
| M11 Idempotency ledger and retry | B3 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M12 S12 loop, dependents, terminal reasons | B3 | not_started | high | sonnet |  | prototype | 0 | 0 | 0 | 0 |
| M13 Probe path and EXECUTION episodes | B3 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M14 Live revalidation and cancellation | B3 | not_started | very high | opus | ★ | partial | 0 | 0 | 0 | 0 |
| M15 Verification and VERIFICATION episodes | B4 | not_started | high | sonnet |  | port only | 0 | 1 | 0 | 0 |
| M16 Consolidation | B4 | not_started | medium | sonnet |  | minimal | 0 | 0 | 0 | 0 |
| M17 Dead letter and explicit rollback | B4 | not_started | high | opus |  | not done | 0 | 0 | 0 | 0 |
| M18 S15 response and redaction | B4 | not_started | medium | sonnet |  | not done | 0 | 0 | 0 | 0 |
| M19 Crash recovery and fault injection | B5 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M20 Multi-process: subprocess kills, two runtimes, tenant isolation | B5 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M21 Journeys, architecture suite, seams, certification | B5 | not_started | high | sonnet | ★ | not done | 0 | 0 | 0 | 0 |

## Rule violations

None.

## Open records

- CONF-003 (M5, ruled): Gate §2 item 10 / C20: store receives `tenant_id`, `execution_id` "as keyword-only arguments". Code: `src/adapters/postgres/confirmations.py:20` and `src/engine/stages/s10_confirmation/store.py:25,43` take them positional-or-keyword; S10 passes them positionally (`s10_confirmation/handler.py:79`). Both required and validated; tested (`tests/stages/test_s10_confirmation.py:58`)
- CONF-004 (M8a, ruled): Gate §2 item 17 names the S0 handler and `tests/stages/test_s0_entry.py`. Code: check at `src/engine/control_plane/pipeline_state_runner.py:182-186` (S0.1) and `:215`; tests in `tests/stages/test_s0_activation.py:49-108` (19 cases)
- CONF-005 (M15, open): Gate D6 (`S12_S15_EXECUTION_GATE.md:1442`) and suite 9 layer selection by autonomy: no `AutonomyLevel` source exists in code (no match in src/, tests/, tests_postgres/). D6 says STOP and report
- CONF-006 (M3, ruled): `src/contracts/state_validators.py:41` StateTransitionValidator (DATA_CONTRACTS §26) contradicts gate Appendix A: run machine `:72-92` uses budget states; step machine `:94-118` uses SUCCESS/TIME_OUT/PROBE_FAILED and allows UNKNOWN→FAILED, RUNNING→UNKNOWN. Loaded at `src/main.py:25,48`. Prototype `s12_execute/transitions.py` matches A.1/A.2 exactly
- CONF-007 (M1, ruled): Gate §7.3 (C39): `operation_quotas` has `worker_id` in `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, worker_id, resource_type, period_start)` and `CHECK (worker_id IS NULL)`. Code `009_execution_admission.sql:113-129`: no `worker_id` column, unique key without it. M8a golden "rejects a non-NULL worker_id" cannot hold
- CONF-008 (M6, ruled): Gate D1 / C32 assume metadata read "at the pinned versions". Code: `kernel_ops` has no version column; `registry_versions` is a singleton (`001_s0_s11_schema.sql:104`); `registry.py:125-132` returns None when versions moved, so every earlier-certified plan is denied after a bump
- CONF-009 (M1, ruled): Plan v3 §3 puts golden tests in `tests\golden\s12\Mxx_*.py`. The S0–S11 certifier OWN-13 runs `pytest tests` and must stay 19/19 every milestone (plan §4 exit), but a golden file is red until its milestone is built, so inside `tests\` it turns OWN-13 FAIL
- CONF-010 (M1, ruled): Plan §5.2: "a golden test that already passes is rejected". 30 of 89 M01 cases already pass because migrations 009/010 (inside the tag) built part of the M1 schema; they cannot be made red without editing tagged migrations (an M1 trap)
- CONF-011 (M2, open): Plan §4 exit "S0–S11 code unchanged since the tag", but the tag also holds the S12 prototype files (M0 item 3), which M2–M4 must rework (e.g. `adapters/postgres/execution.py` queries lack `tenant_id`; `s12_execute/transitions.py` uses bare literals). Frozen `src/bootstrap.py:16` imports the prototype `adapters/runtime/circuit_breaker.py`, and 8 files in `tests/` test prototype code (`test_s12_loop_units.py`, `test_s12_entry_checks.py`, `test_m2a_s12_readiness.py`, `test_m2a_chain.py`, `test_s8_safety_gate.py`, `fixtures/deps.py`, `steps/step_g_s8_matrix.py`, `steps/step_i_integration_journeys.py`)
- CONF-012 (M4, open): C24 "every transition carries a reason code", but Appendix A.5 (worker, STATE_TRANSITIONS §4) and A.8 (confirmation) list none
- CONF-013 (M4, open): C28 bare-literal rule vs the transition-log machine names of DATABASE.md (`run`, `step`, `dead_letter`, …): `dead_letter` is both a machine name and a run/step state value, so the lower-case literal cannot be forbidden
