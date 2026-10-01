# Phase 2: Enumerate and prune

Part of the [S12 truth model](README.md). Input: phase 1 outputs. It produces §2 (evidence ladder), the skeleton of
§4 (master matrix) and the set behind §11 (impossible states).

## Purpose

Build the state space from what the database can tell a reader after a crash, before reading anything that says how
the milestones behave. Remove the combinations the schema, the gate or the invariants make impossible. Mint a frozen
ID for every row that survives and for every rule that removed one. Both halves are deliverables: the surviving rows
become the matrix, and the removed set becomes the impossible-state predicates.

## Entry conditions

- Phase 1 exit criteria met.
- No milestone card, review, guide or reference code has been opened (contamination rule, phase 1).

## The evidence dimensions (corrected)

Each dimension describes one step's current attempt as read from the database. Values marked † are allowed by a CHECK
constraint but can never be written; they stay in the enumeration so their predicates exist.

| ID | Dimension | Values | Read from | Written by |
|---|---|---|---|---|
| D1 | Step status | pending, running, timeout, pending_probe, completed, failed, cancelled, skipped, dead_letter, unknown †, partial † | `execution_steps.status` (`009:48`) | M12, M13, M15, M19 |
| D2 | Step reservation | none; live: reserved, locked, committed; released only (every row released) | `budget_reservations` by `step_id` (at most one live row, `010` unique index) | M9, M12, M13, M17 |
| D3 | Dispatch marker | `null` (never dispatched), `below` (`dispatched_attempt < attempt`), `current` (`= attempt`); `above` † | `execution_steps.dispatched_attempt`, `attempt` (`010:9`) | M11 |
| D4 | Ledger | none, expired (counts as none, MUTATION_SAFETY §5), success, failure | `idempotency_ledger` by key `request_id:plan_step_id` and `tenant_id` | M11 |
| D5 | Layer verdicts | none; open (some recorded, not all required PASS, no FAIL); fail (any FAIL); pass (every layer required on this path recorded PASS, CONF-040) | `verification_layer` events in `execution_events` (CONF-036; table only in drafted `016`) | M15 |
| D6 | Latest episode | none; for EXECUTION and VERIFICATION each: open `pending_probe`, open `reconciling`, closed `confirmed_success`, closed `confirmed_failure`, closed EXHAUSTED | `step_reconciliations` (`015`; at most one open per step) | M13, M15, M19 |
| D7 | Uncertainty dead letter | none; open (pending or retrying) × retry_mode PROBE, VERIFY, NONE; resolved EXECUTED, NOT_EXECUTED, UNDETERMINED; abandoned | `dead_letters` with `error_type = 'unknown_unresolved'`, `origin = 'execution'` | M13, M15, M17 |
| D8 | Operation class | R; W, D or IRREVERSIBLE, each × retry allowed / not allowed (IRREVERSIBLE, `retry_safety = never`, non-idempotent D, or ceiling reached) | `execution_steps.effective_mutation`, registry `retry_safety`, `attempt` | registry, M11 |

Dead letters with another `error_type` (`transient`, `permanent`, `data`) are records only. They never move the step
or the budget (§11, D4), so they are not a dimension. Phase 3 cites them in the dead-letter column.

### Run context (applied before the step rule)

§13 checks the run before it interprets the in-flight step (step 1 takeover, 1a live check, 2 plan digest). These are
enumerated separately as run-context rows (`RC-nnn`), each stating what it does to the step rows:

| ID | Context | Values | Effect on step rows |
|---|---|---|---|
| R1 | Ownership lease | usable; lapsed (`active`, `expires_at <= now()`); expired; released; never leased | Decides only *whether* the cold path runs (CONF-033, CONF-046). Does not change a verdict |
| R2 | Live authorization | valid; revoked | Revoked: resolve the in-flight step by the same rule, then cancel (§13 1a). Changes what follows, not the step verdict |
| R3 | Plan digest | match; mismatch | Mismatch **replaces** the verdict of every row that needs a probe or verification (CONF-043, open). Not a pure override |
| R4 | Run status | running; reconciling | Decides whether a NOT_EXECUTED retry is possible (CONF-047, open) |

Factoring the run out like this is valid only while R1 and R2 leave step verdicts unchanged. Phase 4 tests that
assumption under principle 3. R3 and R4 cannot be factored out: phase 2 mints their rows as explicit RC × TM pairs,
one set per ruling branch.

### Why D8 is not crossed with everything

D8 changes verdicts in two places only: the NOT_EXECUTED path (retry or `cancelled (not_executed_no_retry)`, §9,
A.2) and the read rule (C6 `:383`: `pending_probe → pending (read_reexecution_safe)` without a probe). Split a row by D8
only where the evidence leaves one of those two paths open. Record each split in the row (`d8_split`). Never split
at phase 3.

## The evidence ladder (§2 draft)

Two orders. The draft must state both, because they differ.

**Authority** (what a fact proves about the world, strongest first): unexpired ledger row (definitive: the adapter
produced this result) → recorded layer verdicts → marker `null`/`below` (proves *not* dispatched) → closed episode
outcome → marker `current` (proves only that a call was possible) → open episode → reservation state (bookkeeping,
proves nothing about the world) → nothing. An expired ledger row and a checkpoint row prove nothing (MUTATION_SAFETY
§5; §13 `:1788`; CONF-044 is open on whether checkpoints are evidence at all).

**Consultation** (what the recovery reader checks first, §13 step 3): open episode → ledger (with layer verdicts) →
marker → probe. Within an open EXECUTION episode, each attempt checks the ledger again before probing (§9).

## Pruning rules

Each rule removes combinations, and each gets an ID `IS-nnn` minted here. Every rule records its basis:

| Basis | Meaning | Removed rows go to |
|---|---|---|
| `schema` | The database rejects the state | Impossible set |
| `gate` | Appendix A, a ruling or a gate section forbids it | Impossible set |
| `invariant` | I1–I18 forbids it | Impossible set |
| `derived` | Follows from gate text by a stated argument | Impossible set, status `proposed` |
| `atomicity` | Impossible only if two writes share a transaction, and the gate does not say they must | **Conditional set**: kept as rows tagged `unknown` |
| `ruling:<CONF>` | Depends on an open ruling | Conditional set, one branch per outcome |

History rules (the transition log, the ledger events) are not state rules. Mint them as `IH-nnn` (for example I5,
I6, I14, I16). They go straight to phase 5a.

### Seed rules (confirm, cite and mint; this list is a starting point, not complete)

| Seed | Rule | Basis | Source |
|---|---|---|---|
| a | D1 ≠ `unknown` (handled by recovery all the same: CONF-048) | gate, ruling:CONF-048 | A.2 `:2375`; C24 |
| b | D1 ≠ `partial` | gate | A.2; C6 |
| c | D3 ≠ `above` | derived | C35; M11 `mark_dispatched` sets `attempt` and the marker together |
| d | D1 ∈ {running, timeout, pending_probe} ⇒ D2 = locked | gate | A.2 `:2365` (I-3); A.3 (locked leaves only on terminal or NOT_EXECUTED). DEF-004 says the prototype breaks this |
| e | D2 = reserved ⇒ D1 = pending | gate | A.3 `:2395` |
| f | D1 = completed ⇒ D2 = committed | invariant | I12 |
| g | D1 ∈ {failed, cancelled, skipped} ⇒ D2 ∈ {none, released} | invariant | I12 (see candidate C-4) |
| h | D1 = dead_letter ⇒ D2 follows D7: open → locked; EXECUTED or UNDETERMINED → committed; NOT_EXECUTED → released | invariant | I12; C21; A.3 |
| i | Open episode ⇒ D1 ∈ {running, timeout, unknown, pending_probe} | gate | §13 step 3; C16 |
| j | VERIFICATION episode never has outcome NOT_EXECUTED | gate | C19 |
| k | Episode closed ⇔ outcome set; EXHAUSTED ⇒ status `pending_probe`; confirmed ⇒ closed | gate | A.7 `:2446-2448` |
| l | D1 = dead_letter ⇔ D7 ≠ none | gate | §11 ("only unresolved uncertainty puts the step there"); D4 |
| m | D1 = dead_letter ⇒ latest episode closed EXHAUSTED | gate, ruling:CONF-043 | §9; C19; a tampered plan's in-flight step dead-letters without a probe |
| n | D4 ∈ {success, failure} (unexpired) ⇒ D1 ∉ {pending, skipped} | derived | §9 (ledger before probe); C17 |
| o | D4 = failure ⇒ D1 ≠ completed | gate | §13 (definitive failure); C17 |
| p | D4 ≠ none ⇒ D3 ≠ `null` | derived | C35 (marker before every call); CONF-025 (rows only for results the adapter produced) |
| q | D5 ≠ none ⇒ D3 ≠ `null` and D1 ∉ {pending, skipped} | derived | §8 step 9 (verification follows a result or a confirmed probe) |
| r | D5 = fail ⇒ D1 ≠ completed; D5 = pass ⇒ D1 ≠ failed | gate | §8 step 9 |
| s | D1 = completed ⇒ D5 = pass | gate | §8 step 9; CONF-040 (required set after a probe) |
| t | D1 = skipped ⇒ D3 = `null`, D4 = none, D5 = none, D6 = none | derived | A.2 (only `pending → skipped`); §8 step 12 (only dependents, not yet started) |
| u | Latest episode closed EXHAUSTED ⇒ D1 = dead_letter | atomicity | The gate does not say the close and the step move share a transaction |
| v | Latest EXECUTION episode `confirmed_success` ⇒ D1 = completed, or a VERIFICATION episode follows | atomicity | M13/M15 order not fixed by the gate |

## Procedure

1. Encode D1–D7 and the seed rules in a script (proposed: `tools/truth_model.py`, standard library only, so it runs
   in the `docs` CI job beside `tools/doc_consistency.py`). The raw cross product of D1–D7 is 309,760 (11 × 5 × 4 × 4 × 4 × 11 × 8)
   combinations: generate it, do not write it by hand.
2. Apply rules in basis order (schema, gate, invariant, derived). For every removed combination, record *every* rule
   that removes it, not only the first. A combination removed only by `atomicity` or `ruling:` rules goes to the
   conditional set.
3. Collapse survivors that the dimensions cannot tell apart into one row. Two combinations stay separate rows when
   any reader (§13, §9 or C19) would treat them differently.
4. Split by D8 where the two paths named above remain open.
5. Mint IDs. Keep `work/tm_ids.json`, which maps a canonical key (dimension values in D1…D8 order) to `TM-nnn`. New
   keys get the next number. A key that disappears keeps its number, marked `retired` with the reason. The same file
   holds `IS-nnn`, `IH-nnn` and `RC-nnn`.
6. Write the RC rows (R1–R4). For R3 and R4, one set per branch of CONF-043 and CONF-047.
7. Write candidate observations (see below) into `work/FINDINGS.md` as `candidate`. Phase 2 does not judge them.

## Outputs (`docs/truth_model/work/`)

| File | Content |
|---|---|
| `P2_DIMENSIONS.md` | The table above as frozen, with the commit |
| `P2_ROWS.csv` | `tm_id,d1,d2,d3,d4,d5,d6,d7,d8_split,set(reachable/conditional),conditional_on,status` |
| `P2_IMPOSSIBLE.csv` | `is_id,rule,basis,source,removed_count,example` |
| `P2_HISTORY_RULES.csv` | `ih_id,rule,invariant,source` |
| `P2_RUN_CONTEXT.csv` | `rc_id,r1,r2,r3,r4,effect,branch,affected_tm_ids` |
| `P2_LADDER.md` | §2 draft (both orders) |
| `tm_ids.json` | The ID registry (the only place IDs are minted) |

## Exit criteria

- Every D1–D7 combination is in exactly one place: a row, the impossible set or the conditional set. The script
  checks this and prints the three counts.
- Every rule has a basis and a `file:line` source.
- `tm_ids.json` is committed, and the commit message records "rows frozen at <commit>". From then on, only a
  deliberate re-run of phase 2 changes it.

## Can it split?

No. One minting authority. A second worker would produce IDs that collide or drift.

## Candidate observations already visible (log as `candidate`, do not resolve here)

| ID | Observation | Sources |
|---|---|---|
| C-1 | A read step that crashes with the marker `current` and no ledger row is probed under §13, but C6 says a read probe cannot observe anything. The default probe returns INCONCLUSIVE, so the read dead-letters after three attempts with its budget LOCKED. M13's in-line path never probes a read. | C6 `:383`; §13 `:1780`; M13 docstring |
| C-2 | If closing an episode EXHAUSTED and moving the step to dead_letter are separate transactions, a crash between them leaves the step in pending_probe with no open episode. Recovery then opens a new episode and probes three more times (principle 3). | Seed u; A.7 |
| C-3 | An expired ledger row counts as none, so certainty decreases over time (principle 2). For an IRREVERSIBLE step, an expired success leads to a probe and, by default, a dead letter. | MUTATION_SAFETY §5; §13 `:1780` |
| C-4 | I12 says a cancelled step holds no live reservation, but M16 releases RESERVED reservations at consolidation. If a step is cancelled while its reservation is RESERVED, the two disagree until consolidation. | I12 `:2089`; M16 docstring |
| C-5 | DEF-004 (open): the prototype loop moves the step to running and the reservation to locked in two transactions, so `running` with `reserved` is reachable on today's code. | `S12_DEFECTS.md` DEF-004 |
| C-6 | M19 requires `unknown → pending_probe (recovery)`, which Appendix A does not list. | Proposed CONF-048 |
| C-7 | Monitoring predicates must read across tenants, but RLS is forced on every evidence table. Same root as CONF-042. | `015` RLS block; CONF-042 |
| C-8 | §9 says "IRREVERSIBLE and non-idempotent D steps are never retried" after NOT_EXECUTED, but the M11 draft gives a D step with `retry_safety = safe` a ceiling of 2. Whether "non-idempotent" means `retry_safety <> 'idempotent'` or only `never` decides D8 for every D row. | §9 `:1663-1665`; M11 docstring (`retry_policy.ceiling`); `001:86` |
