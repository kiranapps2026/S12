# Phase 7: Freeze

Part of the [S12 truth model](README.md). Input: every earlier phase. It produces `docs/truth_model/S12_TRUTH_MODEL.md`
with §1 (scope and precedence), §16 (provenance), the decision log, and the shelf-life section. This is the second
handoff: the next implementation session should be able to work from the document without re-deriving anything.

## Purpose

Assemble the phase outputs into one citable document. Then state what it assumes and when it stops being true. A
document without its shelf life gets trusted after it has gone stale, which is worse than having no document.

## Entry conditions

- Phases 4, 5a and 5b exit criteria met.
- Phase 6: every ruling either recorded and applied, or carried as written branches with the row tags
  `ruling:<CONF>`.

## Assembly

| § | Taken from |
|---|---|
| 1 Scope and precedence | Phase 1 precedence, plus "decides nothing; proposes" and the non-goals below |
| 2 Evidence ladder | `P2_LADDER.md` |
| 3 Who writes which evidence | `P1_WRITERS.md`, checked in phase 3 |
| 4 Master matrix | `P3_MATRIX.csv`, rendered by milestone column, with the trace per row |
| 5–7 Derived views | `P4_VIEW_A.md`, `P4_VIEW_B.md`, `P4_VIEW_C.md` |
| 8 Invariants | `P4_INVARIANTS.md` |
| 9 Disposal | Phase 3 disposal columns plus `P5B_LOCKED_TIME.md` |
| 10 Reverse index | `sql/reverse_index.sql`, rendered as a table |
| 11 Impossible states | `P2_IMPOSSIBLE.csv` with its SQL from `sql/impossible_states.sql`, `row_coherence.sql`, `history_predicates.sql` |
| 12 Vocabulary | `P1_VOCABULARY.md` and `P1_GLOSSARY.md` |
| 13 Terminal reasons | `P5B_ENDINGS.md` |
| 14 Cost and latency | `P5B_LATENCY.md` |
| 15 Contradictions and open rulings | `FINDINGS.md` (open entries) and `P6_BRANCHES.md` |
| 16 Provenance | Built in this phase (below) |

Put the shelf-life section directly after §1, not at the end.

## Provenance appendix (§16)

One row per claim source used anywhere in the document: source, `file:line` at the frozen commit, the rows and rules
that cite it, and its status tag. Generate it from the provenance fields of the phase outputs; do not write it by
hand. A row in §4 whose provenance resolves to nothing fails the freeze.

## Decision log

Dated entries in the style of `S12_RECORDS.md`, append-only, with supersession: every ruling applied (phase 6), every
finding accepted as a deliberate exception (phase 4), every customer message and resolution time the owner signed off
(phase 5b), and every re-run of phase 2 with its reason.

## Shelf life

### Non-goals

Cross-step data flow, branching graphs, the HITL channel, billing, fleet dispatch, batch processing (C40),
replanning (C41).

### Assumptions (each one shapes the matrix)

| Assumption | Source | Rows it shapes |
|---|---|---|
| In-process dispatcher only, single node | Golden M12 `InProcessDispatcher`; roadmap 2f | All of §7 |
| The default `probe()` returns INCONCLUSIVE, so every real uncertainty dead-letters after three attempts | C32; §15.3 `no_probe` | Every probe row; §13 frequencies |
| The human layer always returns UNKNOWN (no HITL channel) | D4 | Every IRREVERSIBLE row |
| Forced RLS is the tenancy guard; one SECURITY DEFINER discovery function (if CONF-042 A) | C34; `015` | §7, §10, §11 |
| Lease TTL versus step duration: renewal per CONF-045 as ruled | CONF-045 | R1 rows; §14 |
| Timeouts and the lease TTL come from the environment and have no default in code | `settings.py` | §14 figures |
| Rows checked against schema 001–015 plus drafted 016–017 | Phase 5a run log | §10, §11 |

### What invalidates it

The brief named three events. The roadmap (`batch_bundles/ROADMAP_AFTER_S12.md:195-223`) shows 2a reaches further
than the brief said.

| Event | Sections it rewrites | Why |
|---|---|---|
| Real provider adapters (2c) | §4, §5, §7, §13, §14 | `probe()` and `observe()` stop defaulting to INCONCLUSIVE/UNKNOWN, so rows that dead-letter today start resolving; frequencies and latencies change |
| Multi-node fleet (2f) | §7, §10, §11, R1 | Takeover, orphan detection, breaker persistence and the impossible-state predicates change; the single-node assumption ends |
| Step-to-step data flow (2a) | §2, §3, §4, §7, M11 rows | New evidence (step output references). Per the roadmap it re-certifies S12–S15: entry check 5a, the loop, recovery and idempotency all change |
| Branching graphs (2b) | §4, §9 | Dependents and consolidation (§8 step 12, §10) stop being a straight line |
| Any change to gate Appendix A, a new ruling on an evidence table, or a re-pin of B3–B5 | Re-run phase 2 for the affected machine | The row list was derived from them |
| M11, M13, M15 or M17 implemented on `s12-work` | Re-run phase 5a | The three assumptions in `sql/step_evidence.sql` become checkable |

### Freeze record

At the top of `S12_TRUTH_MODEL.md`: the commit, the gate's pin hash (`docs/gates/spec_pins.sha256`), the golden pin
state (`docs/gates/s12_pins.sha256`; which batches are pinned), the schema version, and the date.

## Procedure

1. Assemble the sections in the order above, the shelf life right after §1.
2. Generate §16 and check that every row resolves.
3. Write the freeze record.
4. Re-run the smoke test and the 5a predicates on the frozen commit; record the result in the freeze record.
5. Commit with the message "truth model frozen at <commit>".

## Exit criteria (the brief's "done when", corrected)

- [ ] Every D1–D7 combination is a row, an impossible state or a conditional row, including the ones no milestone
  covers.
- [ ] Every row carries a status tag and a provenance citation; nothing is uncited, nothing undated.
- [ ] Every row names its golden case, or is listed as untested or uncovered.
- [ ] The three derived views are generated from the matrix and agree with the milestone cards, or the disagreement
  is a TF entry.
- [ ] Every impossible state and history rule has a SQL predicate with a positive control.
- [ ] Every customer-visible ending has an operator action and a message the owner signed off.
- [ ] Every open ruling (CONF-005, 042–047, proposed 048) has both branches written, or is ruled and applied.
- [ ] Someone who has never seen the code can use §10 to diagnose a live incident without reading anything else.
- [ ] The shelf-life section is in place, right after §1.

## Can it split?

No.

## Keeping it honest after the freeze (proposed)

A `check` mode in the phase 2 script (`tools/truth_model.py check`) that the `docs` CI job runs. It fails if
`tm_ids.json` renumbered or deleted an ID, a §4 row lost its provenance, or the gate's Appendix A changed since the
recorded pin. The SQL smoke test can run in the `suite` job, which already has PostgreSQL 16. Neither exists yet, and
adding them to CI is the owner's call.
