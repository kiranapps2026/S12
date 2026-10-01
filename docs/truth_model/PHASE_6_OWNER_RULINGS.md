# Phase 6: Owner rulings

Part of the [S12 truth model](README.md). It runs from phase 3 onward. It produces §15 (contradictions and open
rulings) and turns `ruling:` rows into `ruled` rows. Only the owner decides. This work prepares the decision and
applies its consequences to the matrix.

## Purpose

Let the matrix finish while rulings stay open. Each open ruling gets both branches written as matrix consequences
(which rows change, and how), so the owner decides once, with the effects already worked out, and the document needs
no rework afterwards.

## Do not redo the ruling pack

`docs/gates/S12_RULING_PACK.md` (2026-10-01) already gives every open CONF both sides with `file:line` quotes, the
options and a recommendation. This phase adds only what the pack lacks: the effect of each option on TM, RC and IS
rows. If the owner rules from the pack before phase 3 reaches a ruling's rows, those rows are minted `ruled` and need
no branches.

## The open set (corrected: CONF-040 is ruled; 042 and 045 were missing; 048 is proposed)

| Ruling | Question | Lands in | Pack recommendation | What the branches change in the matrix |
|---|---|---|---|---|
| CONF-005 | Source of AutonomyLevel for verification-layer selection | §6, D5 required set | A: drop autonomy this phase (`:71`) | A: required layers by mutation and risk only (as the M15 draft and CONF-041). B: CONFIRM_ALL adds the human layer, so every such step ends `dead_letter (human_verification_pending)` with the budget LOCKED (D4) |
| CONF-042 | How the sweeper finds other tenants' orphaned runs under forced RLS | §7, R1; 5a role (C-7) | A: one SECURITY DEFINER discovery function, ids only (`:105`) | Which runs reach the cold path at all. Does not change step verdicts. Decides whether monitoring predicates can use the same pattern |
| CONF-043 | In-flight step of a plan whose digest no longer matches | §7, R3 | A: never probe; PROBE dead letter for an operator (`:137`) | A: every R3 = mismatch row → `pending_probe → dead_letter (probe_exhausted)`, budget LOCKED, dead letter `unknown_unresolved`/PROBE with evidence `plan_integrity`. B: probe from the admitted step row; verdicts as for a matching digest. C: as A, but with a new A.2 reason `plan_integrity` |
| CONF-044 | Are checkpoints evidence? | §2 ladder | A+: written as a hint, one golden assertion, never read by recovery (`:167`) | A/A+: checkpoints stay off the ladder, and no dimension is added. B: no checkpoint rows; only §8 deviates. Under no option do checkpoints change a verdict |
| CONF-045 | Lease renewal while a step runs | Assumptions (phase 7); R1 | A: renew, pinned in M20 (`:199`) | A: a long step keeps its lease, so no mid-call takeover row. B: no renewal, long TTL; recovery latency in 5b grows to minutes. C (rejected in the pack): a takeover mid-call is reachable, so the fenced-out rows (principle 7) become live rows |
| CONF-046 | When is a run orphaned? | §7, R1 | A: by its latest lease, one TTL grace (`:231`) | R1 values map to "taken over / not taken over" as listed in the pack. Sets the detection term of every cold-path latency in 5b |
| CONF-047 | NOT_EXECUTED found while the run is RECONCILING | §7, §9, R4 | A: cancel `not_executed_no_retry` (`:256`) | A: R4 = reconciling with a NOT_EXECUTED verdict → `pending → cancelled (not_executed_no_retry)`, never a retry. B: a new A.1 edge `reconciling → running` and a retry |
| CONF-048 (proposed) | Recovery must name `StepState.UNKNOWN` outside the allowed files | D1 = `unknown` rows | A: the in-flight set lives in `transitions.py` (`:454`) | D1 = `unknown` stays a never-written value either way. The rows that handle it defensively are `ruled` once it is recorded |

CONF-028 and CONF-029 (M13) and CONF-040 (M15) are ruled. Cite them as settled; never reopen them here.

## Checks this phase must run on the pack's recommendations

These are matrix consequences the pack does not discuss. Each goes into the branch write-up.

- **CONF-043 A and seed rule m.** Under A, a tampered plan's step reaches `dead_letter` without a probe. Seed rule m
  (a `dead_letter` step's latest episode is closed EXHAUSTED) then holds only if A opens and closes an episode. If A
  opens none, rule m needs an exception, and principle 5 flags the reason `probe_exhausted` used where no probe ran
  (the pack calls it "a slight misnomer"; the matrix grades it cosmetic or loud).
- **CONF-045 B and §14.** Under B, every cold-path figure in phase 5b changes. Compute both before the owner decides.
- **CONF-005 B and §13.** Under B, `human_verification_pending` becomes the most frequent dead letter for CONFIRM_ALL
  tenants. Phase 5b's "waiting on a human" row grows from a product gap into a volume problem.

## Branch write-up format (`work/P6_BRANCHES.md`, one section per ruling)

| Field | Content |
|---|---|
| ruling | ID, question, link to the pack section |
| what would decide it | The fact or preference that settles it (for example "accept minutes of recovery latency?") |
| branch A, B, … | For each: rows added, rows retired, rows whose verdict, episode, budget or dead-letter cell changes (TM/RC/IS IDs with before → after) |
| findings | TF entries that each branch opens or closes |
| recommendation | The pack's, plus anything the matrix adds |
| ruled | Date, owner's words, `S12_RECORDS.md` row status |

## Procedure

1. From phase 3 onward, write the branch section as soon as a ruling's rows are mapped.
2. Hand the owner one document: `work/P6_BRANCHES.md`, ordered by the milestone it blocks (M15: 005; M19: 042,
   043, 044, 046, 047, 048; M20: 045).
3. When the owner rules, they record it in `S12_RECORDS.md` themselves (the pack's "How to apply"). This work then:
   applies the chosen branch to the matrix, retires the other branch's rows in `tm_ids.json` (never deletes them),
   changes the affected tags from `unknown` or `proposed` to `ruled`, and logs it in the decision log.

## Exit criteria

- Every ruling in the open set has a branch section, or a recorded ruling.
- Every recorded ruling is applied to the matrix; no row is still tagged `ruling:<CONF>` for a ruled CONF.
- The owner was interrupted once, with one document.

## Can it split?

No. Owner only for the decision. The branch write-ups can be drafted by whoever owns the affected milestone column.
