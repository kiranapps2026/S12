# Phase 4: Validate

Part of the [S12 truth model](README.md). Input: `work/P3_MATRIX.csv`. It produces the findings register, the derived
views §5–§7 and the invariants section §8, and drafts §15 (contradictions). This is the first handoff to the
owner.

## Purpose

Test every row against the eight principles (README) and against every other milestone's view of the same evidence.
A row that breaks a principle is a finding even when a golden case passes it today. The findings decide whether the
M13, M15 and M19 golden drafts, or the gate, need to change before implementation resumes at M10.

## Entry conditions

- Phase 3 exit criteria met: no blank cell, every row classified.
- Every candidate (C-n) logged in phases 2 and 3 is in `work/FINDINGS.md`.

## The principle tests

Each test runs over all rows. Most can be scripted over `P3_MATRIX.csv`. The ones marked *judgement* need a reader.

| # | Principle | Test | Fails when |
|---|---|---|---|
| 1 | Write order | List every pair (evidence, event it describes) with the transaction order the gate states: marker → call (C35); layer events → step commit (§8 step 8); `pending → running` with `reserved → locked` (I-3); episode opened → probe call; ledger row → step transition; episode closed EXHAUSTED → step `dead_letter`; dead letter created → step `dead_letter` | The order is unstated, and a crash between the two writes produces a row whose verdict differs from either side (judgement) |
| 2 | Monotonic certainty | Order rows by the authority ladder (phase 2). For each pair of rows that differ by one added piece of evidence, compare verdicts on the scale definitive (executed, not executed, failed) > unknown | Adding evidence moves a verdict from definitive to unknown. Known tension: an expired ledger row (C-3) |
| 3 | Re-entrant interpretation | For each row, apply the §13 rule to the state it produces, then once more | The second pass makes any new write: a second episode, a transition, a probe. Also tests the R1/R2 factorisation of phase 2 |
| 4 | Fail closed, with cost | Every row ending with the reservation LOCKED or a dead letter states what is held, for how long, and who releases it (§9 disposal column) | The cost column is empty |
| 5 | No verdict without evidence | Every row with a definitive verdict cites the item that proves it: unexpired ledger row, probe EXECUTED_* or NOT_EXECUTED, marker `null`/`below`, layer FAIL or all PASS | A definitive verdict rests only on INCONCLUSIVE, UNKNOWN or a timeout |
| 6 | Budget conservation | Build the table verdict → reservation disposition across all rows | One verdict maps to two dispositions, or a reservation path has no terminal disposition |
| 7 | One writer per fact | Every write in a cell goes through `fenced_write()` under a holder | Evidence is written without a fence. Check in particular M17 `resolve` / `start_retry` (they take `tenant_id`, not a holder) and `create_rollback` ("no fence, the run is terminal") |
| 8 | Irreversibility dominates | Filter rows with D8 = no retry (IRREVERSIBLE, `retry_safety = never`, non-idempotent D) and verdict unknown or not executed | Any such row leads to a new attempt (`pending` followed by `running`) |

## Derived views (§5–§7)

Each view is a filter over the matrix, rendered as a decision table and compared line by line with the milestone
card and golden docstring. A disagreement is a finding.

| View | Filter | Compare with |
|---|---|---|
| A, live probe (§5) | Rows the M13 column reaches: an attempt returned uncertain (`timeout` or `dispatched_without_record`) | Card `S12_S15_IMPLEMENTATION_PLAN.md:296`; `M13_probe.py` docstring |
| B, live verification (§6) | Rows with D5 ≠ none or a VERIFICATION episode | Card `:320`; `M15_verification.py` docstring |
| C, cold path (§7) | Rows the M19 column reaches, indexed by fault point below | Card `:354`; `M19_recovery.py` docstring; §13 |

### View C seed: the ten fault points (§15.2) and the evidence each leaves

The evidence column comes from the M19 golden draft's fault-injection interface. Phase 4 maps each point to its
TM rows and checks the §13 branch.

| Fault point | Evidence left behind | §13 branch expected |
|---|---|---|
| `after_lease_acquire` | Lease held, nothing reserved | No in-flight step: continue from the first PENDING step |
| `after_budget_reserve` | Reservation RESERVED, step PENDING | No in-flight step. Check what releases or reuses the RESERVED row |
| `after_budget_lock` | Step RUNNING, reservation LOCKED, marker `null` (first attempt) or `below` (a retry) | No ledger row, no marker: NOT_EXECUTED without a probe (EX-1) |
| `after_dispatch_marker_before_call` | Marker `current`, no ledger row | Probe. **Indistinguishable from the next point by design** (C35: a marker without a call costs one unnecessary probe) |
| `after_adapter_call_before_ledger` | Marker `current`, no ledger row, the provider has the side effect | Probe. With the default probe (INCONCLUSIVE), dead letter after three attempts |
| `after_ledger_before_verification` | Ledger row, no layer verdicts | Success: VERIFICATION episode, no probe. Failure: `failed (ledger_hit_failure)` |
| `during_verification` | Ledger row, some layer verdicts | VERIFICATION episode re-runs only the layers not yet PASS (C19) |
| `after_verification_before_step_commit` | Ledger row, every required layer recorded | All PASS: episode opened and closed LEDGER_HIT, `completed (ledger_hit_success)`. Any FAIL: check which row (finding if none) |
| `after_commit_before_checkpoint` | Step COMPLETED, lease still held | Nothing to resolve. Checkpoint is a hint (CONF-044) |
| `during_probe` | EXECUTION episode `reconciling` | Continue the episode. The lost attempt is recorded `inconclusive` (M19 docstring); check that it counts toward the three |

## Findings register (`work/FINDINGS.md`)

One entry per finding, `TF-nnn`, minted here. Candidates from phases 2 and 3 become TF entries or are closed with a
reason.

| Field | Content |
|---|---|
| id | `TF-nnn` |
| rows | TM / RC / IS IDs affected |
| principle | 1–8, or `divergence`, `untested`, `uncovered` |
| severity | silent / loud / cosmetic |
| statement | One sentence: what is wrong |
| evidence | Gate, golden, card, `file:line` |
| disposition | Proposed route, see below |
| status | candidate, open, proposed-to-owner, accepted, rejected (with reason), superseded |
| date | Opened, and each status change |

Routing (the truth model decides nothing itself):

| Finding kind | Route |
|---|---|
| Gate text is ambiguous, or the gate contradicts a golden draft | Propose a `CONF-nnn` row (text only), for the session with write rights |
| A golden draft asserts the wrong outcome, or misses a row | Proposal to the test-author session (`S12_TEST_AUTHOR_BRIEF.md`); the draft changes before the owner pins it |
| Built code (M1–M9) breaks a row | Propose a `DEF-nnn` row (for example, DEF-004 already covers C-5) |
| Correct behaviour that customers will read as a fault | Phase 5b |
| A deliberate exception | Record it in the decision log with the owner's acceptance |

## Severity rubric

| Severity | Test | Example |
|---|---|---|
| silent | The verdict is wrong and nothing visible fails, or money settles wrongly | A reservation committed for an action whose outcome is unknown |
| loud | The run stalls, or it dead-letters when the evidence was sufficient to decide | C-1, a read dead-lettering after a crash |
| cosmetic | Reason string, event name or wording | A reason that Appendix A does not list (DEF-002 class) |

## Outputs (`docs/truth_model/work/`)

| File | Content |
|---|---|
| `FINDINGS.md` | The register |
| `P4_PRINCIPLES.csv` | `tm_id, p1..p8` (pass / fail TF-nnn / n/a) |
| `P4_VIEW_A.md`, `P4_VIEW_B.md`, `P4_VIEW_C.md` | §5–§7 drafts, with the comparison result per line |
| `P4_INVARIANTS.md` | §8 draft: each of I1–I18 with the rows and IS/IH rules that enforce it (I6, I11, I12 first) |
| `P4_HANDOFF.md` | For the owner: findings by severity, and for each of M13, M15 and M19 whether the golden draft must change before it is pinned |

## Exit criteria

- Every row has a pass, fail or `n/a` for each of the eight principles.
- Every divergent, untested or uncovered row from phase 3 has a TF entry or a recorded reason why it is not a finding.
- All three views are generated, and each line is marked agrees or TF-nnn.
- `P4_HANDOFF.md` is written.

## Can it split?

No. Contradictions show up only across milestones, so one reader has to hold all of them.
