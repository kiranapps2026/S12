# Phase 1: Ground truth

Part of the [S12 truth model](README.md). It feeds phase 2 and draft sections §1, §3 and §12 of the final document.

## Purpose

Extract, with citations, everything the later phases treat as given: the legal transitions and their reasons, the
schema constraints that bound the evidence, the status of every relevant ruling and defect, and an index of the golden
cases and sabotage patches. Phase 1 interprets nothing. It lists facts and where each one is written.

## Entry conditions

- The repository is checked out at a recorded commit (note it in every output file header).
- No milestone card, review, improvement guide or reference implementation has been read for this work yet. See
  "Contamination rule" below.

## Contamination rule (resolves a contradiction in v1/v2)

The brief listed the milestone cards, the B4/B5 reviews and the reference implementation as phase 1 sources, and in
the same text said that reading a milestone card before the rows are frozen spoils the enumeration. Both cannot hold.
In phase 1:

| Source | Phase 1 use | Read in full in |
|---|---|---|
| Gate (`docs/implementation/S12_S15_EXECUTION_GATE.md`) | Read in full for the sections below | 1 |
| Schema (migrations) | Read in full | 1 |
| Records (`docs/gates/S12_RECORDS.md`, `S12_DEFECTS.md`, `S12_STOPS.md`) | Status and one-line effect only | 1 |
| `docs/gates/S12_RULING_PACK.md` | Both sides of each open CONF (needed for phase 6) | 1 |
| Golden files and sabotage patches | **Names only** (the index); not case bodies | 3 |
| Golden module docstrings | Interface names only (modules, functions), for the writer table | 3 (behaviour) |
| Milestone cards (`S12_S15_IMPLEMENTATION_PLAN.md:277-361`) | Not opened | 3 |
| `S12_B4_REVIEW.md`, `S12_B5_REVIEW.md`, `batch_bundles/IMPROVEMENT_GUIDE_B3-B5.md` | Not opened | 3, 4 |
| Reference code in `batch_bundles/B*/src/` | Not opened | 3, last |

## Precedence (never inverts)

Gate Appendix A > gate rulings (C, D) > gate sections > ruled CONF rows > repaired specification documents > pinned
golden cases > golden drafts > milestone cards > guides > reference code. This is the order of plan §2 as recorded at
the top of `S12_RECORDS.md`, extended downward. A conflict between the gate and a golden case becomes a proposed
`CONF-nnn` row; it is never resolved inside the truth model.

## Inputs, with locations

All gate line numbers are for `S12_S15_EXECUTION_GATE.md` at `638c519`.

| Input | Location |
|---|---|
| Appendix A: run, step, reservation, lease, dead letter, episode | A.1 `:2343`, A.2 `:2359`, A.3 `:2389`, A.4 `:2402`, A.6 `:2420`, A.7 `:2435` |
| Out of scope: A.5 worker (S12 only reads it), A.8 confirmation (S12 entry), A.9 breaker (M10) | `:2415`, `:2453`, `:2457` |
| Normative loop sequence | §8 `:1564` |
| Probe and reconciliation | §9 `:1648` |
| Consolidation, dead letter, response | §10 `:1675`, §11 `:1696`, §12 `:1722` |
| Recovery decision rule | §13 `:1736-1790` |
| Fault points (ten) | §15.2 `:1851-1870` |
| Invariants I1–I18 | §17 `:2071-2095` |
| Rulings that shape evidence | C6 `:358`, C13 `:468`, C14 `:480`, C16 `:501`, C17 `:520`, C18 `:547`, C19 `:597`, C21 `:664`, C27 `:904`, C35 `:1146`, D4 `:1404`, D5 `:1421` |
| Schema: steps, runs, plans, ownership, transition log | `src/adapters/postgres/migrations/009_execution_admission.sql` (`:10`, `:36`, `:77`, `:88`, `:99`) |
| Schema: reservations | `006_budget_reservations.sql:9`; live-reservation unique index `010_step_loop.sql` (last statement) |
| Schema: dispatch marker, terminal reasons, immutability trigger | `010_step_loop.sql:5-25` |
| Schema: leases, episodes, dead letters, ledger, checkpoints, transition-log machines | `015_s12_schema.sql` |
| Schema: drafted, not on `s12-work` | `batch_bundles/B5_M19-M21/src/adapters/postgres/migrations/016_execution_events.sql`, `017_recovery_candidates.sql` |
| Implemented transition tables (built in M3/M4, golden B1 pinned) | `src/engine/stages/s12_execute/transitions.py` |
| Invariant checker (active subset) | `tests_golden/fixtures/invariants.py` |
| Open records today | CONF-005, 042–047; STOP-002, 004, 005; DEF-002, 003, 004 |

## Procedure

1. **Edges.** For each in-scope machine, list every Appendix A row as `(machine, from, to, reasons, guard,
   produced)`. `produced = no` for edges the gate marks "not produced" (`running → cancelled`, `running → partial`,
   `unknown → *`). Record creation rows (`none → initial`, reason `created` or `opened`) as edges too. Reuse
   `tools/doc_consistency.py` `appendix_edges()` to parse the tables, then add reasons and guards by hand from the
   cells. Cross-check the result against `transitions.py`; any difference becomes a proposed CONF row.
2. **Prose rules that change edges.** Extract the guards stated outside the tables. At least these:
   - I-3: `pending → running` and `reserved → locked` in one transaction (A.2 `:2365`).
   - "Retries are not transitions" (A.2 `:2386-2387`).
   - An exhausted episode keeps `pending_probe`, gets `closed_at` and outcome EXHAUSTED, logged as an event
     (A.7 `:2446-2448`).
   - Ledger-hit and no-dispatch-marker episodes open and close in one transaction (A.7 `:2450-2451`).
   - C35: the marker commits before the call; a new reservation is created only for a retry after NOT_EXECUTED.
   - C14: a LOCKED reservation is resolved only by the probe outcome.
   - D4: an unresolved UNKNOWN and the human layer give DEAD_LETTER with the budget LOCKED.
3. **Schema bounds.** For each evidence table, list CHECK value sets, NOT NULL columns, unique and partial-unique
   indexes, foreign keys and triggers. Each later becomes a pruning rule of basis `schema`.
4. **Ruling status.** One row per CONF, DEF and STOP that names M11–M19 or the evidence tables: ID, status, one-line
   effect, and the edge or dimension it touches. Include CONF-040 (ruled), CONF-028 and CONF-029 (ruled, cite as
   settled), and proposed CONF-048 (from the ruling pack, not yet recorded).
5. **Case index (names only).** For M11, M12, M13, M14, M15, M16, M17 and M19, list every `test_*` function and every
   sabotage patch file. Today there are 25 cases in M11, 13 in M13, 29 in M15, 15 in M16, 27 in M17 and 25 in M19
   (before parametrisation), plus 27 sabotage patches across those milestones. Record pin status per file (all B3–B5
   files are unpinned drafts today).
6. **Vocabulary (§12 draft).** For each enumerated type, list the values and the gate line or schema CHECK that
   defines them: step and run states; reservation, lease, dead letter and episode statuses; episode outcomes
   (`015`: 7 values); `retry_mode`; `resolution_outcome`; dead-letter `error_type` and `origin`; step terminal
   reasons (`010`: 14 values); ProbeOutcome (§9: 4); ErrorClass and its retryable subset (gate C35/C37); Verdict.
   Where a type exists only in the reference code, give the gate text that implies it and mark the value list
   `proposed`.
7. **Writer table (§3 draft, from the gate only).** For each piece of evidence: the §8 step that writes it, whether
   the gate says it goes through `fenced_write()`, and what it must precede (for example, the marker precedes the
   call). Module names are added in phase 3.
8. **Glossary.** Fix one definition each for: attempt (`execution_steps.attempt`; a retry increments it), episode
   (one `step_reconciliations` row), in flight (a step in running, timeout, unknown or pending_probe; §13 step 3),
   evidence (a durable row or event a later reader can query), marker (`dispatched_attempt`), holder (the
   runtime and fence token a write is made under), fence token (from `fence_token_seq`, C25), usable lease
   (`active` and `expires_at > now()`), lapsed lease (`active` and `expires_at <= now()`).

## Outputs (`docs/truth_model/work/`)

| File | Format |
|---|---|
| `P1_EDGES.csv` | `machine,from,to,reasons,guard,produced,gate_ref,transitions_py_agrees` |
| `P1_PROSE_RULES.md` | One numbered rule per entry, quote plus `file:line` |
| `P1_SCHEMA.md` | Per table: constraint, kind (check, unique, fk, trigger), statement, `file:line` |
| `P1_RULINGS.csv` | `id,kind,milestone,status,effect,touches,source_line` |
| `P1_CASES.csv` | `milestone,file,test_or_patch,kind,pinned` |
| `P1_VOCABULARY.md` | Section §12 draft |
| `P1_WRITERS.md` | Section §3 draft |
| `P1_GLOSSARY.md` | Glossary |

Every file starts with the commit it was extracted at.

## Exit criteria

- Every Appendix A row of A.1–A.4, A.6 and A.7 appears in `P1_EDGES.csv`; the row count per machine equals the table
  row count in the gate, recorded in the file header.
- Every edge is either in agreement with `transitions.py` or has a proposed CONF entry.
- Every open record listed above, plus CONF-028, 029, 040 and 048, has a row in `P1_RULINGS.csv`.
- Every golden file and sabotage patch of the eight milestones is in `P1_CASES.csv`.
- No milestone card, review, guide or reference file was opened (state this in the output header).

## Can it split?

No. One reader extracts everything, so phase 2 starts from one consistent reading.

## Traps

- Schema CHECK lists are wider than Appendix A. `unknown` and `partial` pass the step CHECK, and `pending` passes
  the lease CHECK. "Allowed by the schema" does not mean "reachable".
- `state_transitions.entity_type` uses machine names (`run`, `step`, `reservation`, `lease`, `dead_letter`,
  `episode`, `confirmation`; CONF-013). Use them in every output so phase 5a can join on them.
- The ledger has no `step_id` or `execution_id`. It joins to a step only through the key
  `request_id || ':' || plan_step_id` (C9, CONF-024) and `tenant_id`.
