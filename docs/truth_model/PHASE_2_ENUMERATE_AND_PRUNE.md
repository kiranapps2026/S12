# Phase 2: Enumerate and prune

Part of the [S12 truth model](README.md). Input: phase 1 outputs. It produces §2 (evidence ladder), the skeleton of
§4 (master matrix), the run-outcome rules behind §9, and the set behind §11 (impossible states).

Revised in review pass 2 (`REVIEW_LOG.md` P2-1, P2-4, P2-5, P2-7, P2-9, P2-10, P2-12, P2-13).

## Purpose

Build the state space from what the database can tell a reader after a crash, before reading anything that says how
the milestones behave. Remove the combinations the schema, the gate or the invariants make impossible. Mint a frozen
ID for every row that survives and for every rule that removed one. Both halves are deliverables: the surviving rows
become the matrix, and the removed set becomes the impossible-state predicates.

## Entry conditions

- Phase 1 exit criteria met.
- No milestone card, review, guide or reference code has been opened (contamination rule, phase 1).

## The evidence dimensions (step level)

Each dimension describes one step's current attempt as read from the database. Values marked † are allowed by a CHECK
constraint, or by the absence of one, but should never be written. They stay in the enumeration so their predicates
exist.

| ID | Dimension | Values | Read from | Written by |
|---|---|---|---|---|
| D1 | Step status | pending, running, timeout, pending_probe, completed, failed, cancelled, skipped, dead_letter, unknown †, partial † | `execution_steps.status` (`009:48`) | M12, M13, M14, M15, M19 |
| D2 | Step reservation | none; live: reserved, locked, committed; released only (every row released) | `budget_reservations` by `step_id` (at most one live row, `010` unique index) | M9, M12, M13, M17 |
| D3 | Dispatch marker | `null` (never dispatched), `below` (`dispatched_attempt < attempt`: this attempt never dispatched), `current` (`= attempt`: a call was possible); `above` † | `execution_steps.dispatched_attempt`, `attempt` (`010:9`) | M11 |
| D4 | Ledger | none; expired (counts as none, §8 `:1618-1621`); success; failure (class only, no body); foreign † (a row for the key with another `kernel_op_id`: `IdempotencyConflict`, a stop condition) | `idempotency_ledger` by key `request_id:plan_step_id` (C9, CONF-024) and `tenant_id` | M11 |
| D5 | Layer verdicts | none; open (some recorded, not all required PASS, no FAIL); fail (any FAIL); pass (every layer required on this path recorded PASS) | `verification_layer` events, latest per layer (CONF-036; `execution_events` exists only in drafted `016`) | M15 |
| D6 | Latest episode | none; for EXECUTION and VERIFICATION each: open `pending_probe`, open `reconciling`, closed `confirmed_success`, closed `confirmed_failure`, closed EXHAUSTED | `step_reconciliations` (`015`; at most one open per step) | M13, M15, M19 |
| D7 | Uncertainty dead letter | none; open (pending or retrying) × retry_mode PROBE, VERIFY, NONE; resolved EXECUTED, NOT_EXECUTED, UNDETERMINED; abandoned | `dead_letters` with `error_type = 'unknown_unresolved'`, `origin = 'execution'` | M13, M15, M17 |
| D8 | Operation class | R; W, D or IRREVERSIBLE, each × retry allowed / not allowed (IRREVERSIBLE, `retry_safety = never`, non-idempotent D (C-8), or ceiling reached) | `execution_steps.effective_mutation`, `kernel_ops.retry_safety`, `attempt` | registry, M11 |
| D9 | Attempt events | none; started (`step_attempt` only); called (`ProviderCalled`, no `ProviderReturned`); returned ok; returned error; hit (`idempotency_hit`) | `execution_events` for the current `attempt_id` | M11, M12 |

Notes:
- Dead letters with another `error_type` (`transient`, `permanent`, `data`) are records only. They never move the step
  or the budget (§11, D4), so they are not a dimension. Phase 3 cites them in the dead-letter column. Rollback dead
  letters (`origin = 'rollback'`, C27) never touch the run, the step or the budget, and are out of the matrix.
- D9 exists because every event is its own fenced transaction (golden M12 `record`), and §13 never reads events. A
  durable `ProviderReturned` beside a missing ledger row is evidence that recovery ignores (C-9).
- D4 `foreign` is reachable only through a defect or a cross-tenant key collision (C-14). It is kept so that its
  predicate and its stop-condition row exist.

## Run context (applied before the step rule)

§13 checks the run before it interprets the in-flight step (step 1 takeover, 1a live check, 2 plan digest), and
the loop checks cancellation before every step (C16). These are enumerated as run-context rows (`RC-nnn`), each
stating what it does to the step rows:

| ID | Context | Values | Effect on step rows |
|---|---|---|---|
| R1 | Who may drive the run | ownership names the reader's runtime (never taken over, CONF-033); latest lease active and unexpired; latest lease lapsed or expired; latest lease released, within / beyond one TTL; never leased, ownership younger / older than one TTL (CONF-046) | Decides only *whether* the cold path runs. Leases are per step (§8 `:1589`, `:1639`), so a live run between steps holds none. Does not change a verdict |
| R2 | Live authorization | valid; revoked: `kill_switch_engaged`, `authorization_revoked`, `binding_invalid`, `credential_invalid` | The in-flight step is resolved first (§13 1a). If it resolves NOT_EXECUTED, it ends `cancelled` with the revocation reason: no retry, and not `not_executed_no_retry` (M14; `M19_recovery.py:546`). Remaining PENDING steps are cancelled with the reason. **Not a pure override.** Which reason wins when several hold is unpinned (C-13) |
| R3 | Plan digest | match; mismatch (against both stored hashes, CONF-034) | Mismatch **replaces** the verdict of every row that would need a probe or verification (CONF-043, open; C-12). No in-flight step: every PENDING step `cancelled (run_dead_lettered)` |
| R4 | Run status | running; reconciling | In RECONCILING a NOT_EXECUTED step ends `cancelled (not_executed_no_retry)` (CONF-047, open) |
| R5 | Cancellation requested | no; yes (`execution_runs.cancel_requested_at`) | Applied only once no step is RUNNING or PENDING_PROBE (C16, M14). An in-flight call is never interrupted. A NOT_EXECUTED step ends `cancelled (user_cancelled)`. Survives a crash (M19) |

Only R1 can be factored out of the step rows. R2, R3, R4 and R5 change the continuation of NOT_EXECUTED rows, and R3
also changes the verdict of uncertain rows. Phase 2 mints them as explicit RC × TM pairs: one set per value, and for
R3 and R4 one set per ruling branch. Combinations of R2, R3 and R5 whose precedence no source pins are minted with
status `unknown`. For example, tampered and revoked: the B5 review pins only that CONF-043 wins the safety
properties, not which reason is recorded.

## Run-outcome rules (§9, consolidation)

The step matrix decides each step. The run's ending is decided by consolidation, and §10's table is overridden in
several places. Mint each rule as `RO-nnn` and state precedence explicitly.

| Seed | Rule | Source |
|---|---|---|
| a | Any step DEAD_LETTER → run DEAD_LETTER (FAILURE); it wins over CANCELLED and over a revocation | §10 `:1682`; C16 `:517`; M14 |
| b | Any step `cancelled (run_dead_lettered)` → run DEAD_LETTER, even with no DEAD_LETTER step and no dead-letter record | CONF-034; `M19_recovery.py:311-334` |
| c | Revocation → CANCELLED with its reason; cancellation → CANCELLED `user_cancelled`; budget exhausted → CANCELLED `budget_exhausted` | C23; C16; C15 `:497` |
| d | CANCELLED with no step COMPLETED → quota refunded once, in the cancel transaction | C39; CONF-037 |
| e | All COMPLETED, or COMPLETED + SKIPPED with no failure → COMPLETED | §10 |
| f | ≥ 1 COMPLETED and ≥ 1 FAILED or CANCELLED → PARTIAL | §10 |
| g | No step COMPLETED → FAILED | §10 |
| h | After consolidation no reservation is RESERVED; LOCKED only on a DEAD_LETTER step | §10; I2 |

Rule b produces a DEAD_LETTER run that may hold no dead letter at all. The customer gets `error`, not recoverable, and
the operator has nothing to resolve. That is a phase 5b ending in its own right.

## Why D8 is not crossed with everything

D8 changes outcomes in two places only: the NOT_EXECUTED continuation (retry, or `cancelled` with
`not_executed_no_retry` or an R2/R5 reason; §9, A.2) and the read rule (C6 `:383`: `pending_probe → pending
(read_reexecution_safe)` without a probe, CONF-028). Split a row by D8 only where the evidence leaves one of those
paths open. Record each split in the row (`d8_split`). Never split at phase 3.

## The evidence ladder (§2 draft): one ladder per question

Evidence answers four different questions, and a fact can only outrank another fact about the same question. Pass 1
ranked them in one list, which compared layer verdicts with dispatch markers.

| Question | Evidence, strongest first | Notes |
|---|---|---|
| Q1 Was this attempt dispatched? | marker `null` or `below` (proves **not** dispatched, C35) → marker `current` (a call was possible, not certain) | A marker without a call costs one unnecessary probe, never a duplicate (C35) |
| Q2 Did the provider act, and how? | unexpired ledger row (the adapter's own definitive result) → `idempotency_hit` event → `ProviderReturned` event status → closed EXECUTION episode outcome (the probe's answer) → `ProviderCalled` without a return (called, outcome unknown) → nothing | An expired ledger row proves nothing (§8 `:1618-1621`). §13 consults only the ledger and the probe; the events are durable but unread (C-9) |
| Q3 Is the effect verified? | latest verdict per required layer (a FAIL is definitive and not retryable, §8 `:1634`) → closed VERIFICATION episode outcome → nothing | Recovery can re-run a recorded FAIL (C-10) |
| Q4 Is the money settled? | reservation state | A consequence of Q1–Q3, never evidence for them |

Checkpoints answer none of the four (§13 `:1788`; CONF-044 is open on whether they are written at all).

**Consultation order** (what the recovery reader checks first, §13 step 3): open episode → ledger (with layer
verdicts) → marker → probe. Within an open EXECUTION episode, each attempt checks the ledger again before probing
(§9). The live path (M11) checks: live authorization → ledger → marker (`dispatched_without_record` if already
`current`) → call.

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

History rules (the transition log, the order of events) are not state rules. Mint them as `IH-nnn`: I5, I6, I14, I16,
plus the write-order pairs of phase 4. They go straight to phase 5a.

### Seed rules (confirm, cite and mint; a starting point, not complete)

| Seed | Rule | Basis | Source |
|---|---|---|---|
| a | D1 ≠ `unknown` (recovery handles it all the same: CONF-048) | gate, ruling:CONF-048 | A.2 `:2375`; C24 |
| b | D1 ≠ `partial` | gate | A.2; C6 |
| c | D3 ≠ `above` | derived | C35; M11 `mark_dispatched` sets `attempt` and the marker together |
| d | D1 ∈ {running, timeout, pending_probe} ⇒ D2 = locked | gate | A.2 `:2365` (I-3); A.3 (locked leaves only on terminal or NOT_EXECUTED). DEF-004: the prototype breaks this (C-5) |
| e | D2 = reserved ⇒ D1 = pending | gate | A.3 `:2395` |
| f | D1 = completed ⇒ D2 = committed | invariant | I12 |
| g | D1 ∈ {failed, cancelled, skipped} ⇒ D2 ∈ {none, released} | invariant | I12 (C-4) |
| h | D1 = dead_letter ⇒ D2 follows D7: open → locked; EXECUTED or UNDETERMINED → committed; NOT_EXECUTED → released | invariant | I12; C21; A.3 |
| i | Open episode ⇒ D1 ∈ {running, timeout, unknown, pending_probe} | gate | C18 (an episode opens with the step's move to pending_probe); §13 step 3 (in-flight states) |
| j | VERIFICATION episode never has outcome NOT_EXECUTED | gate | C19 |
| k | Episode closed ⇔ outcome set; EXHAUSTED ⇒ status `pending_probe`; confirmed ⇒ closed | gate | A.7 `:2446-2448` |
| l1 | D7 ≠ none ⇒ D1 = dead_letter (no other step state carries an uncertainty dead letter) | gate | §11 (only unresolved uncertainty puts the step there) |
| l2 | D1 = dead_letter ⇒ D7 ≠ none (the record and the step move are one write) | atomicity | §11 and D4 give the meaning, not the transaction |
| m | D1 = dead_letter ⇒ latest episode closed EXHAUSTED | gate, ruling:CONF-043 | §9; C19. Under CONF-043 A the episode is unspecified (C-12) |
| n | D4 ∈ {success, failure} ⇒ D1 ∉ {pending, skipped} | derived | §9 (ledger before probe); C17 |
| o | D4 = failure ⇒ D1 ≠ completed | gate | §13 (definitive failure); C17 |
| p | D4 ≠ none ⇒ D3 ≠ `null` | derived | C35 (marker before every call); CONF-025 (rows only for results the adapter produced) |
| q | D5 ≠ none ⇒ D3 ≠ `null` and D1 ∉ {pending, skipped} | derived | §8 step 9 (verification follows a result or a confirmed probe) |
| r | D5 = fail ⇒ D1 ≠ completed; D5 = pass ⇒ D1 ≠ failed | gate | §8 step 9 |
| s | D1 = completed ⇒ D5 = pass | gate | §8 step 9; C17; CONF-040 (the required set after a probe) |
| t | D1 = skipped ⇒ D3 = `null`, D4 = none, D5 = none, D6 = none, D9 = none | derived | A.2 (only `pending → skipped`); §8 step 12 (only dependents, not yet started) |
| u | Latest episode closed EXHAUSTED ⇒ D1 = dead_letter | atomicity | The gate does not say the close and the step move share a transaction (C-2) |
| v | Latest EXECUTION episode `confirmed_success` ⇒ D1 = completed, or a VERIFICATION episode follows | atomicity | The M13/M15 order is not fixed by the gate |
| w | D9 ∈ {called, returned ok, returned error} ⇒ D3 = `current` | invariant | I16 |
| x | Latest episode is VERIFICATION ⇒ D3 ≠ `null` | derived | C19 (verification uncertainty follows a definitive adapter result or a ledger row) |
| y | D9 = hit ⇒ D4 ≠ none | derived | C17 (a hit reads a row; rows are never deleted, though they may expire) |

## Procedure

1. Encode D1–D7 and D9 and the seed rules in a script (proposed: `tools/truth_model.py`, standard library only, so it
   runs in the `docs` CI job beside `tools/doc_consistency.py`). The raw cross product is 2,323,200 combinations
   (11 × 5 × 4 × 5 × 4 × 11 × 8 × 6): generate it, never write it by hand.
2. Apply rules in basis order (schema, gate, invariant, derived). For every removed combination, record *every* rule
   that removes it, not only the first. A combination removed only by `atomicity` or `ruling:` rules goes to the
   conditional set.
3. Collapse survivors that no reader can tell apart into one row. Two combinations stay separate rows when any reader
   (§13, §9, C19, or the live path of M11/M14) would treat them differently, **or** when they differ in evidence a
   reader ignores (D9). Collapsing those would hide C-9.
4. Split by D8 where the two paths named above remain open.
5. Mint IDs. Keep `work/tm_ids.json`, which maps a canonical key (dimension values in D1…D9 order) to `TM-nnn`. New
   keys get the next number. A key that disappears keeps its number, marked `retired` with the reason. The same file
   holds `IS-nnn`, `IH-nnn`, `RC-nnn` and `RO-nnn`.
6. Write the RC rows (R1–R5) and the RO rules, with precedence.
7. Write the candidate observations below into `work/FINDINGS.md` as `candidate`. Phase 2 does not judge them.

## Outputs (`docs/truth_model/work/`)

| File | Content |
|---|---|
| `P2_DIMENSIONS.md` | The tables above as frozen, with the commit |
| `P2_ROWS.csv` | `tm_id,d1,d2,d3,d4,d5,d6,d7,d9,d8_split,set(reachable/conditional),conditional_on,status` |
| `P2_IMPOSSIBLE.csv` | `is_id,rule,basis,source,removed_count,example` |
| `P2_HISTORY_RULES.csv` | `ih_id,rule,invariant,source` |
| `P2_RUN_CONTEXT.csv` | `rc_id,r1,r2,r3,r4,r5,effect,branch,affected_tm_ids,status` |
| `P2_RUN_OUTCOME.csv` | `ro_id,rule,precedence,source,status` |
| `P2_LADDER.md` | §2 draft (four ladders and the consultation orders) |
| `tm_ids.json` | The ID registry (the only place IDs are minted) |

## Exit criteria

- Every combination is in exactly one place: a row, the impossible set or the conditional set. The script checks this
  and prints the three counts.
- Every rule has a basis and a `file:line` source.
- Every pair of R2, R3, R5 values has an RC row, with status `unknown` where precedence is unpinned.
- `tm_ids.json` is committed, and the commit message records "rows frozen at <commit>". From then on, only a
  deliberate re-run of phase 2 changes it.

## Can it split?

No. One minting authority. A second worker would produce IDs that collide or drift.

## Candidate observations (log as `candidate`; phase 4 judges them)

| ID | Observation | Sources |
|---|---|---|
| C-1 | A read step that crashes with the marker `current` and no ledger row is probed under §13, but C6 says a read probe cannot observe anything. The default probe returns INCONCLUSIVE, so the read dead-letters after three attempts with its budget LOCKED. M13's in-line path never probes a read. | C6 `:383`; §13 `:1780`; M13 docstring |
| C-2 | If closing an episode EXHAUSTED and moving the step to dead_letter are separate transactions, a crash between them leaves the step in pending_probe with no open episode. Recovery then opens a new episode and probes three more times (principle 3). | Seed u; A.7 |
| C-3 | An expired ledger row counts as none, so certainty decreases over time (principle 2). For an IRREVERSIBLE step, an expired success leads to a probe and, by default, a dead letter. | §8 `:1618-1621`; §13 `:1780` |
| C-4 | I12 says a cancelled step holds no live reservation, but consolidation releases RESERVED reservations (M16). If a step is cancelled while its reservation is RESERVED (a crash `after_budget_reserve` followed by a revocation, for example), the two disagree until consolidation. | I12 `:2089`; M16 docstring |
| C-5 | DEF-004 (open): the prototype loop moves the step to running and the reservation to locked in two transactions, so `running` with `reserved` is reachable on today's code. The M12 draft requires one transaction (`started` + `step_started`). | `S12_DEFECTS.md` DEF-004; M12 docstring |
| C-6 | M19 requires `unknown → pending_probe (recovery)`, which Appendix A does not list. | Proposed CONF-048 |
| C-7 | Monitoring predicates must read across tenants, but RLS is forced on every evidence table. Same root as CONF-042. | `015` RLS block; CONF-042 |
| C-8 | §9 says "IRREVERSIBLE and non-idempotent D steps are never retried" after NOT_EXECUTED, but the M11 draft gives a D step with `retry_safety = safe` a ceiling of 2. Whether "non-idempotent" means `retry_safety <> 'idempotent'` or only `never` decides D8 for every D row. | §9 `:1663-1665`; M11 docstring (`retry_policy.ceiling`); `001:86` |
| C-9 | A `ProviderReturned` event can be durable while the ledger row is not (separate fenced writes), and §13 does not read events. Recovery then probes instead of using the recorded return; with the default probe, the step dead-letters with its budget LOCKED. Only the status is in the event (M18 redaction), so the result data needed by schema and deterministic layers is gone either way. | M12 `record`; M11 docstring; §13 |
| C-10 | A FAIL recorded before a crash at `after_verification_before_step_commit` is re-run by the VERIFICATION episode §13 opens ("not recorded as PASS"), and C19 re-runs every layer not yet PASS. A definitive, non-retryable FAIL can turn into a PASS. No golden case covers it. | §8 `:1634`; §13 `:1757-1760`; C19 `:615-616`; `M19_recovery.py:152-163` |
| C-11 | No production path retries or resolves a dead letter (IMP-M17-2). A LOCKED reservation counts against `budget_pool` exactly like a committed one (I1), so the tenant is charged for every unresolved uncertainty, and an action that in fact never happened is never refunded. The safety claim ("money is never settled for an action whose outcome is unknown") holds in name only: LOCKED is not COMMITTED, but costs the same. | IMP-M17-2; I1 `:2078`; D4 |
| C-16 | By design, an adapter without `observe()` makes provider_state verification UNKNOWN, so **every** W, D or IRREVERSIBLE step on it ends DEAD_LETTER with the budget LOCKED, even when the call succeeded (C32). Until real adapters arrive (roadmap 2c), this is the most frequent ending of a mutation, and with C-11 none of them is ever settled. Not a defect; it dominates phases 5b and 7. | C32 `:1046-1050`; gate suite `:2039-2040` |
| C-12 | Under CONF-043 A, a tampered plan's in-flight step gets a PROBE-mode dead letter. A D5 retry must rebuild the probe from parameters that live only in the untrusted plan. The option also leaves open whether an episode is opened (seed m), and uses `probe_exhausted` where no probe ran. | CONF-043; D5 `:1421-1436`; `M19_recovery.py:512-548` |
| C-13 | When several revocations hold, the recorded reason is unpinned (IMP-M14-1). For a failing credential check the golden accepts either `authorization_revoked` or `credential_invalid` (IMP-M14-2). Both are rows with two possible endings. | IMP-M14-1, IMP-M14-2 |
| C-14 | The ledger key `request_id:plan_step_id` is the table's primary key across tenants, but `request_id` is unique only per tenant (`009:32`). Today every entry path generates it as a UUID (`s0_entry/handler.py:46`, `control_plane/api.py:148`), yet `EntryRequest.request_id` accepts a caller value. If one is ever passed through, two tenants can collide: the second tenant's store raises `IdempotencyConflict`. | §8 `:1612-1616`; `009:32`; `contracts/entry.py:20` |
| C-15 | A dead letter's `mutation_type` defaults to `R`, and `is_idempotent` is never written (IMP-M17-1). An operator reading the record may see the wrong operation class. | `015` (dead_letters); IMP-M17-1 |
