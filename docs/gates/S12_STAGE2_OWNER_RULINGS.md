# S12 Stage 2: owner ruling document

Prepared 2026-10-02 against `s12-work` at `f76a7f4` (after the restore merge). **This is not a record.** The records
of truth stay `S12_RECORDS.md`, `S12_STOPS.md` and `S12_DEFECTS.md`; a ruling counts only when the owner writes it into
the row (Part F). Sources: `S12_RULING_PACK.md` (both sides and file:line evidence for every open CONF),
`docs/truth_model/PHASE_6_OWNER_RULINGS.md` (matrix consequences, C-10/C-11/C-12/C-16), and the review of the force-push
recovery (2026-10-02).

Use it in order: Part A (time plan), Part B (safety rules), then decide Parts C–E, apply with Part F, hand off with
Part G.

---

## Part A: owner time plan

Three sittings. Times are estimates for reading and deciding; the long test runs are unattended.

| Sitting | Prerequisite | Owner work | Estimate | Unattended |
|---|---|---|---|---|
| **1. Protect and pin** | The 8 golden fixes pushed; full golden suite 877/877 on unedited golden files (`git diff f76a7f4 -- tests_golden/` shows only the two reverts) | Branch protection on `s12-work` (block force-push and deletion). Restore `tools/owner_pin_s12.ps1` to the owner version. Review the B2 and B3 golden diffs since the last pin, then pin (`tools\owner_pin_s12.ps1`). Close the STOPs (Part C) | 45–75 min | `owner_certify_s12.py --milestone M1` … `M14` in full mode (sabotage, 5× concurrency): start it and leave it |
| **2. Ruling pass** | Sitting 1 done; certifier results for M1–M14 recorded in `s12_autopilot_log.md` | Decide Part D (13 decisions) and Part E (3 amendments). Paste the row texts (Part F). One commit, records only | 60–90 min | `doc_consistency.py`, `s12_tracker.py check`, `owner_certify_s12.py --milestone M14 --fast` |
| **3. Approve the golden amendments** | Test-author session has drafted the B4/B5 amendments of Part G, red-first | Review the amended drafts against the rulings; pin B4 and B5 only after the implementation passes them | 30–45 min | Full certifier M15 … M21 |

Do not merge sittings 1 and 2: the rulings in sitting 2 rely on M1–M14 being certified first, so that a ruling never
covers a defect the certifier would have caught.

---

## Part B: rules for implementing safely

1. **Rule first, then golden, then code.** A behaviour change starts as a ruled record, becomes a red golden case
   (test-author session), and only then becomes code (implementation session). Never the other way round.
2. **The implementation session never edits `tests_golden/`, `tools/owner_*`, pins or the records' ruling columns.**
   A test that seems wrong is a STOP row, not an edit.
3. **One ruling pass = one commit touching only `docs/gates/S12_RECORDS.md`, `S12_STOPS.md`, `S12_DEFECTS.md`.** Easy
   to review, easy to revert.
4. **Pin only after reviewing the golden diff since the last pin**, and only the batch you reviewed.
5. **Certify in full mode** (golden, sabotage, 5× concurrency) before any milestone is marked green. `--fast` is for
   checking, never for marking.
6. **Never force-push.** Restore and fix by merge or revert. Keep branch protection on.
7. **Security findings take the safer option** (fail closed), even when it costs a feature in this phase.
8. **Records stay tables.** The certifier reads only `| CONF-nnn |` and `| STOP-nnn |` rows; any other format hides
   open items from it.
9. **Every ruling names its follow-on work** (golden file, milestone, register line), so nothing ruled is left
   unimplemented (the CONF-020 lesson).

---

## Part C: close-outs (sitting 1, after the pins)

The certifier blocks while a STOP is `open` **or `ruled`**; DEF rows block only the tracker's `reviewed`.

| Record | Now | Action | Row text (Status → Ruling / Applied) |
|---|---|---|---|
| STOP-001 | ruled | `applied` | `applied <date>: golden set pinned (<pin commit>)` |
| STOP-002 | open | `applied` after the B2 pin | `applied <date>: B2 golden files present and pinned (<pin commit>)` |
| STOP-004 | open | `applied` after the B3 pin | `owner <date>: B3 drafted and reviewed as proposed; pinned` / `<pin commit>` |
| STOP-005 | open | `applied` | `owner 2026-09-30: CONF-021..032 accepted (150a668)` / `150a668`, `<pin commit>` |
| DEF-002 | open | Verify, then `fixed`: the M12 loop logs only Appendix A reasons (invariant I5 passes in every golden run) | `fixed <date>: loop rewritten in M12; I5 green (<commit>)` |
| DEF-004 | open | Verify, then `fixed`: `loop.py:319-320` moves the step to RUNNING and the reservation to LOCKED in one `set_step` (I-3) | `fixed <date>: one transaction, loop.py:319-320 (<commit>)` |
| DEF-003 | open | Decide in Part D (D-13) | — |

---

## Part D: decisions

### D-0: summary

| # | Record | Blocks | Recommendation | If decided wrong |
|---|---|---|---|---|
| D-1 | CONF-005 | M15 | A: no autonomy source this phase | B: every CONFIRM_ALL step dead-letters (human layer is UNKNOWN) |
| D-2 | CONF-042 | M19 | A with CONF-046's amendment | A wider role (B) puts the most powerful credential in every runtime |
| D-3 | CONF-043 | M19 | **A′** (A + `retry_mode = NONE` + recorded episode) | Plain A lets an operator retry probe a tampered plan's parameters |
| D-4 | CONF-044 | M19 | A+ (one pinned checkpoint assertion) | A leaves an unpinned write path and a vacuous M20 check |
| D-5 | CONF-045 | M20 | A: renew, pinned in M20 | C (the recorded proposal) is unpinned concurrency code; mid-call takeovers |
| D-6 | CONF-046 | M19 | A | Needless takeovers of live runs; nondeterministic M20 |
| D-7 | CONF-047 | M19 | A | B needs a gate change for a state nothing produces |
| D-8 | CONF-048 (record) | M19 | A: in-flight set lives in `transitions.py` | B edits a pinned B1 file |
| D-9 | CONF-049 (record) | M21 | Operator path for dead letters, pinned in M21 | LOCKED money has no release path in production |
| D-10 | CONF-050 (record) | M19 | A recorded FAIL ends the step FAILED after a crash | A non-retryable FAIL can flip to PASS |
| D-11 | CONF-051 (record) | M11 | Composite ledger key, migration 018 fixed | Cross-tenant key collision stops the second tenant |
| D-12 | CONF-052 (record) | Certification | Mutations production-enabled only with a verifying adapter | Every successful mutation dead-letters and holds money |
| D-13 | DEF-003 | — (tracker) | B: defer, role guard at every entry point | A moves the S0–S11 tag mid-batch |

Proposed record numbers 048–052 are assigned in this order when recorded; if a number is taken, use the next free one
and keep the order.

### D-1 CONF-005: no AutonomyLevel source for verification-layer selection (blocks M15)

- **Question.** Gate D6 says STOP if there is no AutonomyLevel source; there is none in code.
- **Recommendation: A.** Layer selection by mutation and risk only in this phase (as CONF-041 already assumes and
  golden M15 pins). Deferred register: "autonomy source: post-S15".
- **Why.** Option B builds a source whose only effect in this phase is to dead-letter every CONFIRM_ALL tenant's
  steps, because the human layer always returns UNKNOWN (D4).
- **Follow-on.** Deferred-register line; certification report sentence.
- **Row text.** `ruled <date> (owner): option A; no AutonomyLevel source in this phase; required_verification_layers(mutation, risk); register: autonomy source post-S15`

### D-2 CONF-042: sweeper discovery under forced RLS (blocks M19)

- **Recommendation: A, as amended by CONF-046**: one `SECURITY DEFINER` function
  `s12_recovery_candidates(runtime_instance_id, limit, orphan_after_s)`, ids only, writes nothing, `search_path`
  pinned with `pg_temp` last, the only such function in the schema.
- **Why.** The alternatives are a BYPASSRLS role in every runtime (B) or a second source of truth on the hottest path
  (C).
- **Follow-on.** Deployment decision recorded with it: revoke `EXECUTE` from `PUBLIC` and grant it to the runtime role
  at deployment (the migration cannot know the role name).
- **Row text.** `ruled <date> (owner): option A with CONF-046's signature (runtime_instance_id, limit, orphan_after_s); search_path pinned, pg_temp last; deployment revokes EXECUTE from PUBLIC`

### D-3 CONF-043: the in-flight step of a tampered plan (blocks M19)

- **Recommendation: A′** (truth model C-12).
  1. The dead letter has `retry_mode = NONE`, not PROBE: a probe retry would rebuild the call from the plan that failed
     its digest check, and tampering implies database write access, so a human resolves it.
  2. An EXECUTION episode is opened and closed with the step's move: outcome EXHAUSTED, `attempts = 0`, evidence
     `plan_integrity`, linked by the dead letter's `episode_id`. Every dead-letter step then has a closed episode, and
     an operator sees that no probe ran despite the reason `probe_exhausted` (the only Appendix A.2 edge; changing it
     would re-pin the gate and B1).
- **Follow-on.** M19 golden amendment (Part G), before B5 is pinned.
- **Row text.** `ruled <date> (owner): A as proposed, amended: retry_mode NONE (no automated probe from an untrusted plan; human resolution only); an EXECUTION episode is opened and closed with it (outcome EXHAUSTED, attempts 0, evidence plan_integrity, linked by episode_id); golden M19 amended before the B5 pin`

### D-4 CONF-044: checkpoints (blocks M19)

- **Recommendation: A+.** Written at §8 steps 7 and 11 through `fenced_write` as a hint; recovery never reads them;
  one M19 assertion that a completed run has increasing sequences and the last row lists every step.
- **Why.** Without the assertion, the write path is unpinned and M20's tenant-isolation check on `checkpoints` passes
  even if no row is ever written.
- **Row text.** `ruled <date> (owner): option A+; checkpoint rows are a hint written at §8 steps 7 and 11; recovery never reads them; one M19 assertion pins that they are written`

### D-5 CONF-045: lease renewal during a step (blocks M20)

- **Note.** The recorded proposal is option C ("pinned when an owner assigns it"), which the pack rejects. Accepting
  "as proposed" would choose C.
- **Recommendation: A.** The loop renews every `lease_renewal_interval_s` while a step runs; `LeaseLost` stops the step
  like `FencedOut`; two M20 cases: a step longer than the TTL completes with no takeover and strictly increasing
  tokens; a refused renewal writes nothing further and discards the result.
- **Why.** The pinned M21 defaults set step timeout = lease TTL = 30 s, so without renewal a step can be taken over
  mid-call. This is also the likely cause of the M20 instability (IMP-X7), which a timing workaround would only hide.
- **Row text.** `ruled <date> (owner): option A (not C); renewal every lease_renewal_interval_s during a step; LeaseLost stops the step like FencedOut; pinned by two M20 cases before the B5 pin`

### D-6 CONF-046: when is a run orphaned (blocks M19)

- **Recommendation: A** as recorded: judged by the latest lease; active and unexpired never; lapsed or expired at
  once; released one TTL after release; never leased one TTL after the ownership row.
- **Row text.** `ruled <date> (owner): accepted as proposed (option A)`

### D-7 CONF-047: NOT_EXECUTED in a RECONCILING run (blocks M19)

- **Recommendation: A** as recorded: the step ends `cancelled (not_executed_no_retry)`, the run is consolidated in the
  same pass.
- **Row text.** `ruled <date> (owner): accepted as proposed (option A)`

### D-8 CONF-048 (new record): recovery must name `StepState.UNKNOWN`

- **Record first** (copy the "Proposed CONF-048" section of `S12_RULING_PACK.md` into a row), then rule.
- **Recommendation: A.** The in-flight set (`IN_FLIGHT_STEP_STATES`) lives in `transitions.py`, which may name
  UNKNOWN; recovery imports it. Aliasing to evade the M03 scan is forbidden.
- **Row text.** `ruled <date> (owner): option A; the in-flight set is defined in transitions.py and imported by recovery; no aliasing around the M03 scan`

### D-9 CONF-049 (new record): operator path for dead letters (blocks certification of M21)

- **Question.** §11 and D5 define dead-letter retry and resolution, and the M17 draft fixes the adapter interface,
  but no milestone builds an entry point. A LOCKED reservation has no release path in production and counts against
  `budget_pool` (I1).
- **Recommendation.** An admin API to list, resolve and retry dead letters, assigned to M21:
  list a tenant's open dead letters under RLS; resolve with EXECUTED / NOT_EXECUTED / UNDETERMINED (settles a LOCKED
  reservation per C21; moves neither run nor step, D4); retry only PROBE / VERIFY records (refused for NONE); tenant
  admin role only; audited like the other admin actions.
- **If not assigned before certification:** the certification report states "LOCKED money has no release path", and
  production stays read-only (D-12 gives that state).
- **Row text.** `ruled <date> (owner): admin API for dead letters (list, resolve, retry PROBE/VERIFY only), tenant admin role, audited; assigned to M21; pinned by M21 golden cases before the B5 pin`

### D-10 CONF-050 (new record): a recorded FAIL during recovery

- **Question.** At `after_verification_before_step_commit` with a FAIL recorded, §13 opens a VERIFICATION episode
  ("not recorded as PASS") and C19 re-runs the failed layer; §8 step 9 says FAIL is not retryable. No golden case.
- **Recommendation.** §8 step 9 wins: recovery finds any recorded FAIL → the open VERIFICATION episode (if any) closes
  `confirmed_failure (verified_fail)`, step `failed (verification_failed)`, budget released (`step_failed`), dead
  letter `data` / NONE. The latest verdict per layer decides (CONF-036).
- **Follow-on.** One M19 case, with and without an open episode (Part G).
- **Row text.** `ruled <date> (owner): §8 step 9 wins over §13 for a recorded FAIL: episode closed verified_fail if open, step failed (verification_failed), budget released, data dead letter; pinned by an M19 case before the B5 pin`

### D-11 CONF-051 (new record): composite idempotency-ledger key

- **Question.** Gate §8 makes `idempotency_key` the ledger's primary key; the key `request_id:plan_step_id` is unique
  only per tenant. Migration 018 (implementation) made the key `(tenant_id, idempotency_key)`, and golden M11 was edited
  to accept it.
- **Recommendation.** Accept the composite key **with conditions**: (1) remove the `BEGIN`/`COMMIT` from
  `018_idempotency_composite_pk.sql` (every other migration relies on the migrator's single transaction); (2) the
  M11 golden change is re-made by the test-author session against this ruling, not kept from the implementation
  session's edit; (3) a same-tenant row with another `kernel_op_id` still raises `IdempotencyConflict`.
- **Why.** `request_id` is a server UUID today, so the risk is latent; the composite key removes it for good and
  matches RLS tenancy.
- **Row text.** `ruled <date> (owner): ledger key (tenant_id, idempotency_key); migration 018 without BEGIN/COMMIT; M11 golden amended by the test-author session; same-tenant foreign kernel_op_id still raises IdempotencyConflict`

### D-12 CONF-052 (new record): production enablement of mutations

- **Question.** By design (C32), an adapter without `observe()` makes provider_state verification UNKNOWN, so every
  W/D/IRREVERSIBLE step on it ends DEAD_LETTER with its money LOCKED, even when the call succeeded. With no release
  path (D-9), every such mutation holds money indefinitely.
- **Recommendation.** Keep C32 unchanged; refuse unverifiable mutations at enablement:
  1. `tools/registry_readiness.py` blocks a `PRODUCTION_ENABLED` mutation unless its adapter overrides `observe()` and
     `probe()`, not only when the catalog names an observation method;
  2. the Worker Runtime refuses to start with such a binding (M21, next to DEF-003's role check);
  3. production runs read operations only until real adapters (roadmap 2c, Layer A specs) pass their conformance
     cases; each mutation is then enabled one operation at a time by the owner.
- **Row text.** `ruled <date> (owner): C32 unchanged; mutations PRODUCTION_ENABLED only with an adapter implementing observe() and probe() for the operation; readiness tool and runtime start-up enforce it; production read-only for mutations until roadmap 2c`

### D-13 DEF-003: frozen confirmation store without a `tenant_id` predicate

| Option | Effect | Cost |
|---|---|---|
| A | Add the predicate now under §19.3 change control | The `s0-s11-certified` tag moves; M1–M9 re-verified mid-batch |
| **B (recommended)** | `wontfix` this phase; RLS plus the superuser/BYPASSRLS refusal are the control; the same refusal is required at every Worker Runtime entry point (pinned in M21); predicate added in the first post-S15 change-control batch with CONF-006 | The defense-in-depth gap stays open until after S15, guarded by two role checks |
| C | Reclassify `confirmations.py` as S12 code | Edits a pinned file; precedent for reclassifying frozen files |

- **Row text (B).** Status `wontfix`; `owner <date>: RLS + NOSUPERUSER/NOBYPASSRLS role guard are the control in this phase; Worker Runtime entry must refuse superuser/BYPASSRLS (M21); predicate added in the first post-S15 S0–S11 change-control batch with CONF-006`

---

## Part E: amendments to rulings that are recorded but not implementable as written

| Record | Problem | Recommendation | Text to append to the Ruling column |
|---|---|---|---|
| CONF-008 | Ruled "goes into the deferred register", but no register line was ever written | A: keep fail-closed; write the register line and an operator rule | `deferred-register entry written <commit>; operator rule: a catalog version bump denies plans awaiting confirmation; bump when none are pending` |
| CONF-020 | M18 never sees an entry DENY (no run), and no M18 case pins `quota_exhausted` | A: S15 maps entry denials through `entry_denial_envelope(outcome)`; `quota_exhausted` → error type `budget_exceeded` with the upgrade text (soft adds `retry_after_ms`); 2–3 M18 cases before the B4 pin | `amended <date> (owner): entry denials are mapped by S15 entry_denial_envelope (M18), quota_exhausted → budget_exceeded with upgrade text; pinned by M18 quota cases` |
| CONF-027 | The real admission snapshot and pre-flight sources were never assigned; every golden injects them | A: assign to M21 (`PostgresAdmissionSnapshot`, `PostgresPreflight`), amend M21 before the B5 pin; otherwise the certification report must say the loop is not production-wired | `assigned <date> (owner): M21; PostgresAdmissionSnapshot and PostgresPreflight; one journey with real sources plus one case per DB-backed gate` |

---

## Part F: how to apply

1. Edit the rows in `docs/gates/S12_RECORDS.md`, `S12_STOPS.md`, `S12_DEFECTS.md`. The certifier reads the **third
   column** (Status): CONF `open` → `ruled`; STOP `open`/`ruled` → `applied`; DEF `open` → `fixed` or `wontfix`.
   Paste the row text into the ruling column. New records (048–052) are new table rows, status `ruled`, opened today.
2. One commit, records only: `s12: owner rulings <date>: CONF-005, 042–052, DEF-002/003/004; STOP-001/002/004/005 applied`.
3. Check, in this order:
   ```
   python tools/doc_consistency.py
   python tools/s12_tracker.py check
   python tools/owner_certify_s12.py --milestone M14 --fast      # S12-REC must PASS
   python tools/owner_certify_s12.py --milestone M21 --fast      # S12-REC must list nothing up to M21
   ```
4. Push normally. Never `--force`.

---

## Part G: hand-off after the rulings

**Test-author session (golden amendments, red-first, before the B4/B5 pins):**

| File | Change | From |
|---|---|---|
| `M19_recovery.py:540-541` | Tampered-plan dead letter: `retry_mode == "NONE"`; one EXECUTION episode, outcome EXHAUSTED, `attempts == 0`, linked by `episode_id` | D-3 |
| `M19_recovery.py` (new) | Crash at `after_verification_before_step_commit` with a FAIL recorded, with and without an open episode | D-10 |
| `M19_recovery.py` | Checkpoint assertion | D-4 |
| `M20_multiprocess.py` | Two renewal cases | D-5 |
| `M18_response.py` | 2–3 `quota_exhausted` entry-denial cases | Part E, CONF-020 |
| `M21_journeys.py` | Operator endpoint cases; real admission and pre-flight sources; Worker Runtime role check; enablement check | D-9, Part E CONF-027, D-13, D-12 |
| `M11_idempotency_retry.py` | Composite key behaviour, re-made against the ruling | D-11 |
| Sabotage | A recovery that writes PROBE for a `plan_integrity` dead letter; a FAIL re-run after a crash; a dead-letter retry allowed for NONE | D-3, D-10, D-9 |

**Implementation session (after the amended cases are red):** implement D-3, D-4, D-5, D-9, D-10, D-11 (remove
`BEGIN`/`COMMIT`), D-12, D-13's role check, and the CONF-020 and CONF-027 amendments; then the code review of the
reference-derived `src/` (security review, fenced-write registry IMP-X2, redaction IMP-X5).

**Owner (sitting 3):** review the amended drafts, then pin B4 and B5 once the implementation passes them, and certify
M15 … M21 in full mode.
