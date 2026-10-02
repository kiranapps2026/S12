# Phase 6: Owner rulings

Part of the [S12 truth model](README.md). It runs from phase 3 onward. It produces §15 (contradictions and open
rulings) and turns `ruling:` rows into `ruled` rows. Only the owner decides. This work prepares the decision and
applies its consequences to the matrix.

Revised in review pass 2 (`REVIEW_LOG.md` P2-6, P2-18): recorded proposals versus the pack, the full owner queue
(STOP and DEF rows included), the matrix checks C-12 and C-16, and the corrections to a circulated owner-approval
analysis.

Extended 2026-10-01 (pass 3): recommendations for C-12 and C-16 and their shared prerequisite C-11, with draft record
text, proposals to the test-author session, and the order in the overall process. See "Recommendations: C-12, C-16
and C-11".

## Purpose

Let the matrix finish while rulings stay open. Each open ruling gets both branches written as matrix consequences
(which rows change, and how), so the owner decides once, with the effects already worked out, and the document needs
no rework afterwards.

## Do not redo the ruling pack

`docs/gates/S12_RULING_PACK.md` (2026-10-01) already gives every open CONF both sides with `file:line` quotes, the
options and a recommendation, and covers DEF-003, STOP-004 and STOP-005. This phase adds only what the pack lacks:
the effect of each option on TM, RC, RO and IS rows. If the owner rules from the pack before phase 3 reaches a
ruling's rows, those rows are minted `ruled` and need no branches.

## How the records block work (read before deciding what is urgent)

| Record | What blocks | Source |
|---|---|---|
| CONF row with status `open` | The certifier row S12-REC fails for every milestone from the CONF's milestone onward | `tools/owner_certify_s12.py:141-154` (ruling pack `:13-19`) |
| STOP row with status `open` **or `ruled`** | Same: a STOP must reach `applied` | Same |
| DEF row | Not read by the certifier. The tracker refuses `reviewed` for a milestone with an open DEF | `tools/s12_tracker.py:71-74` |

## The owner queue at `c505af0`

Status is as recorded at `c505af0`; re-check `S12_RECORDS.md`, `S12_STOPS.md` and `S12_DEFECTS.md` before acting.
"Recorded proposal" is the text in the record's ruling column today. "Accept as proposed" means that text, which for
three rulings is **not** what the pack recommends.

### Truth-model rulings (CONF)

| Ruling | Blocks | Question | Recorded proposal | Pack recommendation | Same? | What the branches change in the matrix |
|---|---|---|---|---|---|---|
| CONF-005 | M15 → | Source of AutonomyLevel for verification-layer selection | Owner must name a source or drop autonomy | A: drop autonomy this phase; deferred register (`:71`) | — | A: required layers by mutation and risk only (as the M15 draft and CONF-041). B: CONFIRM_ALL adds the human layer, so every such step ends `dead_letter (human_verification_pending)` with the budget LOCKED (D4) |
| CONF-042 | M19 → | How the sweeper finds other tenants' orphaned runs under forced RLS | SECURITY DEFINER `s12_recovery_candidates(runtime_instance_id, limit)` | A, **with CONF-046's amendment**: signature `(runtime_instance_id, limit, orphan_after_s)`, `search_path` pinned with `pg_temp` last (`:105`) | No: the recorded signature lacks the grace and the hardening | Which runs reach the cold path at all; not step verdicts. Decides whether monitoring predicates (5a) may use the same pattern (C-7) |
| CONF-043 | M19 → | In-flight step of a plan whose digest no longer matches | Never probe; `dead_letter (probe_exhausted)`, LOCKED, PROBE dead letter with evidence `plan_integrity` | A, as recorded (`:137`) | Yes | A: every R3 = mismatch row with a step in flight → `pending_probe → dead_letter`, LOCKED, `unknown_unresolved`/PROBE. B: probe from the admitted step row; verdicts as for a matching digest. C: as A with a new A.2 reason `plan_integrity`. **This work recommends A′** (A with `retry_mode = NONE` and a recorded episode; see "Recommendations") because of C-12 |
| CONF-044 | M19 → | Are checkpoints written, and are they evidence? | Written as a hint, **not pinned** | **A+**: as A, plus one M19 assertion that they are written (`:167`) | No | Under every option checkpoints stay off the evidence ladder and change no verdict. A+ makes M20's tenant-isolation check on `checkpoints` non-vacuous |
| CONF-045 | M20 → | Lease renewal while a step runs | Renew; **"pinned when an owner assigns it"** (option C) | **A**: renew and pin it in M20 with two cases; reject C explicitly (`:199`) | No: the recorded proposal is the option the pack rejects | A: a long step keeps its lease; no mid-call takeover row. B: no renewal, long TTL; cold-path latency in 5b grows to minutes. C: unpinned concurrency code, and with the pinned M21 defaults (step timeout = lease TTL = 30 s) a mid-call takeover is reachable, so the fenced-out rows (principle 7) are live rows |
| CONF-046 | M19 → | When is a run orphaned? | Judge by the latest lease; one TTL grace; `search_path` pinned | A, as recorded (`:231`) | Yes | R1 values map to taken over / not taken over as listed in the pack. Sets the detection term of every cold-path latency in 5b. Leaves open: `EXECUTE` on the function is not revoked from `PUBLIC` (B5 review, "checked and left"), a deployment decision |
| CONF-047 | M19 → | NOT_EXECUTED found while the run is RECONCILING | `cancelled (not_executed_no_retry)`; consolidate in the same pass | A, as recorded (`:256`) | Yes | A: R4 = reconciling with a NOT_EXECUTED verdict → `pending → cancelled (not_executed_no_retry)`, never a retry. B: a new A.1 edge `reconciling → running` and a retry |
| CONF-048 (proposed, not recorded) | M19 → once recorded | Recovery must name `StepState.UNKNOWN` outside the allowed files | — | A: the in-flight set lives in `transitions.py` (`:454`) | — | D1 = `unknown` stays a never-written value either way. The rows that handle it defensively become `ruled` once it is recorded |

CONF-028, CONF-029 (M13), CONF-033–035 (M12) and CONF-036–041 (M15–M18) are ruled. Cite them as settled; never
reopen them here.

### Stops and defects in the same queue

| Record | Status | Blocks | Pack recommendation | Matrix relevance |
|---|---|---|---|---|
| STOP-001 | `ruled` (still blocks) | M1 → (S12-REC) | `applied`, with the owner's close-out (`S12_B3_PREFLIGHT.md`) | None |
| STOP-002 | open | M5 → | `applied` once B2 is pinned (`s12_pins.sha256` covers B1 only) | None |
| STOP-004 | open | M10 → | A: pin B3, then `applied` citing the pin commit (`:406`) | None. Its premise ("no M10 golden file") is stale, but the closing action is the pin, not a code check |
| STOP-005 | open | M10 → | A: `applied` (CONF-021..032 ruled in `150a668`) (`:426`). `150a668` also changed M8 code and the M08 golden after M8 was reached, so the owner's M8 checkpoint must re-prove M8 | None |
| DEF-002 | open (M12) | Tracker only | Close in M12 (IMP-M12-1) | Reason strings outside Appendix A: cosmetic findings in phase 4 |
| DEF-003 | open (S0–S11) | Tracker only | **B**: `wontfix` for this phase; RLS plus the superuser/BYPASSRLS refusal are the control; require the same refusal at the Worker Runtime entry point (pinned in M21); fix in the first post-S15 change-control batch with CONF-006 | Outside the truth model (confirmations precede S12). Bears on C-7 and CONF-042: every cross-tenant read relies on the same role guard |
| DEF-004 | open (M12) | Tracker only | Close in M12: `started` + `step_started` in one transaction (M12 draft) | Seed rule d; C-5 |

DEF-003 has three options, and the owner should see the cost of each, not a single recommendation:

| Option | What it does | Cost |
|---|---|---|
| A | Add `AND tenant_id = $n` to the four statements now, under §19.3 change control | The tag `s0-s11-certified` moves; the pinned `code_scan.py` and the certifier hard-code it; the owner re-verifies M1–M9 mid-batch |
| B (pack) | Defer; enforce the role guard at every entry point | The defense-in-depth gap stays open until after S15, guarded by two role checks |
| C | Reclassify `confirmations.py` as S12 code (CONF-011 list) so M5 must fix it | Edits a pinned file; sets a precedent for reclassifying any frozen file |

There is no option "revert the predicate": the predicate does not exist today.

## Checks this phase must run on the pack's recommendations

These are matrix consequences the pack does not discuss. Each goes into the branch write-up.

- **CONF-043 A, the dead letter's retry (C-12), and seed rule m.** Resolved by the recommendation A′ below.
  Background: a PROBE-mode dead letter is retried by calling the provider probe (D5), and the probe needs the step's
  parameters, which live only in the plan that failed its digest. The B5 review fixed the operation (read from
  `execution_steps`), not the parameters. Rule m (a `dead_letter` step's latest episode is closed EXHAUSTED) holds under
  A only if an episode is recorded, which neither the record nor the golden says. And the reason `probe_exhausted` is
  used where no probe ran.
- **CONF-045 B or C and §14.** Under B every cold-path figure in 5b changes; under C a mid-call takeover row is
  reachable. Compute both before the owner decides.
- **CONF-005 B and §13.** Under B, `human_verification_pending` becomes the most frequent dead letter for CONFIRM_ALL
  tenants, on top of C-16.
- **C-16 is not a ruling, but the owner should see it here.** By design (C32), every mutation on an adapter without
  `observe()` ends DEAD_LETTER with the budget LOCKED. With no production path to resolve dead letters (C-11), the
  question "should mutations run in production before real adapters exist?" is the owner's. Recommendation below.

## Recommendations: C-12, C-16 and C-11

These are this work's recommendations, not decisions. They change no gate text and no pinned file. Each option is
stated as an owner decision with its matrix effect, so it can be ruled in the same pass as the M19 rulings.

### C-16: refuse unverifiable mutations at enablement, not at the end of the run

**Recommendation.** Keep the gate's fail-closed rule unchanged. Move the refusal earlier: a W, D or IRREVERSIBLE
operation may be `PRODUCTION_ENABLED` only if its adapter really verifies it. Until real adapters exist, production
runs read operations only.

Why:
- The rule itself is right. C32 (`:1046-1050`) and FINAL_ARCHITECTURE §3 principle 8 make verification mandatory, and
  it is certified spec. What is wrong is *when* the system says no. Today a mutation runs, its budget is LOCKED, and
  only then does the system find it cannot verify the result. The step dead-letters and the money stays held (C-11).
  Refusing at enablement gives the same safety without charging anyone.
- The enablement check already half exists. `tools/registry_readiness.py` blocks a production-enabled mutation whose
  catalog entry has no `observation_method`. It checks the **catalog**, though, not the **adapter**. An operation can
  declare an observation method while its adapter still inherits `BaseAdapter.observe()`, which returns UNKNOWN. That
  combination is C-16 exactly.
- The real adapters are already specified with both paths. `batch_bundles/LAYER_A/ADAPTER_SPECS` (standard, GHL CRM,
  Gmail) define `probe()` per operation (§3) and `observe()` per observation method (§4), with conformance cases.

What it takes:

| Item | Where | Pinned file touched? |
|---|---|---|
| Extend the readiness rule: a production-enabled mutation is BLOCKED unless the adapter bound to it overrides both `observe()` and `probe()` | `tools/registry_readiness.py` (or a sibling check) | No |
| The same check when a Worker Runtime starts: refuse to start (not to run) when a production-enabled mutation is bound to an adapter that does not override `observe()` and `probe()` | Runtime start-up, M21 (alongside the superuser/BYPASSRLS refusal DEF-003 option B needs) | No; one M21 golden case if the owner wants it pinned |
| Production read-only until 2c: mutations run in test tenants with the mock only | Catalog and `truth_state` (owner action) | No |
| Enable each mutation one at a time after its adapter's conformance cases pass | Roadmap 2c; owner action per operation | No |

Matrix effect: every row where D8 is W, D or IRREVERSIBLE and the adapter has no `observe()` becomes unreachable in
production (status `ruled` once decided). Phase 5b's most frequent ending ("every change I make gets stuck") moves from
"normal" to "cannot happen in production". Phase 7 adds the enablement rule to the shelf-life assumptions and lists
2c as the event that reopens those rows.

Alternatives, for the record:
- **Accept C-16 as is**: mutations run and dead-letter. Every successful mutation holds its budget with no release
  path (C-11). Not recommended.
- **Relax verification for adapters without `observe()`**: contradicts C32 and principle 8, needs a gate change and a
  re-pin, and breaks the safety claim. Not recommended.

Draft decision text (owner, for the deferred register and the certification report):
> Mutations (W, D, IRREVERSIBLE) are production-enabled only when their adapter implements `observe()` and `probe()`
> for that operation and its conformance cases pass. Until roadmap 2c, production runs read operations only. The
> readiness check and the Worker Runtime start-up check enforce this.

### C-12: CONF-043 option A′ (A with `retry_mode = NONE` and a recorded episode)

**Recommendation.** Accept CONF-043 option A with two amendments, applied to the M19 golden draft **before B5 is
pinned**.

1. **The dead letter's `retry_mode` is `NONE`, not `PROBE`.** A PROBE retry calls the provider probe with the step's
   parameters, and they exist only in the plan that failed its digest check. The Layer A specs confirm the probe uses
   "the step's params". Tampering also implies database write access, so `execution_steps` is not fully trusted either:
   that is the pack's own argument against option B. `NONE` means "leaves pending only through human resolution" (D5),
   which is the right owner for a suspected tampering incident. The schema already allows it (`015`,
   `retry_mode IN ('PROBE', 'VERIFY', 'NONE')`).
2. **Record the episode.** Open and close an EXECUTION episode in the same transaction as the step's move:
   `none → pending_probe (opened)`, then closed with outcome EXHAUSTED, `attempts = 0`, evidence
   `{"plan_integrity": true}`. Link it from the dead letter's `episode_id`. This is a legal A.7 path (an exhausted
   episode keeps status `pending_probe` and gets `closed_at`; no attempt is needed). Seed rule m then holds for every
   dead-letter step. The operator sees `attempts = 0` and `plan_integrity`, so the reason `probe_exhausted` (the only
   A.2 edge into `dead_letter`) can no longer be read as "the provider was asked three times". That avoids option C's
   change to Appendix A and its re-pin of the gate and B1.

Matrix effect: every RC row with R3 = mismatch and a step in flight → step `pending_probe → dead_letter
(probe_exhausted)`, budget LOCKED, dead letter `unknown_unresolved` / `NONE` / evidence `plan_integrity`, episode
EXECUTION EXHAUSTED with 0 attempts. Rows without a step in flight are unchanged (CONF-034: every PENDING step
`cancelled (run_dead_lettered)`, run DEAD_LETTER). Resolution is human only, and depends on C-11.

Draft ruling text for the CONF-043 row (owner):
> owner <date>: A as proposed, amended: the in-flight step's dead letter has `retry_mode = NONE` (no automated probe
> from an untrusted plan; human resolution only), and an EXECUTION episode is opened and closed with it (outcome
> EXHAUSTED, attempts 0, evidence `plan_integrity`, linked by `episode_id`). Golden M19 amended before the B5 pin.

Proposal to the test-author session (this work never edits `tests_golden/`):

| File | Change |
|---|---|
| `tests_golden/s12/M19_recovery.py:540-541` (`test_the_in_flight_step_of_a_tampered_plan_is_dead_lettered_never_probed`) | Expect `retry_mode == "NONE"` instead of `"PROBE"`; add: exactly one EXECUTION episode for the step, outcome EXHAUSTED, `attempts == 0`, `closed_at` set, and the dead letter's `episode_id` equal to it |
| `tests_golden/s12/M19_recovery.py` (new case, C-10) | Crash at `after_verification_before_step_commit` with a FAIL recorded: recovery must not re-run the failed layer. The expected ending (step `failed (verification_failed)`, budget released, `data` dead letter, as §8 step 9) is itself an owner decision, because §13 as written opens a VERIFICATION episode. Record it as a CONF row first |
| One sabotage patch | A recovery that writes `PROBE` for a `plan_integrity` dead letter |

### C-11, the prerequisite for both: an operator path for dead letters

Both recommendations end in "a human resolves it", and today nothing in production can (IMP-M17-2). The dead-letter
adapter interface is fixed by the M17 golden draft (`resolve`, `start_retry`, `abandon`, `retry_dead_letter`); only an
entry point and its authorization are missing.

**Recommendation.** Record a new CONF row (proposed number CONF-049; the session with write rights assigns the
number) and assign a minimal operator path to M21, pinned by golden cases:

| Capability | Behaviour |
|---|---|
| List | A tenant's open dead letters (`pending`, `retrying`) with error type, retry mode, evidence and the held amount; tenant-scoped under RLS |
| Resolve | Set the outcome (EXECUTED, NOT_EXECUTED, UNDETERMINED); settles a LOCKED reservation per C21; never changes the run or the step (D4) |
| Retry | Start a retry for PROBE or VERIFY records only (D5); refused for NONE, which covers the C-12 dead letters |
| Authorization | An admin role of the dead letter's tenant only, audited like the other admin API actions (Phase B4 admin API) |

Draft CONF row (proposed):
> CONF-049 | M21 | open | §11 and D5 define dead-letter retry and resolution, and the M17 draft fixes their adapter
> interface, but no milestone builds an entry point (IMP-M17-2; B4 review "known gaps": "an operator entry point is
> M21", not pinned). A LOCKED reservation therefore has no release path in production and counts against
> `budget_pool` (I1) | proposal: an admin API to list, resolve and retry dead letters, tenant-scoped, audited, pinned in
> M21 by golden cases (list under RLS; resolve settles LOCKED per C21 and moves neither run nor step; retry refused for
> NONE)

**If the owner does not assign it before certification:** the S12–S15 certification report states "LOCKED money has
no release path" as a known limitation, and production stays read-only. The C-16 recommendation already gives that
state.

### Order in the overall process

| When | Action | Who | Cost |
|---|---|---|---|
| Now, before the B5 pin | Amend the M19 draft for C-12; add the C-10 case once its CONF row is ruled; one sabotage patch | Test-author session, from this proposal | Edits to unpinned drafts only |
| Owner ruling pass (the M19 rulings) | Rule CONF-043 as A′; record and rule CONF-049; decide the expected ending for C-10; take the C-16 decision | Owner | One pass, one document |
| M21 | Build and pin the operator path (CONF-049); add the Worker Runtime start-up check (C-16) beside the DEF-003 role check | Implementation session | Small, already-shaped work |
| Before certification | Extend `tools/registry_readiness.py` to check the adapter, not only the catalog | Implementation session | A tool change, no pinned file |
| Certification | Report scope: mutations not production-enabled until a verifiable adapter exists; CONF-049 delivered or listed as a limitation | Owner | One section of the report |
| Roadmap 2c | Enable mutations one operation at a time after their adapter's conformance cases pass (Layer A first) | Owner, per operation | One decision per operation |

## Corrections to the circulated owner-approval analysis

A separate analysis of "open items requiring owner approval" circulated on 2026-10-01. Checked against the records at
`c505af0`, it is wrong in these places. Do not act on it without these corrections.

| Item | The analysis said | The records say |
|---|---|---|
| CONF-005 | Resolved; "no owner approval needed" | Open; blocks M15 onward |
| CONF-033, 034, 035 | Open | Ruled (`4ba83bf`) |
| CONF-040 | Open; "run semantic only" | Ruled; after a probe the layers that run are provider_state, semantic and human |
| CONF-044 | "Do not pin" | That is the recorded proposal; the pack recommends A+ (pin one assertion) |
| CONF-045 | "Pin when assigned"; add `lease_renewal_interval_s` | That is option C, which the pack rejects; the setting already exists (`settings.py`, `S12_LEASE_RENEWAL_INTERVAL_S`) |
| CONF-044, 045 | Under "not requiring owner approval" | Open CONF rows; the certifier blocks M19/M20 until ruled |
| CONF-046, 047, proposed 048 | Missing | Open (048 not yet recorded); block M19 |
| STOP-005, STOP-001 | Missing | STOP-005 open, STOP-001 `ruled`; both block |
| DEF-002, DEF-004 | Missing | Open (M12) |
| STOP-004 | Stale because "all 64 M10 cases [are] green on reference" | The reference is the unreviewed code in `batch_bundles/`; nothing from M10 is implemented on `s12-work`. Close it by pinning B3 |
| STOP-002 | "Confirm M05 is pinned" | B2 is not pinned; pinning is the action |
| DEF-003 | Option (b) "revert the predicate" | There is no predicate to revert; the options are A, B and C above |
| S12-REC-002/003/004 | Record IDs | No such records; the records use CONF, STOP and DEF numbers |

Correct in that analysis: CONF-042 (SECURITY DEFINER, ids only, `search_path` hardened) and CONF-043 (dead-letter,
never probe) match the pack.

## Branch write-up format (`work/P6_BRANCHES.md`, one section per ruling)

| Field | Content |
|---|---|
| ruling | ID, question, link to the pack section |
| recorded vs pack | Whether "accept as proposed" equals the pack's recommendation |
| what would decide it | The fact or preference that settles it (for example "accept minutes of recovery latency?") |
| branch A, B, … | For each: rows added, rows retired, rows whose verdict, episode, budget or dead-letter cell changes (TM/RC/RO/IS IDs with before → after) |
| findings | TF entries that each branch opens or closes |
| recommendation | The pack's, plus anything the matrix adds |
| ruled | Date, owner's words, record status |

## Procedure

1. From phase 3 onward, write the branch section as soon as a ruling's rows are mapped.
2. Hand the owner one document, `work/P6_BRANCHES.md`, ordered by the milestone each item blocks: M1/M5/M10 (the
   STOP close-outs, which need only the pins), M15 (005), M19 (042, 043 as A′, 044, 046, 047, 048, and the C-10
   ending), M20 (045), M21 (CONF-049), then DEF-003 and C-16.
3. When the owner rules, they record it themselves (the pack's "How to apply"). This work then applies the chosen
   branch to the matrix, retires the other branch's rows in `tm_ids.json` (never deletes them), changes the affected
   tags from `unknown` or `proposed` to `ruled`, and logs it in the decision log.

## Exit criteria

- Every ruling in the open set has a branch section, or a recorded ruling.
- Every recorded ruling is applied to the matrix; no row is still tagged `ruling:<CONF>` for a ruled CONF.
- Each of C-12, C-16 and C-11 (CONF-049) has the owner's answer, or a TF entry carrying it as open.
- The M19 draft amendment (C-12) and the C-10 case are either in the B5 drafts before the pin, or recorded as
  open with the owner's reason.
- The owner was interrupted once, with one document.

## Can it split?

No. Owner only for the decision. The branch write-ups can be drafted by whoever owns the affected milestone column.
