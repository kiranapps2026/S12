# Phase 3: Map and classify

Part of the [S12 truth model](README.md). Input: the frozen rows of phase 2. It fills §4 (master matrix) and §9
(disposal), and checks the §3 writer table.

## Purpose

For every frozen row, record what each milestone does with that evidence, with a citation. Then classify the row by
how well its behaviour is specified and tested. Empty cells and cells two milestones fill differently are the
findings this work exists to produce.

## Entry conditions

- `work/tm_ids.json` is committed, and its commit message records the freeze.
- From here on, milestone cards, golden case bodies, sabotage patches, reviews and guides may be read.

## Columns, owners and sources

One worker owns one milestone column. A worker writes only its own column file.

| Column | Milestone role | Sources, in reading order | Module owners (from the golden interface docstrings) |
|---|---|---|---|
| M11 | Produces the marker and the ledger | `tests_golden/s12/M11_idempotency_retry.py` docstring and cases; 10 `M11_*` sabotage patches; plan card `S12_S15_IMPLEMENTATION_PLAN.md:277` | `contracts.idempotency`; `adapters.postgres.idempotency`; `adapters.postgres.step_attempts`; `engine.stages.s12_execute.retry_policy`; `engine.stages.s12_execute.attempts` |
| M12 | Orders the writes | `M12_loop.py`; `M12_*` patches; card `:287`; DEF-002, DEF-004 | `engine.stages.s12_execute.loop`; `adapters.postgres.execution`; `adapters.postgres.execution_events` |
| M13 | Interprets live, after a timeout | `M13_probe.py`; 4 `M13_*` patches; card `:296`; CONF-028, 029 | `engine.stages.s13_reconciliation.probe`; `adapters.postgres.reconciliation` |
| M14 | Supplies the live-authorization input | `M14_revocation_cancel.py`; card `:304` | `adapters.postgres.live_authorization`; `adapters.postgres.cancellation` |
| M15 | Interprets live, after a result | `M15_verification.py`; 3 `M15_*` patches; card `:320`; CONF-036, 040, 041, 005 | `engine.stages.s13_reconciliation.verification`; `contracts.verification` |
| M16 | Consumes: consolidation | `M16_consolidation.py`; 3 `M16_*` patches; card `:329`; CONF-034, 037 | `engine.stages.s13_reconciliation.consolidation`; `adapters.postgres.consolidation` |
| M17 | Consumes: dead letters, settlement | `M17_dead_letter.py`; 3 `M17_*` patches; card `:338`; CONF-038 | `adapters.postgres.dead_letters`; `engine.stages.s14_dead_letter.retry`, `.rollback` |
| M19 | Interprets cold, after a crash | `M19_recovery.py`; 4 `M19_*` patches; card `:354`; CONF-033, 042–047 | `engine.stages.s12_execute.loop.recover_execution`; `engine.stages.s12_execute.recovery`; `engine.stages.s12_execute.fault_injection`; migration `017` |

After those, read `docs/gates/S12_B4_REVIEW.md` and `S12_B5_REVIEW.md` ("Defects caught", "Defects the new cases
found"), then `batch_bundles/IMPROVEMENT_GUIDE_B3-B5.md` §4.2–4.4. Read the reference code under
`batch_bundles/B*/src/` last, and only to settle an ambiguity in the golden text. Never cite it as a source of
behaviour.

## Cell format

For each row a milestone reaches, the cell holds:

| Field | Content |
|---|---|
| verdict | executed / not executed / failed / unknown, or `n/a` |
| episode | kind, transitions with reasons, close status, outcome, evidence key |
| step | `from → to (reason)`, one entry per transition, in order |
| budget | `from → to (reason)`, plus "new reservation" where C35 allows one |
| dead letter | `error_type` / `retry_mode`, or none |
| events | execution events in order (`step_attempt`, `ProviderCalled`, `idempotency_hit`, `verification_layer`, `episode_closed`, `dead_letter_alert`, …) |
| status | `ruled`, `pinned-by-golden`, `golden-draft`, `proposed`, `unknown` |
| provenance | gate `file:line`; ruling IDs; golden `file::test`; card line |
| guarded by | sabotage patch file(s), or none |
| module | the module that writes the decisive transition |

A milestone that never reaches a row writes `n/a: <why>` (for example, "M15: no result and no confirmed probe").
Blank cells are not allowed.

## Format reference (corrected examples; IDs are `EX-n` so they cannot collide with minted rows)

| ID | Evidence | Verdict | Episode | Step | Budget | Dead letter |
|---|---|---|---|---|---|---|
| EX-1 | running; reservation locked; marker `null` or `below`; no ledger row; no open episode; retry allowed | not executed, no probe | EXECUTION opened and closed in one transaction: `none → pending_probe (opened) → reconciling (attempt_started) → confirmed_failure (not_executed)`, outcome NOT_EXECUTED, evidence `no_dispatch_marker` | `running → pending_probe (recovery) → pending (no_dispatch_marker)`, then retried as the next attempt | `locked → released (no_dispatch_marker)`; a new reservation for the retry | none |
| EX-1b | as EX-1, but no retry allowed (IRREVERSIBLE, `retry_safety = never`, non-idempotent D, or ceiling reached) | not executed | as EX-1 | as EX-1, then `pending → cancelled (not_executed_no_retry)` | `locked → released (no_dispatch_marker)` | none |
| EX-2 | marker `current`; no ledger row; probe EXECUTED_SUCCESS; required layers PASS (after a probe: provider_state, semantic and human as required; never schema or deterministic, CONF-040) | executed | EXECUTION `reconciling → confirmed_success (executed_success)` | `pending_probe → completed (probe_executed_success)` | `locked → committed (step_completed)` | none |
| EX-3 | marker `current`; no ledger row; probe INCONCLUSIVE three times | unknown | EXECUTION stays `pending_probe`, gets `closed_at` and outcome EXHAUSTED; event `episode_closed` | `pending_probe → dead_letter (probe_exhausted)`; remaining PENDING steps `cancelled (run_dead_lettered)` | stays `locked` (D4) | `unknown_unresolved` / PROBE, carrying the episode and the reservation |

Sources: EX-1 C35 `:1164-1170`, §13 `:1773-1778`, A.2 `:2378`, A.3 `:2398`, A.7 `:2450`; EX-2 §9, CONF-040; EX-3
§9, A.7 `:2446-2448`, D4, M17 docstring.

## Worked trace per row

Each reachable row gets one trace: the sequence of `state_transitions` rows (`entity_type, from_state, to_state,
reason`) and execution events that produce it, starting from the last state every reader agrees on. The trace is
what an operator compares with the database during an incident. Write it once per row, from the column whose
milestone first produces the row (usually M12 or M13 for live rows, M19 for cold rows).

## Classification (one per row, after all columns are filled)

| Class | Rule | Is it a finding? |
|---|---|---|
| covered | Every column that reaches the row agrees, and at least one golden case asserts the outcome | No |
| divergent | Two columns disagree, or a card disagrees with its golden case | Yes: goes to phase 4 |
| untested | The gate or a card states the outcome, but no golden case asserts it | Yes |
| uncovered | No source states the outcome | Yes. The most valuable class |

Rows in the conditional set (phase 2) are classified the same way, plus the question: does any source say the two
writes share a transaction?

## Procedure

1. Each worker copies the frozen row list and fills its column in `work/P3_<column>.csv`. It never adds, removes or
   merges rows. A row that looks wrong goes to `work/ROW_CHANGE_LOG.md`.
2. Each worker also lists the golden cases and sabotage patches of its milestone that match **no** row. A case
   without a row means the enumeration missed a dimension; log it in the row-change log.
3. A merge step (one person or a script) joins the column files into `work/P3_MATRIX.csv` and writes the class of
   each row.
4. Fill the disposal columns (§9) from M16 and M17: run outcome per §10, settlement of the reservation, and whether
   the run can still consolidate.
5. Check the §3 writer table from phase 1 against the module owners above, and record any evidence with two writing
   modules (principle 7 input for phase 4).

## Outputs (`docs/truth_model/work/`)

| File | Content |
|---|---|
| `P3_<column>.csv` | One file per column: `tm_id` plus the cell fields above |
| `P3_MATRIX.csv` | All columns joined, plus `class` and `trace` |
| `P3_TRACES.md` | One trace per reachable row |
| `P3_UNMATCHED_CASES.csv` | Golden cases and sabotage patches with no row |
| `ROW_CHANGE_LOG.md` | Logged, unapplied proposals to change the row list |

## Exit criteria

- Every row has a value or `n/a: <why>` in every column. The merge script fails on a blank.
- Every non-`n/a` cell has a provenance entry.
- Every row has a class.
- Every golden case and sabotage patch of the eight milestones maps to at least one row, or is listed in
  `P3_UNMATCHED_CASES.csv`.

## Can it split?

Yes, one worker per column, because the rows are frozen. The merge and the classification are done once, by one
person, after every column is complete.

## Traps

- A golden draft that passes on the reference proves only that the reference agrees with the draft. Tag such cells
  `golden-draft`, not `pinned-by-golden`.
- M13 and M15 both write episodes. When a probe confirmed the execution and verification then fails, the EXECUTION
  episode closes `confirmed_failure (verified_fail)`, outcome VERIFIED_FAIL (M13 docstring). Do not assume an
  EXECUTION episode only ever closes with an EXECUTED_* outcome.
- M19 resumes a retried step "at the attempt after its last dispatched one". The attempt number is evidence too:
  record it in the trace.
