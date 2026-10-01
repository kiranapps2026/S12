# S12 truth model: brief and phase index

Owner: @Kiran. Brief dated 2026-10-01; this corrected version and the phase documents were written 2026-10-01 against
`s12-work` at `638c519`. This file replaces `batch_bundles/Handoff brief — S12 truth model document.md` (v1) and
the later upload (v2). The corrections are listed at the end, each with its source. Review pass 2 (same day, at
`c505af0`) found missed issues and inconsistencies in these documents themselves; see [REVIEW_LOG.md](REVIEW_LOG.md).

## What is being built

One document that answers a single question for the whole S12–S15 execution path: **given what is persisted, what
verdict about an attempt is justified?**

M13, M15 and M19 each ask that question at a different time: live after a timeout, live after a result exists, and
cold after a crash. They share one store (`step_reconciliations`), one episode state machine (gate Appendix A.7,
validated through `transitions.validate("episode", …)`) and one set of budget disposal rules (A.3). Three separate
documents would duplicate the rules and hide the contradictions between them. One matrix generates all three views.
Cells that come out empty, or filled twice with different answers, mark where the next production defect is.

In scope: M11 produces the evidence (the dispatch marker and the idempotency ledger), M12 orders the writes, M13 and
M15 interpret evidence live, M19 interprets it cold, and M16 and M17 consume the verdicts (consolidation, dead letters
and the LOCKED reservations they hold). M14 supplies two run-level inputs: live authorization and cancellation.

The safety claim the matrix has to prove: **an action is never silently repeated, and money is never settled for an
action whose outcome is unknown.** The codebase does not state this claim in one place, and nothing proves it. Each
matrix row is a case the claim must survive. A row where it fails is either a defect or an exception that nobody has
written down.

Two facts already strain the claim, and the document must face them rather than discover them late. A LOCKED
reservation is not "settled", but it counts against the tenant's budget exactly like a committed one (I1). Today
nothing in production releases it (C-11). And by design (C32), every mutation on an adapter without `observe()` ends
in that state even when it succeeded (C-16).

## Phases (one scheme; v2 carried three)

| Phase | Document | Output | Needs | Can it split? |
|---|---|---|---|---|
| 1 Ground truth | [PHASE_1_GROUND_TRUTH.md](PHASE_1_GROUND_TRUTH.md) | Edge table, ruling status, case index, vocabulary | Repository only | No |
| 2 Enumerate and prune | [PHASE_2_ENUMERATE_AND_PRUNE.md](PHASE_2_ENUMERATE_AND_PRUNE.md) | Frozen row list (TM-nnn), impossible set (IS-nnn), run context (RC-nnn), run-outcome rules (RO-nnn) | Phase 1 | No: one minting authority |
| 3 Map and classify | [PHASE_3_MAP_AND_CLASSIFY.md](PHASE_3_MAP_AND_CLASSIFY.md) | Each row mapped and classified, per milestone | Frozen rows | Yes: one worker per milestone column |
| 4 Validate | [PHASE_4_VALIDATE.md](PHASE_4_VALIDATE.md) | Findings register (TF-nnn), three derived views | All of phase 3 | No |
| 5a Operationalise | [PHASE_5A_OPERATIONALISE.md](PHASE_5A_OPERATIONALISE.md) | Evidence view, reverse-index SQL, zero-row predicates | Validated rows, PostgreSQL 16 | Runs beside 5b |
| 5b Consequences | [PHASE_5B_CONSEQUENCES.md](PHASE_5B_CONSEQUENCES.md) | Terminal reason table, latency and LOCKED-time figures | Validated rows | Runs beside 5a |
| 6 Owner rulings | [PHASE_6_OWNER_RULINGS.md](PHASE_6_OWNER_RULINGS.md) | Corrected owner queue (CONF, STOP, DEF), branch write-ups, rulings applied | Phase 3 onward | Owner only |
| 7 Freeze | [PHASE_7_FREEZE.md](PHASE_7_FREEZE.md) | `S12_TRUTH_MODEL.md`: provenance, decision log, shelf life | Everything | No |

Phases 1–4 and 5b need no database. Phase 5a needs one (a local PostgreSQL 16 cluster is enough). Phase 6 needs the
owner. The gate between phases 2 and 3 matters most: if anyone reads a milestone card before the rows are frozen, the
enumeration copies what the implementation already does, and the exercise finds nothing new.

Phase outputs go in `docs/truth_model/work/`. The assembled document is `docs/truth_model/S12_TRUTH_MODEL.md`
(phase 7).

## State at 2026-10-01

| Item | State |
|---|---|
| Phase documents 1–7 | Written (this folder) |
| `sql/step_evidence.sql` | Draft of the phase 5a evidence view (dimensions D1–D9); `sql/smoke_test.sql` (twelve evidence shapes) passes on PostgreSQL 16 with migrations 001–015 plus drafted 016–017, and each of five view mutations or a mutated expectation makes it fail |
| Candidate observations C-1 … C-16 | Logged in phase 2, for phase 4 to judge. The most severe: C-9 (durable evidence recovery ignores), C-10 (a recorded FAIL re-run after a crash), C-11 and C-16 (LOCKED money nothing releases) |
| Owner queue | Corrected in phase 6, including the STOP and DEF rows and the errors in a circulated analysis |
| [REVIEW_LOG.md](REVIEW_LOG.md) | What each review pass found and where it was fixed |
| Phase outputs (`work/`) | None yet. Phase 1 is next |

## Coordination rules

- Row IDs are minted once, in phase 2, and never by a phase 3 worker. Rules for impossible states (IS-nnn) are
  minted the same way.
- Findings go into the register (`work/FINDINGS.md`), never as edits to a row. A row is changed only by the
  worker that owns its milestone column.
- Anything found mid-phase that would change the row list is logged in `work/ROW_CHANGE_LOG.md` and not applied. It
  waits for a deliberate re-run of phase 2, because a row list that moves under phase 3 invalidates work already done.
- The owner is interrupted once, at phase 6, and gets both branches of each open ruling already written.
- This work never edits `src/`, `tests_golden/`, `docs/implementation/`, pins or owner tools. A gate-versus-golden
  conflict is proposed as a `CONF-nnn` row; the session with write rights appends it (`S12_TEST_AUTHOR_BRIEF.md`).

## Standing conventions (from phase 1)

- **Row IDs**: `TM-001` onward, stable, never renumbered or reused. A retired row keeps its ID with status
  `retired` and the reason. Examples in briefs use `EX-n`, never `TM-n`, so they cannot collide with minted IDs.
- **Status tag per claim**, never blank:

  | Tag | Meaning |
  |---|---|
  | `ruled` | The gate text or a ruled CONF states it |
  | `pinned-by-golden` | A golden case asserts it, and the owner has pinned that file |
  | `golden-draft` | A golden case asserts it, but the file is still unpinned (B2–B5 today) |
  | `proposed` | Derived by this work; no source states it |
  | `unknown` | No source decides it. These are the most valuable rows |

- **Severity per finding**: *silent* (wrong verdict, nothing visibly fails, money moves wrongly), *loud* (the run
  stalls or dead-letters), *cosmetic* (reason string or wording). Silent ranks above loud.
- **Provenance per row**: gate section and `file:line`, ruling ID, golden case (`file::test`), sabotage patch.
  A row without a citation is an opinion.
- **Traceability**: row → golden case → sabotage patch. A sabotage patch is a written-down wrong implementation;
  read it as a derived requirement.
- **Module owner per cell**, from the golden interface docstrings (phase 3 lists them).
- **Two-reader test**: each row must serve an engineer deciding what to build and an operator deciding what to do
  at 2 a.m.
- **Decision log**: dated, with supersession, in the style of `S12_RECORDS.md`.
- **Glossary**: episode, attempt, in flight, evidence, marker, holder, fence token, lapsed lease (phase 1 fixes the
  definitions).

## Principles every row must satisfy

These are the reasoning spine. Phase 4 tests every row against all eight. Most defects found by the B4 and B5
reviews broke one of these, not a milestone rule.

1. **Write order gives evidence its meaning.** The dispatch marker is informative only because it commits before
   the call can happen. In general, every piece of evidence must be durable before the event it describes becomes
   possible. A row where this order is broken merges two distinguishable states into one.
2. **Monotonic certainty.** Evidence only accumulates; a verdict never becomes less certain as evidence arrives.
   (Phase 4 must address the one built-in exception: an expired ledger row counts as none.)
3. **Re-entrant interpretation.** Reading the same evidence twice gives the same verdict. A second recovery sweep
   must not reach a different conclusion or open a second episode.
4. **Fail closed, and name the cost.** Where evidence is missing, the system holds the budget LOCKED and
   dead-letters rather than guessing. Every fail-closed row states what that costs.
5. **No verdict without evidence.** INCONCLUSIVE describes knowledge, not the world: never success, never failure,
   never a plain error.
6. **Budget conservation.** Every reservation reaches exactly one terminal disposition, and that disposition depends
   on the verdict alone, not on the code path that produced it.
7. **One writer per fact.** Evidence is written under the fence; a runtime that has been taken over adds none.
   A row that two runtimes could write is a fencing bug, not a matrix row.
8. **Irreversibility dominates.** For an IRREVERSIBLE or non-idempotent operation, uncertainty never resolves to a
   retry. This overrides every other rule.

## The finished document's sections, and the phase that produces each

| § | Section | Produced in |
|---|---|---|
| 1 | Scope and precedence: what it decides (nothing) versus what it proposes | 1 (drafted), 7 (final) |
| 2 | The evidence ladder, in order of authority | 2 |
| 3 | Who writes which evidence, and when | 1, checked in 3 |
| 4 | **Master matrix**: evidence → verdict, episode, step transition, budget, dead letter | 2 (skeleton), 3 (filled) |
| 5–7 | Derived views: live probe (M13), live verification (M15), cold path (M19, ten fault points) | 4 |
| 8 | Invariants the matrix must satisfy (I6 first, then I11, I12) | 2, 4 |
| 9 | Disposal: what each row costs the tenant (M16, M17) | 3, 5b |
| 10 | **Reverse index**: symptom → candidate rows → the query that tells them apart | 5a |
| 11 | **Impossible states**: one zero-row SQL predicate each | 2 (set), 5a (SQL) |
| 12 | Vocabulary | 1 |
| 13 | Terminal reason → operator action → budget → customer message | 5b |
| 14 | Cost and latency per path | 5b |
| 15 | Contradictions and open rulings | 4, 6 |
| 16 | Provenance appendix | 7 |

## Corrections to the v1/v2 brief

Each fact was checked against the repository at `638c519`. Gate means `docs/implementation/S12_S15_EXECUTION_GATE.md`.

| # | Brief said | Correct | Source |
|---|---|---|---|
| 1 | Example TM-003: no-marker case, "none opened" | An EXECUTION episode **is** opened and closed in one transaction: outcome NOT_EXECUTED, evidence `no_dispatch_marker`, closed `confirmed_failure (not_executed)`. Step `running → pending_probe (recovery) → pending (no_dispatch_marker)`; budget `locked → released (no_dispatch_marker)`; the retry takes a new reservation. If no retry is allowed (IRREVERSIBLE, non-idempotent D, ceiling reached), the step goes on to `cancelled (not_executed_no_retry)`. | Gate C35 `:1164-1170`, `:1187-1189`; §13 `:1772-1778`; A.2 `:2378`; A.3 `:2398`; A.7 `:2450-2451` |
| 2 | Step states include `reconciling` | `reconciling` is a run state and an episode state, never a step state | Schema `009:48-50`; A.1, A.7 |
| 3 | Step `unknown` is an ordinary state | `unknown` is allowed by the CHECK but never written in this phase (C24). Recovery must still handle it: proposed CONF-048 | A.2 `:2375`; `S12_RULING_PACK.md:431-443` |
| 4 | Dispatch marker: absent / present | `dispatched_attempt` has three readings: NULL or `< attempt` (provably not dispatched), `= attempt` (may have been called). `> attempt` cannot occur. | Gate C35 `:1160-1169`; M11 `mark_dispatched` |
| 5 | Ledger value "claimed not stored" | Does not exist. The ledger row is one `INSERT … ON CONFLICT DO NOTHING` with the result; values are none / expired (counts as none) / success / failure | `015_s12_schema.sql` (idempotency_ledger); M11 docstring |
| 6 | Lease: held by me, lapsed, expired, released, none | A.4 has `active`, `expired`, `released`. "Lapsed" means `active` with `expires_at <= now()`; "held by me" depends on who is reading, so it is not a stored value. Ownership is the separate `execution_ownership` row. | A.4 `:2402-2413`; `009:88` |
| 7 | Invariants I1–I16 | The gate defines **I1–I18**. I17 and I18 (quota, eligibility) prune nothing here, but cite the full set. | Gate §17 `:2071-2095` |
| 8 | Six open rulings: 005, **040**, 043, 044, 046, 047 | CONF-040 is ruled. The open set is **005, 042, 043, 044, 045, 046, 047**, plus proposed **CONF-048**. All but 048 have both sides and a recommendation in `S12_RULING_PACK.md`. | `S12_RECORDS.md`; ruling pack `:21-36` |
| 9 | Vocabulary counts (ErrorClass 8, ProbeOutcome 4, Verdict 3) | The counts are right, but they come from the unreviewed reference in `batch_bundles/`. Take them from the gate and the golden docstrings instead. | Precedence rule of phase 1 |
| 10 | Reverse index over `execution_events` | That table exists only in drafted migration `016` (`batch_bundles/B5_M19-M21`). `s12-work` has 001–015, and M10 onward is not implemented. Every query records the schema it was checked against. | `src/adapters/postgres/migrations/` |
| 11 | Three phase schemes (P0–P8, a six-phase plan, phases 1–7) | One scheme: phases 1–7, with 5a and 5b in parallel | This file |
| 12 | Status tag `pinned-by-golden` for golden cases | B2–B5 golden files are unpinned drafts; tag them `golden-draft` until the owner pins | `docs/gates/s12_autopilot_log.md` |
| 13 | Phase 1 reads the milestone cards, reviews and reference code, and the cards must not be read before the rows are frozen | Phase 1 reads the gate, schema and records, and indexes golden cases by name only. Cards, reviews, guides and reference code are read in phase 3 | Phase 1, "Contamination rule" |
| 14 | Phases 5a/5b: "every predicate runs and returns zero" | Zero on an empty database proves nothing. Each predicate must return 0 on a clean fixture and exactly 1 on its own planted violation | Phase 5a |
| 15 | The ruling write-ups are produced in phase 6 | `docs/gates/S12_RULING_PACK.md` already has both sides and a recommendation for each open CONF. Phase 6 adds only the matrix consequences | Phase 6 |
| 16 | Evidence dimensions: reservation, step, marker, ledger, layers, episode, lease, digest, authorization, operation | Execution events are evidence too (`ProviderReturned`, `idempotency_hit`, …): each is its own fenced write, and recovery ignores them (D9, C-9). Cancellation requests and run status are run context (R4, R5) | Pass 2, P2-1, P2-5 |
| 17 | Evidence ladder: ledger → marker → layer events → open episode → reservation → nothing | That list ranks answers to different questions against each other. Phase 2 uses one ladder per question (dispatched? provider acted? effect verified? money settled?) | Pass 2, P2-10 |
| 18 | "The default `probe()` returns INCONCLUSIVE, so every real uncertainty dead-letters" | Also: the default `observe()` returns UNKNOWN, so every **certain** success of a mutation dead-letters too (C32 `:1046-1050`) | Pass 2, C-16 |
| 19 | "Budget held, nothing happened": wording and an SLA | No production path releases the money at all (IMP-M17-2). An SLA needs an operator entry point first | Pass 2, P2-3 |
