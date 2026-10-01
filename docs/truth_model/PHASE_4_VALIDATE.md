# Phase 4: Validate

Part of the [S12 truth model](README.md). Input: `work/P3_MATRIX.csv`. It produces the findings register, the derived
views §5–§7 and the invariants section §8, and drafts §15 (contradictions). This is the first handoff to the
owner.

Revised in review pass 2 (`REVIEW_LOG.md` P2-1, P2-2, P2-3, P2-16): event write order, the FAIL re-run, LOCKED
with no production release, the settled reservation reuse, and two probe regimes in view C.

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
| 1 | Write order | List every pair (evidence, event it describes) with the transaction order the gate states: marker → call (C35); `ProviderCalled` / `ProviderReturned` events → ledger row (each its own transaction, C-9); `step_attempt` event → `ProviderCalled` (I16); layer events → step commit (§8 step 8; IMP-M15-3); `pending → running` with `reserved → locked` (I-3; DEF-004); episode opened → probe call; ledger row → step transition; episode closed EXHAUSTED → step `dead_letter` (C-2); dead letter created → step `dead_letter` (seed l2) | The order is unstated, and a crash between the two writes produces a row whose verdict differs from either side, or durable evidence that no reader consults (judgement) |
| 2 | Monotonic certainty | Per question (the four ladders of phase 2), order rows by evidence. For each pair of rows that differ by one added piece of evidence, compare verdicts on the scale definitive (executed, not executed, failed, verified PASS or FAIL) > unknown | Adding evidence, or time passing, moves a verdict from definitive to unknown or flips it. Known tensions: an expired ledger row (C-3); a recorded FAIL re-run after a crash (C-10); a durable `ProviderReturned` that recovery ignores (C-9) |
| 3 | Re-entrant interpretation | For each row, apply the §13 rule to the state it produces, then once more. Also crash at each write inside recovery itself (M19 pins four double crashes) | The second pass makes any new write: a second episode, a transition, a probe, a token reused. Also checks that R1 can be factored out (phase 2) |
| 4 | Fail closed, with cost | Every row ending with the reservation LOCKED or a dead letter states what is held, for how long, and who releases it (§9 disposal column) | The cost column is empty, or "who releases it" has no production answer (C-11: no entry point retries or resolves a dead letter, and LOCKED counts against the pool under I1) |
| 5 | No verdict without evidence | Every row with a definitive verdict cites the item that proves it: unexpired ledger row, probe EXECUTED_* or NOT_EXECUTED, marker `null`/`below`, layer FAIL or all PASS | A definitive verdict rests only on INCONCLUSIVE, UNKNOWN or a timeout |
| 6 | Budget conservation | Build the table verdict → reservation disposition across all rows, including the run-level RO rules (refund, RESERVED released at consolidation) | One verdict maps to two dispositions, a reservation path has no terminal disposition reachable in production (C-11), or a step state and its reservation disagree between two transactions (C-4, C-5) |
| 7 | One writer per fact | Every write in a cell goes through `fenced_write()` under a holder | Evidence is written without a fence. Check in particular M17 `resolve` / `start_retry` (they take `tenant_id`, not a holder) and `create_rollback` ("no fence, the run is terminal") |
| 8 | Irreversibility dominates | Filter rows with D8 = no retry (IRREVERSIBLE, `retry_safety = never`, non-idempotent D) and verdict unknown or not executed. Settle C-8 first: it decides which D rows are in the filter | Any such row leads to a new attempt (`pending` followed by `running`) |

## Derived views (§5–§7)

Each view is a filter over the matrix, rendered as a decision table and compared line by line with the milestone
card and golden docstring. A disagreement is a finding.

| View | Filter | Compare with |
|---|---|---|
| A, live probe (§5) | Rows the M13 column reaches: an attempt returned uncertain (`timeout` or `dispatched_without_record`) | Card `S12_S15_IMPLEMENTATION_PLAN.md:296`; `M13_probe.py` docstring |
| B, live verification (§6) | Rows with D5 ≠ none or a VERIFICATION episode | Card `:320`; `M15_verification.py` docstring |
| C, cold path (§7) | Rows the M19 column reaches, indexed by fault point below | Card `:354`; `M19_recovery.py` docstring; §13 |

### View C seed: the ten fault points (§15.2) and the evidence each leaves

The evidence column comes from the M19 golden draft's fault-injection interface (`M19_recovery.py:18-24`). The
golden column is what `POINT_CASES` (`M19_recovery.py:152-163`) pins with a mock probe that answers. The default
column is what the same evidence gives in production, where the default probe returns INCONCLUSIVE (C32). Phase 4
maps each point to its TM rows and checks the §13 branch for both.

| Fault point | Evidence left behind | §13 branch | Golden (answering probe) | Production default |
|---|---|---|---|---|
| `after_lease_acquire` | Lease held, nothing reserved | No in-flight step: continue from the first PENDING step | `fresh` | Same |
| `after_budget_reserve` | Reservation RESERVED, step PENDING | No in-flight step; `reserve()` returns the existing live reservation (`budget_reserver.py:82-84`) | `reuses_reservation` | Same |
| `after_budget_lock` | Step RUNNING, reservation LOCKED, marker `null` (first attempt) or `below` (a retry) | No ledger row, no marker: NOT_EXECUTED without a probe (EX-1); attempt number reused | `not_executed_without_probe` | Same (no probe involved) |
| `after_dispatch_marker_before_call` | Marker `current`, no ledger row, no `ProviderCalled` | Probe | `probe_then_retry`: NOT_EXECUTED, retry as `att-0-2` | Dead letter after three INCONCLUSIVE probes, budget LOCKED, for a call that never happened |
| `after_adapter_call_before_ledger` | Marker `current`, no ledger row, the provider has the side effect; `ProviderCalled` / `ProviderReturned` present or not, depending on where the point sits relative to the event writes (unpinned) | Probe; the events are not read (C-9) | `crash_a`: EXECUTED_SUCCESS, completed | Dead letter, budget LOCKED, although a `ProviderReturned ok` may be on record |
| `after_ledger_before_verification` | Ledger row, no layer verdicts | Success: VERIFICATION episode, no probe. Failure: `failed (ledger_hit_failure)` | `crash_b`: `completed (verification_passed)` | Depends on the layers: provider_state uses `observe()`, which defaults to UNKNOWN, so a W/D step dead-letters (`verification_exhausted`) |
| `during_verification` | Ledger row, some layer verdicts | VERIFICATION episode re-runs only the layers not yet PASS (C19) | `crash_b` | As above |
| `after_verification_before_step_commit` | Ledger row, every required layer recorded | All PASS: episode opened and closed LEDGER_HIT, `completed (ledger_hit_success)`. **A FAIL recorded: a VERIFICATION episode re-runs the failed layer (C-10)** | `crash_c_all_passed` only; the FAIL case is uncovered | FAIL can flip to PASS or to UNKNOWN → dead letter |
| `after_commit_before_checkpoint` | Step COMPLETED, lease still held | Nothing to resolve. Checkpoint is a hint (CONF-044) | `already_completed` | Same |
| `during_probe` | EXECUTION episode `reconciling` | Continue the episode; the lost attempt is recorded `inconclusive` (M19 docstring). Check that it counts toward the three | `probe_continued` | Dead letter |

Cross each point with the run context the M19 golden also exercises: revocation found in recovery (`REVOKED_IN_RECOVERY`,
`:546`), a tampered plan with and without a step in flight (`:311`, `:512`), a cancellation requested while crashed,
and a RECONCILING run (CONF-047).

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
