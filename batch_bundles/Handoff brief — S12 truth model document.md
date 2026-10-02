# Handoff brief — S12 truth model document

Oct 1, 2026 · @Kiran

## What to build

One document that answers a single question for the whole S12–S15 execution path: given what is persisted, what verdict about an attempt is justified?

M13, M15 and M19 each ask that question at a different moment — live after a timeout, live after a result exists, and cold after a crash. They share one store (`step_reconciliations`), one episode state machine validated through `transitions.validate("episode", …)`, and one budget disposal rule set. Writing them as three documents duplicates the rules and hides the contradictions between them. One matrix generates all three views, and the cells that come out empty or double-filled are where the next production defect already lives.

M11 is in scope as the evidence producer: without the dispatch marker ordering, none of the questions are answerable. M16 and M17 are in scope as the consumers, because the budget column only means something if dead-letter kinds and their LOCKED reservations sit in the same table.

The deeper reason to write it: the system makes one safety claim to its customers — an action is never silently repeated, and money is never settled for an action whose outcome is unknown. Nothing in the codebase states that claim in one place or proves it. The matrix is the proof obligation. Every row is a case the claim must survive, and any row where it does not is either a defect or a deliberate exception that nobody has written down.

## How the work is phased

&#91;embedded content: nine phases · one owner-blocked lane\]

Phases 0 to 5 need no cloud credits, no running system and no owner. The rulings pass is the only input you cannot produce yourself, and it runs beside P3 to P5 rather than ahead of them.

| Phase | Output | Needs | Who | Effort |
| --- | --- | --- | --- | --- |
| P0 Load sources | Reading notes, precedence fixed | — | Research session | Low |
| P1 Enumerate | Evidence dimensions and the raw state space | P0 | Research session | Low |
| P2 Prune | Matrix skeleton, plus the impossible-state set | P1, schema CHECKs, I1–I16 | Research session | Medium |
| P3 Map | Rows filled from M11, M13, M15, M16, M17, M19 | P2 | Research session | High |
| P4 Audit | Findings classified silent / loud / cosmetic | P3 and the principles | Research session | High |
| P5 Assemble | Derived views, reverse-index SQL, impossible-state predicates | P4 | Research session | Medium |
| P6 Rulings | Both branches written for the six open CONFs | P3 (parallel) | Owner only | Low, but blocking |
| P7 Business layer | Terminal reason → operator action → customer message | P5, P6 | Research session, owner signs off | Low |
| P8 Freeze | Scope, assumptions, invalidation triggers, gates | All | Research session | Low |

Handoff points are P4 and P8. P4 hands the owner a findings list with severities, which is what decides whether M13, M15 or M19 need rework before implementation resumes. P8 hands the next implementation session a document it can work from without re-deriving anything.

## How the work is phased

&#91;embedded content: phase plan · 6 phases, 5 gates\]

P0 to P2 cost nothing but thinking time and can run entirely away from the repo. P3 onward needs the codebase open. The gate between P2 and P3 is the one that decides whether the document is worth anything: once a milestone card is read, the enumeration is contaminated by what the implementation already does.

## Sources, in reading order

Precedence never inverts: the gate and the pinned documents outrank the guides, and the reference implementation is an example that passes, not a specification.

| # | Source | Take from it |
| --- | --- | --- |
| 1 | Gate §9, §11, §13, §15.2, Appendix A | The legal transitions and reasons. Every cell's reason must be an Appendix A edge |
| 2 | `S12_RECORDS.md` | CONF rulings, their status, their proposal text |
| 3 | Golden `M13_probe.py`, `M15_verification.py`, `M19_recovery.py` | The module docstrings are the interface contract; the cases are the acceptance criteria |
| 4 | `tests_golden/sabotage/` for M13, M15, M19 | Each patch names a wrong implementation that must fail. These are the error-prone cells |
| 5 | Milestone cards M11, M13, M15, M16, M17, M19 | The tables already written. Use as cross-check, not as the structure |
| 6 | `S12_B4_REVIEW.md`, `S12_B5_REVIEW.md` | The defects a second pass found in the reference. Every one of them is a matrix row that was wrong |
| 7 | `IMPROVEMENT_GUIDE_B3-B5.md` | Places a correct-looking implementation still fails silently |
| 8 | Reference `probe.py`, `verification.py`, `recovery.py`, `loop.py` | Last. Unreviewed, and it will anchor you if read first |

A conflict between 1 and 3 is a `CONF-nnn` row, not something to resolve in this document.

## Method

Enumerate first, map second. This is the one instruction that decides whether the document is worth the effort.

1. **Enumerate the evidence dimensions** independently of any milestone. Each is a column of the state space, and each is something the database can actually tell you after a crash:

| Dimension | Values | Who writes it |
| --- | --- | --- |
| Reservation status | none, reserved, locked, committed, released | M9, M12 |
| Step state | pending, running, timeout, unknown, pending\_probe, reconciling, + terminals | M12 |
| Dispatch marker | absent, present (per attempt) | M11 |
| Idempotency ledger | no row, claimed not stored, success row, failure row + class | M11 |
| Layer verdicts recorded | none, partial, all required | M15 |
| Episode | none, EXECUTION open/closed + outcome, VERIFICATION open/closed + outcome | M13, M15 |
| Lease | held by me, lapsed, expired, released, none | M7, M19 |
| Plan digest | match, mismatch | M19 |
| Live authorization | valid, revoked | M14 |
| Operation attributes | mutation class, retry\_safety, IRREVERSIBLE, truth\_state | registry |

2. **Prune to the reachable states.** The raw cross-product is large and mostly impossible. Cut it with the schema CHECKs, the foreign keys, Appendix A's legal edges, and invariants I1–I16. What survives the pruning is the matrix; what the pruning removes becomes §11, the impossible-state predicates. Both halves are deliverables — do not throw the pruned set away.
3. **Map existing behaviour onto the surviving rows.** Only now open the milestone cards.
4. **Classify every row**: covered and consistent; covered differently by two milestones; covered with no golden case; not covered at all. The last three categories are the findings.
5. **Test each row against the principles below.** A row that contradicts one of them is a defect even if a golden case currently passes it.

If you instead transcribe the three milestones into one table, you inherit their blind spots and the exercise produces nothing new. The empty and double-filled cells are the entire deliverable.

One worked trace per row — the actual sequence of transitions and events — turns an abstract row into something usable during an incident. Abstract rows are useless at 2 a.m.

## Principles every cell must satisfy

These are the document's reasoning spine. State them once and test every row against them; most defects the B4 and B5 reviews found were violations of one of these, not of a milestone rule.

1. **Write-order is what makes evidence meaningful.** The dispatch marker informs you only because it commits *before* the call can happen. Generalise it: every piece of evidence must be durable before the event it describes becomes possible. Any row where this ordering is violated collapses two distinguishable states into one.
2. **Monotonic certainty.** Evidence only accumulates. A verdict must never become less certain as more evidence arrives. Read the rows in evidence order and check this holds.
3. **Re-entrant interpretation.** The same evidence read twice yields the same verdict. Recovery sweeps repeat, and a second sweep must not reach a different conclusion or open a second episode.
4. **Fail closed, and name what closing costs.** Where evidence is missing the system holds the budget LOCKED and dead-letters rather than guessing. That is correct and it is expensive. Every fail-closed cell should state the cost it incurs, so the owner can see the aggregate.
5. **No verdict without evidence.** INCONCLUSIVE is a statement about knowledge, not about the world. Never success, never failure, never a plain error.
6. **Budget conservation.** Every reservation reaches exactly one terminal disposition, and that disposition is a function of the verdict alone, never of which code path produced it.
7. **One writer per fact.** Evidence is written under the fence. A taken-over runtime adds none. A row two runtimes could write is a fencing bug, not a matrix row.
8. **Irreversibility dominates.** For an IRREVERSIBLE or non-idempotent operation, uncertainty must never resolve to a retry, whatever the rest of the row says. This overrides every other rule.

A worked row looks like this. Three examples, to fix the format before the enumeration starts:

| ID | Evidence | Verdict | Episode | Step (reason) | Budget | Dead letter |
| --- | --- | --- | --- | --- | --- | --- |
| TM-003 | running, reservation LOCKED, no dispatch marker | NOT\_EXECUTED, no probe | none opened | retry as attempt n+1 | released, new one taken | none |
| TM-011 | marker present, no ledger row, probe EXECUTED\_SUCCESS | executed | EXECUTION closed confirmed\_success | completed (probe\_executed\_success) | committed | none |
| TM-024 | marker present, no ledger row, probe INCONCLUSIVE x3 | unknown | EXECUTION closed EXHAUSTED | dead\_letter (probe\_exhausted) | stays LOCKED | PROBE |

TM-003 exists only because of principle 1. TM-024 generates most of the business consequences below.

## Conventions

These make the document citable rather than merely readable. Apply them from the first row.

- **Row IDs.** Every matrix row gets a stable ID, TM-001 onward. Defects, commits and future rulings then cite a row instead of re-describing it, the way CONF-nnn works today. Never renumber.
- **Status tag per claim**, never blank: `ruled`, `pinned-by-golden`, `proposed`, `unknown`. The `unknown` rows are the most valuable content in the file.
- **Severity per finding**, so the reader can triage: *silent* (wrong verdict, nothing visibly fails, money moves wrongly), *loud* (run stalls or dead-letters), *cosmetic* (reason string or wording). Silent findings rank above loud ones — a stalled run is visible, a wrongly committed reservation is not.
- **Provenance per row**: gate section, ruling ID, golden case name, and `file:line`. A row with no citation is an opinion, and in six months nobody can tell which rows were which.
- **Test traceability**: row → golden case → sabotage patch that guards it. The sabotage patches are a ready-made list of wrong implementations; read them as derived requirements, not as tests. Rows with no covering case are a finding in their own right.
- **Module ownership per cell**, so a wrong verdict maps to a file rather than to a discussion.
- **The two-reader test.** Each row must be usable by two different readers: an engineer deciding what to implement, and an operator deciding what to do at 2 a.m. If a row serves only the first, it is incomplete.
- **Decision log**, dated, with supersession, in the style of `S12_RECORDS.md`.
- **Glossary** for the words used loosely in conversation and precisely in code: episode, attempt, in flight, evidence, marker, holder, fence token.

## Sections the document must contain

1. Scope and precedence — what it decides (nothing) versus proposes
2. The evidence ladder — every durable trace, in order of authority: ledger row → dispatch marker → `verification_layer` events → open episode → reservation state → nothing
3. Who writes which evidence, and when (M11 produces, M12 orders, M13/M15 interpret live, M19 interprets cold)
4. **The master matrix** — evidence state → justified verdict, episode kind and close status, step transition and reason, budget disposition, dead-letter kind
5. Derived view A: the live probe path (M13)
6. Derived view B: the live verification path (M15)
7. Derived view C: the cold path (M19), its ten fault points mapped back onto §4
8. Invariants the matrix must satisfy — I6 above all, plus I11 and I12
9. Disposal — what each row costs the tenant (M16 consolidation, M17 dead letters)
10. **The reverse index** — symptom → candidate evidence states → the SQL that distinguishes them, against `execution_steps`, `step_reconciliations`, `idempotency_ledger`, `execution_events`, `budget_reservations`, `dead_letters`. This is what makes the document the thing you reach for during an incident
11. **Impossible states** — every combination the matrix forbids, each as a SQL predicate that must return zero rows. Doubles as a monitoring spec and an extension of I1–I16
12. Vocabulary — `ErrorClass` (8, with `RETRYABLE` = `not_dispatched`, `rate_limited`, `server_error`), `ProbeOutcome` (4), `Verdict` (3), episode close states and outcomes, dead-letter `retry_mode` and categories, budget states, customer-visible terminal reasons
13. Terminal reason → operator action → budget consequence → customer message, as one table
14. Cost and latency per path — worst-case time to a dead letter, and how long money sits LOCKED
15. Contradictions and open rulings
16. Appendix: provenance table

## Open rulings: do not block on them

Six rulings land inside this document. Give each one a "what would decide this" field, and write what the matrix says under *each* possible ruling. That lets the work finish while the rulings stay open, and it hands the owner a decision with its consequences already worked out.

| Ruling | Question it decides | Where it lands |
| --- | --- | --- |
| CONF-005 | AutonomyLevel source for verification-layer selection | §6, which layers are required |
| CONF-040 | Verification after a probe has no adapter result | §4 rows where the probe confirmed execution |
| CONF-043 | In-flight step of a tampered plan | §7, the plan-integrity path |
| CONF-044 | Checkpoints as a hint only | §2, whether checkpoints are evidence at all |
| CONF-046 | Orphan rule, by latest lease | §7, who may be taken over |
| CONF-047 | RECONCILING resolution | §7 and §9, how such a run ends |

CONF-028 and CONF-029 are already ruled and should be cited as settled, not reopened.

## Scope and shelf life

**Non-goals.** Cross-step data flow, branching graphs, the HITL channel, billing, fleet dispatch. Naming them keeps the document from sprawling into the deferred phases.

**Assumptions to state explicitly**, because each one silently shapes the matrix: in-process dispatcher only; the default `probe()` returns INCONCLUSIVE, so every real uncertainty today dead-letters after three attempts; lease TTL versus step timeout is unresolved (CONF-045); forced RLS is the tenancy guard; single node.

**What invalidates it.** Name the three events and which sections each rewrites.

| Event | Sections it rewrites |
| --- | --- |
| Real provider adapters arrive (2c) | §4 and §5 — `probe()` stops being INCONCLUSIVE, so rows that dead-letter today start resolving |
| The multi-node fleet arrives (2f) | §7 and §11 — takeover, orphan detection and the impossible-state predicates |
| Step-to-step data flow arrives (2a) | §2 and §4 — new evidence, and entry check 5a changes |

Write that section last but make it prominent. A document without it gets trusted after it has gone stale, which is worse than not having one.

## Business consequences to work out in §13

Every row of the matrix eventually reaches a customer. Rank them by how often they will occur and how badly they read, not by how interesting they are technically. The first three are correct behaviour that will still be reported as bugs — those need wording and an SLA, not a fix.

| Symptom the user reports | Matrix origin | Severity | What the document must supply |
| --- | --- | --- | --- |
| Budget held, nothing happened | Both exhaustion paths leave the reservation LOCKED | High, frequent | Resolution SLA, who releases it, and the message that explains the hold |
| It said it failed but it went through | INCONCLUSIVE x3 on a real side effect | High | Wording that distinguishes unknown from failed; the probe evidence to show on request |
| The same action happened twice | Retry of an operation whose retry\_safety was wrong in the registry | Critical, rare | The registry audit this implies, and which rows depend on retry\_safety being correct |
| Nothing came back at all | A run left non-terminal | Critical | Every row that can leave a run non-terminal, with its detection query |
| It took far too long | Three probe attempts with backoff, then three verification attempts | Medium, frequent | Worst-case latency per path, computed, not estimated |
| Waiting on a human, forever | human\_verification\_pending with no HITL channel | High | Flag as a product gap with an interim operator procedure |
| Support cannot explain it | Redaction strips provider bodies from envelope, logs and all persisted rows | Medium | What support may see, and where they see it |
| Everything broke at once | A registry version bump denies previously valid plans (CONF-008) | Critical, correlated | Call out separately: this is the only failure mode that hits every tenant simultaneously |

Two framings worth stating explicitly, because they change how the product is sold: the system is deliberately built to hold money and stop rather than guess, and it is honest about not knowing. Both are the right engineering choice and both look like defects to a customer who was not told. The document should say what the customer is told, in plain words, for each terminal reason.

## Done when

- [ ] Every evidence combination the schema permits has a row, including the ones no milestone covers
- [ ] Every row carries a status tag and a provenance citation
- [ ] Every row names its golden case, or is listed as uncovered
- [ ] The three derived views (M13, M15, M19) are generated from the matrix and agree with the milestone cards, or the disagreement is written up as a finding
- [ ] Every impossible state has a SQL predicate
- [ ] Every customer-visible terminal reason has an operator action and a support message
- [ ] The six open rulings each have both branches written out
- [ ] A demanding reviewer could use §10 to diagnose a live incident without reading anything else
