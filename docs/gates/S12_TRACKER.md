# S12-S15 tracker

Generated 2026-09-30 by `tools/s12_tracker.py report`. Do not edit by hand: change status with `python tools/s12_tracker.py set Mxx <status>`. The owner certifier output (S12_PROGRESS.md), when it exists, overrides this file.

**Summary:** 23 not_started, 0 red_confirmed, 0 in_progress, 0 green, 0 reviewed of 23 milestones. Open: 2 conflicts, 0 stops, 0 defects.

**Next:** M0 Preflight (model: sonnet, complexity: low, status: not_started)

| Milestone | Batch | Status | Complexity | Model | Review | Prototype state | Commits | Open CONF | Open STOP | Open DEF |
|---|---|---|---|---|---|---|---|---|---|---|
| M0 Preflight | B0 | not_started | low | sonnet | ★ | not done | 0 | 2 | 0 | 0 |
| M1 Schema: migrations | B1 | not_started | medium-high | sonnet | ★ | partial | 0 | 0 | 0 | 0 |
| M2 fenced_write(), repositories, transition log | B1 | not_started | medium | sonnet |  | partial | 0 | 0 | 0 | 0 |
| M3 State machines I: run, step, budget | B1 | not_started | medium | sonnet |  | prototype | 0 | 0 | 0 | 0 |
| M4 State machines II: lease, worker, dead letter, episode, confirmation, breaker | B1 | not_started | medium | sonnet |  | not done | 0 | 0 | 0 | 0 |
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
| M15 Verification and VERIFICATION episodes | B4 | not_started | high | sonnet |  | port only | 0 | 0 | 0 | 0 |
| M16 Consolidation | B4 | not_started | medium | sonnet |  | minimal | 0 | 0 | 0 | 0 |
| M17 Dead letter and explicit rollback | B4 | not_started | high | opus |  | not done | 0 | 0 | 0 | 0 |
| M18 S15 response and redaction | B4 | not_started | medium | sonnet |  | not done | 0 | 0 | 0 | 0 |
| M19 Crash recovery and fault injection | B5 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M20 Multi-process: subprocess kills, two runtimes, tenant isolation | B5 | not_started | very high | opus |  | not done | 0 | 0 | 0 | 0 |
| M21 Journeys, architecture suite, seams, certification | B5 | not_started | high | sonnet | ★ | not done | 0 | 0 | 0 | 0 |

## Rule violations

None.

## Open records

- CONF-001 (M0, open): `DATA_CONTRACTS.md` line 131: python code fence (section 2 ExecutionContext) has no closing fence before line 215; text between renders as code. Tool key `C7:unclosed-fence-DATA_CONTRACTS.md-131`
- CONF-002 (M0, open): `DATA_CONTRACTS.md` line 1240: python code fence (19.1 StepState) has no closing fence before line 1256 (heading 19.2). Key `C7:unclosed-fence-DATA_CONTRACTS.md-1240`
