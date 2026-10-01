# B4 agent guide: M15–M18 (verification, consolidation, dead letters, S15 response)

Read `../README.md` first: precedence, the ten rules, the module map and the names the tests patch. This file
covers what is specific to B4. Each milestone has its own file in `milestones/`.

## Entry conditions (all must hold before the first B4 commit)

- [ ] `docs/gates/s12_milestones.json`: M0–M14 are `green` or `reviewed`. M14 is ★: the owner's review of the
      execution loop must be done (plan §4 M14).
- [ ] `python tools/owner_certify_s12.py --selftest` shows every row OK.
- [ ] `python tools/owner_certify_s12.py --milestone M14` exits 0 on the current `s12-work` head.
- [ ] `git diff origin/s12-work -- tests_golden docs/gates/*.sha256` is empty, and S12-FRZ passes.
- [ ] CONF-005 has an owner ruling (it blocks M15's S12-REC row). If it is still `open`, build M15 but report the
      milestone as blocked on CONF-005, never as reached.
- [ ] Red first: each B4 golden file fails on the current head for the right reason (a missing module or symbol,
      not a fixture error). The B4 review records the expected red counts: M15 50/51, M16 30/31, M17 36/37,
      M18 16/16.

## What B4 builds on (must already exist from B3 / M10–M14)

| From | You will call it | If it is missing, B3 is not done: STOP |
|---|---|---|
| M10 | `ReliabilityGuard.call / probe / observe`, `BudgetTracker`, `MockAdapter` | do not write it inside a B4 milestone |
| M11 | `PostgresIdempotencyLedger`, retry policy, `attempts.py` | |
| M12 | `run_execution`, `LoopDeps`, `LoopSettings`, `execution_events` (migration 016), `dispatch.py` | |
| M13 | `s13_reconciliation/probe.py` `resolve_execution`, `PostgresEpisodes.open/close`, EXECUTION episodes | |
| M14 | `PostgresCancellation`, live revalidation, `LoopDeps.live`, the cancel path | |

## Order and targets

Work strictly M15 → M16 → M17 → M18. Each one depends on the one before it.

| Milestone | Golden file (cases) | Sabotage | New modules | Changed modules (additive) | Target |
|---|---|---|---|---|---|
| [M15](milestones/M15_verification.md) | `M15_verification.py` (51) | 3 | `contracts/verification.py`, `s13_reconciliation/verification.py` | `loop.py` (+`verification` dep, settings), `reconciliation.py` (close refuses NOT_EXECUTED for VERIFICATION), `mock_adapter.py` (`data["id"]`, `observe`, `observe_unknown`, `observations`) | 51/51, 3/3 caught, M01–M14 still green |
| [M16](milestones/M16_consolidation.md) | `M16_consolidation.py` (31) | 3 | `s13_reconciliation/consolidation.py`, `adapters/postgres/consolidation.py` | `execution_states.py` (+`ConsolidationOutcome`), `loop.py` (+`cancel_run`) | 31/31, 3/3, M01–M15 green |
| [M17](milestones/M17_dead_letter.md) | `M17_dead_letter.py` (37) | 3 | `adapters/postgres/dead_letters.py`, `s14_dead_letter/{__init__,retry,rollback}.py` | `reliability.py` (+`InverseBudget`), `loop.py` (+`dead_letters`) | 37/37, 3/3, M01–M16 green |
| [M18](milestones/M18_response.md) | `M18_response.py` (16) | 3 | `contracts/envelope.py`, `s15_final_state/response.py`, `adapters/postgres/run_summary.py` | `idempotency.py` (failure rows keep the class only, if not already) | 16/16, 3/3, M01–M17 green |

Batch target: **135/135 B4 cases, 12/12 sabotage caught**, every earlier golden file unchanged and green,
`pytest tests -q` green, S0–S11 certifier 19/19.

## Files B4 may create or change

Only these, plus a fix in an earlier S12 file (not frozen) when a golden case of the current milestone proves it is
needed. Record the reason in the commit message.

```text
src/contracts/verification.py                          M15  new
src/contracts/execution_states.py                      M16  add ConsolidationOutcome (StrEnum SUCCESS, PARTIAL, FAILURE)
src/contracts/envelope.py                              M18  new
src/engine/stages/s13_reconciliation/verification.py   M15  new
src/engine/stages/s13_reconciliation/consolidation.py  M16  new
src/engine/stages/s14_dead_letter/__init__.py          M17  new (empty)
src/engine/stages/s14_dead_letter/retry.py             M17  new
src/engine/stages/s14_dead_letter/rollback.py          M17  new
src/engine/stages/s15_final_state/response.py          M18  new
src/engine/stages/s12_execute/loop.py                  M15–M17  additive fields and paths
src/engine/stages/s12_execute/reliability.py           M17  add InverseBudget
src/adapters/postgres/reconciliation.py                M15  close() guard
src/adapters/postgres/execution.py                     M15  the loaded run carries its persisted verifiers (D1)
src/adapters/postgres/consolidation.py                 M16  new
src/adapters/postgres/dead_letters.py                  M17  new
src/adapters/postgres/budget_reserver.py               M17  add settle_dead_letter_reservation (A.3 dead_letter_* reasons)
src/adapters/postgres/run_summary.py                   M18  new
src/adapters/postgres/idempotency.py                   M18  only if failure bodies are still stored
src/adapters/runtime/mock_adapter.py                   M15  additive programme options
tests_agent/**                                         any  your own extra tests (never counted)
```

**No new migration in B4.** CONF-036 puts layer results in `execution_events` (`verification_layer` events), and
the dead-letter, quota and summary tables already exist (015). If you think a table or column is missing, STOP
(it would be a schema change outside every B4 card).

## Do not touch in B4

- The prototype handlers `s13_reconciliation/handler.py`, `s14_verification/handler.py`,
  `s15_final_state/handler.py`. The new code goes in new modules next to them, as listed above.
- `s12_execute/guard.py` (prototype). B4 verification uses `ReliabilityGuard.observe` in `reliability.py`.
- Any signature fixed by M10–M14. Everything B4 adds to `LoopDeps` defaults to `None`, so the earlier golden files
  build `LoopDeps` unchanged.
- S12 entry (`s12_entry/*`), admission and leases: B4 calls them and does not change them. The budget reserver gains
  only `settle_dead_letter_reservation` (M17). The one allowed exception is a bug a B4 case proves. Commit that fix
  on its own.

## Conflict avoidance (B4-specific)

| Risk | Rule |
|---|---|
| Two paths end a run | Every terminal run state after admission goes through `PostgresConsolidator.consolidate` or `.cancel` (M16). Once `cancel_run` is wired, the loop never moves a run row itself |
| Verification versus probe | A VERIFICATION episode never calls the probe or the adapter, and never closes NOT_EXECUTED. An EXECUTION episode never runs the layers. Two questions, two episode kinds (C19; sabotage `M15_verification_as_execution`) |
| A dead-letter record versus the DEAD_LETTER state | A record is evidence. Only unresolved uncertainty (episode EXHAUSTED, human layer) puts the step in DEAD_LETTER. A transient or data record leaves the step FAILED (§11) |
| A resolution moves state | Resolving or retrying a dead letter never changes the run or the step. It may settle only a LOCKED reservation (D4; sabotage `M17_resolution_moves_step`) |
| Leaking ids or bodies | S15 output carries plan positions, operation names, states and `trace_id`, never internal ids, exception text or provider bodies (M18) |
| Bare strings | New reasons and outcomes are enum members in `contracts.execution_states`. M04 scans for string values equal to state names |
| `ruff --fix` over directories | It rewrote frozen `admission.py` and `usage.py` once. Fix files one at a time |

## Milestone end (each of M15–M18)

1. `python tools/owner_certify_s12.py --milestone Mxx` (full run): every row PASS.
2. `git diff --name-only <milestone start>..HEAD` lists only the files above (and `tests_agent/**`, log appends).
3. Append `MILESTONE Mxx REACHED at <commit>` to `docs/gates/s12_autopilot_log.md`, push `origin s12-work`, and send
   the milestone report. None of M15–M18 is ★; continue with the next card unless a STOP condition holds.

## STOP conditions (B4 examples)

- CONF-005 still open at M15 end → the milestone is not reached; report it as blocked.
- A golden case contradicts the gate or a ruling (§19.1), e.g. if the §10 table and a case disagree.
- A fix needs a frozen file: e.g. `contracts/step_execution.py` (`AdapterResult`, `Revoked`) or the S0–S11
  confirmation store.
- The same check still fails after 3 iterations aimed at it, or the PASS count drops and one more iteration does not
  restore it.
- Record the STOP as `STOP-nnn` in `S12_STOPS.md` before reporting. Use the report format in `S12_AUTOPILOT.md`.
