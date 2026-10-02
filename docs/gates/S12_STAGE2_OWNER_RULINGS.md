# S12 Stage 2: owner ruling document

Prepared 2026-10-02 against `s12-work` at `f76a7f4` (after the restore merge); **revised the same day** after a
recheck against the owner tools (Part I lists what changed). **This is not a record.** The records of truth stay
`S12_RECORDS.md`, `S12_STOPS.md` and `S12_DEFECTS.md`; a ruling counts only when the owner writes it into the row
(Part F). Sources: `S12_RULING_PACK.md` (both sides and file:line evidence for every open CONF),
`docs/truth_model/PHASE_6_OWNER_RULINGS.md` (C-10/C-11/C-12/C-16), and the review of the force-push recovery.

Use it in order: Part A (pre-checks), Part B (time plan), Part C (safety rules), decide Parts D–E, apply with Part F,
hand off with Part G. Part H covers the owner scripts.

---

## Part A: pre-checks before the owner starts (implementation session, then verified by the owner)

Every line must hold. If one fails, stop and fix it first.

| # | Check | Command (repository root) | Expected |
|---|---|---|---|
| A-1 | Branch state | `git fetch origin; git status -sb; git log -1 --oneline` | On `s12-work`, nothing to commit, level with `origin/s12-work` |
| A-2 | Golden files equal the restored set, except M11 | `git diff f192b67 -- tests_golden` | **Empty**, except `tests_golden/s12/M11_idempotency_retry.py` (pending D-11). Today M01, M10 and M12 also differ: restore them with `git checkout f192b67 -- tests_golden/s12/M01_schema.py tests_golden/s12/M10_guard.py tests_golden/s12/M12_loop.py` (this also removes the four helpers the merge left defined twice in `M12_loop.py`: `_snapshot`, `_take_over`, `_force_plan_update`, `_retamper`) |
| A-3 | Golden suite | `pytest -q tests_golden/s12` with `TEST_DATABASE_URL` on a `_test` database | All pass. Only exception allowed: the M11 cross-tenant case, until D-11 is applied |
| A-4 | No implementation edits to owner files | `git diff f192b67 -- tools/owner_pin_s12.ps1 tools/owner_verify_s12.ps1 tools/owner_certify_s12.py tools/doc_consistency.py tools/s12_tracker.py docs/gates/S12_AUTOPILOT.md` | Empty. Today `owner_pin_s12.ps1` differs: see B-1 |
| A-5 | Certifier binary | `Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256` | `C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD` (also in `docs/gates/owner_certify_s12.sha256`) |
| A-6 | Certifier self-test | `python tools/owner_certify_s12.py --selftest` | Exit code 0 |
| A-7 | Records are tables | `Select-String -Path docs\gates\S12_RECORDS.md -Pattern '^\| ?CONF-' \| Measure-Object` | 47 rows; open: CONF-005, 042–047 |
| A-8 | Document checks | `python tools/doc_consistency.py; python tools/s12_tracker.py check` | `0 unruled finding(s)`; `tracker consistent` |
| A-9 | S0–S11 still certified | `python tools/owner_certify.py` | `19/19 PASS` |

---

## Part B: owner time plan

Times are estimates for reading and deciding; long test runs are unattended.

### How pinning works (read first)

`owner_certify_s12.py --pin` hashes **every** file matched by `PINNED_GLOBS`: all of `tests_golden/**` (including the
B4/B5 drafts and the fixtures) plus `tools/owner_pin_s12.ps1`, `tools/owner_verify_s12.ps1`, `tools/doc_consistency.py`,
`tools/s12_tracker.py` and `docs/gates/S12_AUTOPILOT.md`. **There is no per-batch pin.** Every pin covers the whole
golden set, and any later change to a pinned file fails S12-PIN for every milestone until the owner pins again. The
plan therefore pins twice: once for B1–B3 (with B4/B5 pinned as drafts), and again after the B4/B5 amendments.

### Sitting 1: pre-pin decisions, pin, close STOPs, certify M1–M14 (60–90 min, plus an unattended run)

| Step | Owner action |
|---|---|
| B-0 | Protect the branch: GitHub → Settings → Branches → rule for `s12-work`: block force pushes and deletion. Add `s12-work` to the `on.push.branches` of `.github/workflows/tests.yml` (today the workflow runs only for `s0-s11-*`) |
| B-1 | `tools/owner_pin_s12.ps1` is pinned and was edited by an implementation session. Its new venv branch is broken: when `.venv\Scripts\python.exe` is missing it calls that same missing program to install. **Restore the owner version**: `git checkout f192b67 -- tools/owner_pin_s12.ps1` (re-add improvements later, as an owner change) |
| B-2 | **Decide D-11** (composite ledger key) now: it changes a B3 file. Either (a) accept, and have the test-author session re-make the M11 case against the ruling before the pin, or (b) revert migration 018 and the ledger change for this phase, so the original M11 case passes. Then A-2 and A-3 must hold with no exception |
| B-3 | Review the golden diff since the last pin: `git diff <last pin commit> -- tests_golden tools/owner_pin_s12.ps1 docs/gates/S12_AUTOPILOT.md`, where `<last pin commit>` is `git log -1 --format=%h -- docs/gates/s12_pins.sha256`. Read B2 and B3 closely; B4/B5 are pinned as drafts and amended in sitting 3 |
| B-4 | Pin: `powershell -ExecutionPolicy Bypass -File tools\owner_pin_s12.ps1` (it checks the certifier hash, runs the self-test, pins, commits, pushes) |
| B-5 | Close the STOPs (Part C-table below), one commit, records only |
| B-6 | **Unattended:** `python tools/owner_certify_s12.py --milestone M14` (full mode: golden, sabotage, 5× concurrency for every milestone up to M14; one run certifies M1–M14). It writes `docs/gates/S12_PROGRESS.md`; commit it |
| B-7 | Tracker, in order. The tracker refuses to move a milestone while an earlier ★ milestone is below `reviewed` (★: M0, M1, M8a, M14, M21). So: `set M1 green` → review M1 → `set M1 reviewed` → `set M2 green` … `M8a green` → review → `M8a reviewed` → `M9` … `M14 green` → review → `M14 reviewed`. ★ reviews: **M1** the schema (migrations 015–018), **M8a** worker eligibility and quota, **M14** live revalidation and cancellation, including CONF-032 (gate 8 is a delay) |

### Sitting 2: ruling pass (60–90 min)

Decide Parts D (except D-11, done in sitting 1) and E; paste the row texts (Part F); one commit, records only; run the
Part F checks.

### Sitting 3: amended B4/B5 drafts, second pin, certify M15–M21 (45–60 min, plus an unattended run)

| Step | Owner action |
|---|---|
| B-8 | Review the B4/B5 amendments the test-author session drafted from Part G. They must be **red** on the current code (red-first) |
| B-9 | Pin again (B-4). Pin **before** the implementation: the pinned, failing cases are the target. Never pin after the code passes, which would let tests bend to code |
| B-10 | After the implementation session reports them green: **unattended** `python tools/owner_certify_s12.py --milestone M21`, then the tracker M15 … M21 in order, with the ★ review of M21 |

---

## Part C: rules for implementing safely

1. **Rule first, then golden, then code.** A behaviour change starts as a ruled record, becomes a red golden case
   (test-author session), and only then becomes code (implementation session).
2. **The implementation session never edits `tests_golden/`, the pinned tools, pins, or the ruling columns.** A test
   that seems wrong is a STOP row, not an edit.
3. **One ruling pass = one commit touching only `S12_RECORDS.md`, `S12_STOPS.md`, `S12_DEFECTS.md`.**
4. **Every pin covers the whole golden set.** Review the whole diff since the last pin before pinning, and pin
   amendments red, before the code that turns them green.
5. **Certify in full mode** before a milestone is marked green; `--fast` is for checking only.
6. **Never force-push.** Restore and fix by merge or revert; keep branch protection on.
7. **Security findings take the fail-closed option**, even when it costs a feature in this phase.
8. **Records stay tables.** The certifier reads only `| CONF-nnn |` and `| STOP-nnn |` rows (third column = status).
9. **Every ruling names its follow-on work** (golden file, milestone, register line), so nothing ruled stays
   unimplemented.

### Close-outs (sitting 1, step B-5)

The certifier blocks while a STOP is `open` **or `ruled`**; DEF rows block only the tracker's `reviewed`.

| Record | Now | Action | Row text |
|---|---|---|---|
| STOP-001 | ruled | `applied` | `applied <date>: golden set pinned (<pin commit>)` |
| STOP-002 | open | `applied` | `applied <date>: B2 golden files present and pinned (<pin commit>)` |
| STOP-004 | open | `applied` | `owner <date>: B3 drafted and reviewed as proposed; pinned (<pin commit>)` |
| STOP-005 | open | `applied` | `owner 2026-09-30: CONF-021..032 accepted (150a668); applied 150a668, <pin commit>` |
| DEF-002 | open | Verify, then `fixed` | The M12 loop logs only Appendix A reasons: I5 passes in every golden run. `fixed <date>: loop rewritten in M12; I5 green (<commit>)` |
| DEF-004 | open | Verify, then `fixed` | `loop.py:319-320` moves the step to RUNNING and the reservation to LOCKED in one `set_step` (I-3). `fixed <date>: one transaction, loop.py:319-320 (<commit>)` |
| DEF-003 | open | Decide D-13 (sitting 2) | — |

---

## Part D: decisions

### D-0: summary

| # | Record (milestone column) | When | Recommendation | If decided wrong |
|---|---|---|---|---|
| D-1 | CONF-005 (M15) | Sitting 2 | A: no autonomy source this phase | B: every CONFIRM_ALL step dead-letters (human layer is UNKNOWN) |
| D-2 | CONF-042 (M19) | Sitting 2 | A with CONF-046's amendment | B puts the most powerful credential in every runtime |
| D-3 | CONF-043 (M19) | Sitting 2 | **A′** (A + `retry_mode = NONE` + recorded episode) | Plain A lets an operator retry probe a tampered plan's parameters |
| D-4 | CONF-044 (M19) | Sitting 2 | A+ (one pinned checkpoint assertion) | A leaves an unpinned write path and a vacuous M20 check |
| D-5 | CONF-045 (M20) | Sitting 2 | A: renew, pinned in M20 | C (the recorded proposal) is unpinned concurrency code; mid-call takeovers |
| D-6 | CONF-046 (M19) | Sitting 2 | A | Needless takeovers of live runs; nondeterministic M20 |
| D-7 | CONF-047 (M19) | Sitting 2 | A | B needs a gate change for a state nothing produces |
| D-8 | new CONF-048 (M19) | Sitting 2 | A: in-flight set lives in `transitions.py` | B edits a pinned B1 file |
| D-9 | new CONF-049 (M21) | Sitting 2 | Operator path for dead letters, pinned in M21 | LOCKED money has no release path in production |
| D-10 | new CONF-050 (M19) | Sitting 2 | A recorded FAIL ends the step FAILED after a crash | A non-retryable FAIL can flip to PASS |
| D-11 | new CONF-051 (M11) | **Sitting 1, before the pin** | Composite ledger key, with conditions | Cross-tenant key collision stops the second tenant; or M11 cannot certify |
| D-12 | new CONF-052 (M21) | Sitting 2 | Mutations production-enabled only with a verifying adapter | Every successful mutation dead-letters and holds money |
| D-13 | DEF-003 (S0–S11) | Sitting 2 | B: defer, role guard at every entry point | A moves the S0–S11 tag mid-batch |

New records 048–052 are recorded **directly as `ruled`** (a new row with status `open` would block every milestone from
its milestone column onward). Numbers are assigned in this order; if one is taken, use the next free number and keep
the order. The milestone column above is what the certifier gates on.

### D-1 CONF-005: no AutonomyLevel source (blocks M15)

- **Question.** Gate D6 says STOP if there is no AutonomyLevel source; there is none in code.
- **Recommendation: A.** Layer selection by mutation and risk only in this phase, as CONF-041 already assumes and
  golden M15 pins. Deferred register: "autonomy source: post-S15".
- **Why.** B builds a source whose only effect in this phase is to dead-letter every CONFIRM_ALL tenant's steps,
  because the human layer always returns UNKNOWN (D4).
- **Follow-on.** Deferred-register line; certification report sentence.
- **Row text.** `ruled <date> (owner): option A; no AutonomyLevel source in this phase; required_verification_layers(mutation, risk); register: autonomy source post-S15`

### D-2 CONF-042: sweeper discovery under forced RLS (blocks M19)

- **Recommendation: A, as amended by CONF-046**: one `SECURITY DEFINER` function
  `s12_recovery_candidates(runtime_instance_id, limit, orphan_after_s)`, ids only, writes nothing, `search_path`
  pinned with `pg_temp` last, the only such function in the schema.
- **Why.** The alternatives are a BYPASSRLS role in every runtime (B) or a second source of truth on the hottest
  path (C).
- **Follow-on.** Deployment: revoke `EXECUTE` from `PUBLIC` and grant it to the runtime role (the migration cannot know
  the role name; recorded with CONF-046 in the B5 review).
- **Row text.** `ruled <date> (owner): option A with CONF-046's signature (runtime_instance_id, limit, orphan_after_s); search_path pinned, pg_temp last; deployment revokes EXECUTE from PUBLIC`

### D-3 CONF-043: the in-flight step of a tampered plan (blocks M19)

- **Recommendation: A′** (truth model C-12).
  1. The dead letter has `retry_mode = NONE`, not PROBE. A probe retry would rebuild the call from the plan that
     failed its digest check, and tampering implies database write access, so a human resolves it (D5: NONE leaves
     `pending` only by human resolution, through D-9's operator path).
  2. An EXECUTION episode is opened and closed with the step's move: creation logged `none → pending_probe (opened)`,
     closed with outcome EXHAUSTED, `attempts = 0`, evidence `plan_integrity`, the `episode_closed` event, linked by
     the dead letter's `episode_id`. Every dead-letter step then has a closed episode, and an operator sees that no
     probe ran despite the reason `probe_exhausted` (the only Appendix A.2 edge; changing it re-pins the gate and B1).
- **Follow-on.** M19 golden amendment (Part G) before the second pin.
- **Row text.** `ruled <date> (owner): A as proposed, amended: retry_mode NONE (no automated probe from an untrusted plan; human resolution only); an EXECUTION episode is opened and closed with it (outcome EXHAUSTED, attempts 0, evidence plan_integrity, linked by episode_id); golden M19 amended before the B5 pin`

### D-4 CONF-044: checkpoints (blocks M19)

- **Recommendation: A+.** Written at §8 steps 7 and 11 through `fenced_write` as a hint; recovery never reads them;
  one M19 assertion that a completed run has increasing sequences and the last row lists every step.
- **Why.** Without the assertion, the write path is unpinned, and M20's tenant-isolation check on `checkpoints`
  passes even if no row is ever written.
- **Row text.** `ruled <date> (owner): option A+; checkpoint rows are a hint written at §8 steps 7 and 11; recovery never reads them; one M19 assertion pins that they are written`

### D-5 CONF-045: lease renewal during a step (blocks M20)

- **Note.** The recorded proposal is option C ("pinned when an owner assigns it"), which the pack rejects.
  "Accepted as proposed" would choose C.
- **Recommendation: A.** The loop renews every `lease_renewal_interval_s` while a step runs; `LeaseLost` stops the step
  like `FencedOut`; two M20 cases: a step longer than the TTL completes with no takeover and strictly increasing
  tokens; a refused renewal writes nothing further and discards the result.
- **Why.** The pinned M21 defaults set step timeout = lease TTL = 30 s (`M21_journeys.py:344`), so without renewal a
  step can be taken over mid-call. It is also the likely cause of the M20 instability (IMP-X7), which a timing
  workaround would only hide.
- **Row text.** `ruled <date> (owner): option A (not C); renewal every lease_renewal_interval_s during a step; LeaseLost stops the step like FencedOut; pinned by two M20 cases before the B5 pin`

### D-6 CONF-046: when is a run orphaned (blocks M19)

- **Recommendation: A** as recorded: judged by the latest lease; active and unexpired never; lapsed or expired at
  once; released one TTL after release; never leased one TTL after the ownership row.
- **Row text.** `ruled <date> (owner): accepted as proposed (option A)`

### D-7 CONF-047: NOT_EXECUTED in a RECONCILING run (blocks M19)

- **Recommendation: A** as recorded: the step ends `cancelled (not_executed_no_retry)`; the run is consolidated in the
  same pass.
- **Row text.** `ruled <date> (owner): accepted as proposed (option A)`

### D-8 new CONF-048 (M19): recovery must name `StepState.UNKNOWN`

- **Record and rule together:** copy the "Proposed CONF-048" section of `S12_RULING_PACK.md` into a new row.
- **Recommendation: A.** The in-flight set (`IN_FLIGHT_STEP_STATES`) lives in `transitions.py`, which may name
  UNKNOWN; recovery imports it. Aliasing to evade the M03 scan is forbidden.
- **Row text.** `ruled <date> (owner): option A; the in-flight set is defined in transitions.py and imported by recovery; no aliasing around the M03 scan`

### D-9 new CONF-049 (M21): operator path for dead letters

- **Question.** §11 and D5 define dead-letter retry and resolution, and the M17 draft fixes the adapter interface,
  but no milestone builds an entry point (IMP-M17-2). A LOCKED reservation has no release path in production and
  counts against `budget_pool` like a committed one (I1).
- **Recommendation.** An admin API, assigned to M21: list a tenant's open dead letters under RLS; resolve with
  EXECUTED / NOT_EXECUTED / UNDETERMINED (settles a LOCKED reservation per C21; never moves the run or the step, D4);
  retry only PROBE / VERIFY records (refused for NONE, which includes D-3's dead letters). Access through the existing
  admin API actor checks for the dead letter's tenant, audited like the other admin actions.
- **If not assigned before certification:** the certification report states "LOCKED money has no release path", and
  production stays read-only for mutations (D-12).
- **Row text.** `ruled <date> (owner): admin API for dead letters (list, resolve, retry PROBE/VERIFY only), tenant-scoped admin access, audited; assigned to M21; pinned by M21 golden cases before the B5 pin`

### D-10 new CONF-050 (M19): a recorded FAIL during recovery

- **Question.** At `after_verification_before_step_commit` with a FAIL recorded, §13 opens a VERIFICATION episode
  ("not recorded as PASS") and C19 re-runs the failed layer; §8 step 9 says FAIL is not retryable. No golden case.
- **Recommendation.** §8 step 9 wins. Recovery checks for a recorded FAIL **before the ledger lookup** (so the answer
  is the same whether or not the ledger row has expired). On any recorded FAIL (latest verdict per layer, CONF-036):
  the open VERIFICATION episode, if any, closes `confirmed_failure (verified_fail)`; step `failed
  (verification_failed)`; budget released (`step_failed`); dead letter `data` / NONE.
- **Follow-on.** M19 cases with and without an open episode (Part G).
- **Row text.** `ruled <date> (owner): §8 step 9 wins over §13 for a recorded FAIL, checked before the ledger lookup: episode closed verified_fail if open, step failed (verification_failed), budget released, data dead letter; pinned by M19 cases before the B5 pin`

### D-11 new CONF-051 (M11): composite idempotency-ledger key (decide in sitting 1)

- **Question.** Gate §8 makes `idempotency_key` the ledger's primary key; the key `request_id:plan_step_id` is unique
  only per tenant (`request_id` is unique per tenant in `009`, generated as a UUID by S0 today). Migration 018 made the
  key `(tenant_id, idempotency_key)`, and golden M11 was edited by the implementation session to accept it.
- **Recommendation: accept, with conditions.** (1) Remove `BEGIN`/`COMMIT` from `018_idempotency_composite_pk.sql`
  (every other migration relies on the migrator's single transaction). (2) The M11 change is re-made by the
  test-author session against this ruling. (3) A same-tenant row with another `kernel_op_id` still raises
  `IdempotencyConflict`.
- **Alternative that lets you pin today:** revert migration 018 and the ledger code for this phase (original M11
  passes), and record this as a post-S15 item.
- **Row text.** `ruled <date> (owner): ledger key (tenant_id, idempotency_key); migration 018 without BEGIN/COMMIT; M11 re-made by the test-author session; same-tenant foreign kernel_op_id still raises IdempotencyConflict`

### D-12 new CONF-052 (M21): production enablement of mutations

- **Question.** By design (C32), an adapter without `observe()` makes provider_state verification UNKNOWN, so every
  W/D/IRREVERSIBLE step on it ends DEAD_LETTER with its money LOCKED, even when the call succeeded.
- **Recommendation.** Keep C32 unchanged; refuse unverifiable mutations at enablement: (1) `tools/registry_readiness.py`
  blocks a `PRODUCTION_ENABLED` mutation unless its adapter overrides `observe()` and `probe()` (not only when the
  catalog names an observation method); (2) the Worker Runtime refuses to start with such a binding (M21, next to
  D-13's role check); (3) production runs read operations only until real adapters (roadmap 2c, Layer A specs) pass
  their conformance cases; each mutation is then enabled one operation at a time by the owner.
- **Row text.** `ruled <date> (owner): C32 unchanged; mutations PRODUCTION_ENABLED only with an adapter implementing observe() and probe() for the operation; readiness tool and runtime start-up enforce it (M21); production read-only for mutations until roadmap 2c`

### D-13 DEF-003: frozen confirmation store without a `tenant_id` predicate

| Option | Effect | Cost |
|---|---|---|
| A | Add the predicate now under §19.3 change control | The `s0-s11-certified` tag moves; M1–M9 re-verified mid-batch |
| **B (recommended)** | `wontfix` this phase; RLS plus the superuser/BYPASSRLS refusal are the control; the same refusal is required at every Worker Runtime entry point (pinned in M21); predicate added in the first post-S15 change-control batch with CONF-006 | The defense-in-depth gap stays open until after S15, guarded by two role checks |
| C | Reclassify `confirmations.py` as S12 code | Edits a pinned file; precedent for reclassifying frozen files |

- **Row text (B).** Status `wontfix`; `owner <date>: RLS + NOSUPERUSER/NOBYPASSRLS role guard are the control in this phase; Worker Runtime entry must refuse superuser/BYPASSRLS (M21); predicate added in the first post-S15 S0–S11 change-control batch with CONF-006`

---

## Part E: amendments to rulings recorded but not implementable as written (sitting 2)

| Record | Problem | Recommendation | Text to append to the Ruling column |
|---|---|---|---|
| CONF-008 | Ruled "goes into the deferred register", but no register line was ever written | Keep fail-closed; write the register line and an operator rule | `deferred-register entry written <commit>; operator rule: a catalog version bump denies plans awaiting confirmation; bump when none are pending` |
| CONF-020 | M18 never sees an entry DENY (no run), and no M18 case pins `quota_exhausted` | S15 maps entry denials through `entry_denial_envelope(outcome)`; `quota_exhausted` → error type `budget_exceeded` with the upgrade text (soft adds `retry_after_ms`); 2–3 M18 cases before the second pin | `amended <date> (owner): entry denials are mapped by S15 entry_denial_envelope (M18), quota_exhausted → budget_exceeded with upgrade text; pinned by M18 quota cases` |
| CONF-027 | The real admission snapshot and pre-flight sources were never assigned; every golden injects them | Assign to M21 (`PostgresAdmissionSnapshot`, `PostgresPreflight`) and amend M21 before the second pin; otherwise the certification report must say the loop is not production-wired | `assigned <date> (owner): M21; PostgresAdmissionSnapshot and PostgresPreflight; one journey with real sources plus one case per DB-backed gate` |

---

## Part F: how to apply a ruling pass

1. Edit the rows in `docs/gates/S12_RECORDS.md`, `S12_STOPS.md`, `S12_DEFECTS.md`. The certifier and tracker read the
   **third column** (Status): CONF `open` → `ruled`; STOP `open`/`ruled` → `applied`; DEF `open` → `fixed` or
   `wontfix`. Paste the row text into the ruling column. New records (048–052) are new table rows, status `ruled`,
   opened today, with the milestone column from D-0.
2. One commit per pass, records only. Sitting 1: `s12: owner close-outs <date>: STOP-001/002/004/005 applied; DEF-002/004 fixed; CONF-051 ruled`.
   Sitting 2: `s12: owner rulings <date>: CONF-005, 042–050, 052; DEF-003; amendments CONF-008/020/027`.
3. Check, in this order:
   ```
   python tools/doc_consistency.py                               # 0 unruled finding(s)
   python tools/s12_tracker.py check                             # tracker consistent
   python tools/owner_certify_s12.py --milestone M14 --fast      # S12-REC PASS
   python tools/owner_certify_s12.py --milestone M21 --fast      # S12-REC PASS (S12-PIN may fail until the second pin)
   ```
4. Push normally. Never `--force`.

---

## Part G: hand-off after the rulings

**Test-author session (golden amendments, red-first, before the second pin):**

| File | Change | From |
|---|---|---|
| `M11_idempotency_retry.py` | Composite-key behaviour, re-made against the ruling (sitting 1, before the first pin) | D-11 |
| `M19_recovery.py:540-541` | Tampered-plan dead letter: `retry_mode == "NONE"`; one EXECUTION episode, outcome EXHAUSTED, `attempts == 0`, linked by `episode_id` | D-3 |
| `M19_recovery.py` (new) | Crash at `after_verification_before_step_commit` with a FAIL recorded, with and without an open episode, and with the ledger row expired | D-10 |
| `M19_recovery.py` | Checkpoint assertion | D-4 |
| `M20_multiprocess.py` | Two renewal cases | D-5 |
| `M18_response.py` | 2–3 `quota_exhausted` entry-denial cases | CONF-020 |
| `M21_journeys.py` | Operator endpoint; real admission and pre-flight sources; Worker Runtime role check; enablement check | D-9, CONF-027, D-13, D-12 |
| Sabotage | A recovery that writes PROBE for a `plan_integrity` dead letter; a FAIL re-run after a crash; a dead-letter retry allowed for NONE | D-3, D-10, D-9 |

**Implementation session (after the second pin):** implement D-3, D-4, D-5, D-8, D-9, D-10, D-11 (migration fix),
D-12, D-13's role check, and the CONF-020 and CONF-027 amendments; then review the reference-derived `src/` (security
review, fenced-write registry IMP-X2, redaction IMP-X5).

---

## Part H: the owner scripts `certify_batch.ps1` and `certify_milestone.ps1`

Neither is pinned (they are not in `PINNED_GLOBS`). Until fixed, use the certifier and tracker commands of Part B
directly.

| Script | Problem | Fix |
|---|---|---|
| `certify_batch.ps1` | Line 75 still has `$lastMilestone:` (a parse error; commit `2f70adc` changed only `certify_milestone.ps1`) | `${lastMilestone}` |
| `certify_batch.ps1` | Pins and pushes after certifying (step 4): pins without a review, and the certification itself needs a current pin | Remove the pin step; pinning is `owner_pin_s12.ps1` after review (B-3, B-4) |
| `certify_batch.ps1` | Sets M0…end green in one loop; the tracker refuses anything after a ★ milestone below `reviewed`, so most writes fail | Follow B-7 instead |
| `certify_batch.ps1` | `python … 2>&1` under `$ErrorActionPreference = "Stop"` turns tracker stderr into a terminating error (PowerShell 5.1) | Set `Continue` around the call, as `certify_milestone.ps1` now does |
| `certify_batch.ps1` | `$_ -le $lastMilestone` compares strings (`"M8a" -le "M14"` is false) | Compare positions in the milestone list |
| `certify_batch.ps1` | Non-ASCII characters; line 77 already garbled | Save as UTF-8 with BOM, or use ASCII |
| `certify_milestone.ps1` | With `-Fast` it still sets the milestone green | Set green only in full mode |
| `certify_milestone.ps1` | Usage says `--fast`; the parameter is `-Fast` (PowerShell rejects `--fast`) | Fix the usage text |
| `certify_milestone.ps1` | Assigns `$args`, PowerShell's automatic variable, and splats it | Rename (for example `$certArgs`) |
| `certify_milestone.ps1` | Reports any tracker refusal as "already green or reviewed", hiding refusals for open records or order | Print the tracker's own message |

---

## Part I: what the recheck changed (2026-10-02)

| # | Gap in the first version | Fixed in |
|---|---|---|
| 1 | Assumed per-batch pinning; `--pin` hashes the whole golden set and the pinned tools | Part B "How pinning works"; two pins |
| 2 | D-11 changes a B3 file but was scheduled after the pin | D-11 moved to sitting 1, with a pin-today alternative |
| 3 | Sitting 3 pinned after the implementation passed (tests could bend to code) | B-9: pin red, before the code |
| 4 | No pre-checks; M01/M10/M12 still carried implementation edits, and `M12_loop.py` had four helpers defined twice (two with different bodies; the later, restored definitions win) | Part A, A-2 |
| 5 | `owner_pin_s12.ps1` (pinned) has a broken venv branch; plan said only "restore" without the command | B-1 |
| 6 | Certification per milestone was ambiguous; one full run to M14 certifies M1–M14; the tracker's ★ order was missing | B-6, B-7 |
| 7 | New records could have been added as `open`, blocking every milestone from their column onward; milestone columns were not given | D-0 note and column |
| 8 | D-10 did not say the recorded FAIL is checked before the ledger lookup (expired ledger rows) | D-10, Part G |
| 9 | Part F's commit message mixed sitting 1 and 2 items | Part F step 2 |
| 10 | `certify_batch.ps1` line 75 was assumed fixed; `certify_milestone.ps1` problems not listed | Part H |
| 11 | CI does not run on `s12-work` | B-0 |
