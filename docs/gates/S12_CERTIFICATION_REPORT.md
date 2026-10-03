# S12–S15 certification report

Gate §20 template, filled from the certified code and the owner's verification run, with the evidence for each row.

- **Status:** **CERTIFIED**, 2026-10-03. Tag `s12-s15-certified` = `c844cdd`, verified by the owner
  (`owner_verify_s12.ps1 M21`, 34/34 PASS).
- **Revision 2:** after a stage-by-stage re-check. It adds the `tests_postgres` results, four pre-tag decisions
  (section 5), the API-wiring gaps and a proposed DEF-006, and corrects the S8 and blocker rows.
- **Revision 3 (at the tag):** the four pre-tag decisions were taken as option (a) and done in code (section 5); the
  owner re-verified at `c844cdd` and tagged; the numbers below are at the tagged commit; section 8 lists the work
  pushed to `s12-work` after the tag.
- **Companions:**
  - `docs/gates/S12_DEFERRED_REGISTER.md` (gate §21, DR-01–DR-60);
  - `docs/gates/S0_S15_STAGE_REFERENCE.md` (per-stage logic, what works, limits, inconsistencies).

| Item | Value |
|---|---|
| Code certified | **`c844cdd`** = tag `s12-s15-certified` (owner checkpoint commit `d6b8ad7` "M21 green at c844cdd"). Earlier M21 certification: `ee9c334` (checkpoint `3c2a515`) |
| Owner verification | `tools/owner_verify_s12.ps1 M21` on the owner's Windows host at `c844cdd`: **34/34 PASS (target M21)**, including C-M20 (5 consecutive multi-process runs) and X-M21 (sabotage); transcript `..\verify_m21.txt` |
| Tags | `s12-s15-certified` → `c844cdd`; `s12-m14-certified` → `181b7f5`; `s12-stage2-pinned` → `dac952e` (annotated, pushed by the owner) |
| S12 certifier | `tools/owner_certify_s12.py`, SHA-256 `C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD` (= `docs/gates/owner_certify_s12.sha256`) |
| Pinned set | `docs/gates/s12_pins.sha256`, 138 files (pins #1–#6: `db847c4`, `49b1fb9`, `157a173`, `dac952e`, `a54cba1`, `ffc35a7`) |
| Base tag | `s0-s11-certified` = `f14a95626749ea85caadd7318aa1729f46d56565` |
| Platforms | Windows (owner certification host); Linux 6.18, Python 3.11.15, PostgreSQL 16.14 (independent re-runs for this report). Code is portable (gate §21 S9, M20) |

## 1. Gate §20 template

```text
S12–S15 CERTIFICATION

Preflight:                 PASS   (docs/gates/S12_M0_PREFLIGHT.md: Pre-1..Pre-4 PASS; items 1, 2, 10, 17 pass)
Doc repairs C1–C41:        PASS   (applied by the owner as gate v9/v10 documentation edits with repair markers;
                                   certifier row S12-DOC "document consistency" PASS; none outstanding)
Owner decisions D1–D6:     as confirmed: D1 verifiers built at S12 entry from pinned metadata;
                           D2 explicit rollback only (undo_token, inverse through the guard, InverseBudget CONF-038);
                           D3 join_mode "all" only; D4 unresolved UNKNOWN → DEAD_LETTER, LOCKED until resolution,
                           human layer UNKNOWN; D5 dead-letter retry PROBE / VERIFY / NONE, never re-executes;
                           D6 semantic layer may only FAIL or UNKNOWN, strict enum

State machines:            PASS   (transitions tested: 114 legal edges with their allowed reasons, 57 wrong-reason
                                   rejections, an exhaustive illegal-pair sweep over 9 machines; goldens M3 130, M4 79)
Architecture:              PASS   (violations: 0; scans over all of src/: tenant-scoped SQL (M2), no bare state
                                   literals (M4), no module-level mutable state (M10), task scheduling only in
                                   dispatch.py (M12), probe handling only in the s13 package (M13), no hard-coded
                                   hosts / filesystem checkpoints / Laya code (M21), no POSIX-only APIs (M20))
S12 entry:                 PASS   (golden M6, 23 cases)
Budget:                    PASS   (concurrency runs: 5 x golden M9; over-reservations: 0 —
                                   test_twenty_concurrent_reservations_never_over_reserve; I1, I2, I12)
Leases/fencing:            PASS   (fenced-out writes succeeded: 0 — M2 fencing cases; I7, I8; 5 x M7)
Idempotency:               PASS   (duplicate side effects: 0 — M11; crash at every point and multi-process runs assert
                                   one side effect per key, 14 assertion sites; I4)
Retry matrix:              PASS   (golden M11, 46 cases)
UNKNOWN/probe:             PASS   (UNKNOWN bypassing PENDING_PROBE: 0 — M13 asserts every timeout is followed by
                                   pending_probe; I6)
Verification:              PASS   (golden M15, 51 cases, incl. a failing deterministic layer never overridden by a
                                   semantic PASS)
Consolidation:             PASS   (golden M16, 31 cases)
Dead letter:               PASS   (golden M17, 37 cases; operator API M21)
S15 redaction:             PASS   (M18 test_secrets_traces_and_provider_bodies_reach_no_envelope_log_or_row)
Confirmation store (PG):   PASS   (concurrent winners per token: 1 — test_twenty_concurrent_consumers_one_winner; 5 x M5)
Crash recovery:            PASS   (injection points: 10/10; subprocess kills: 3/3; recovery itself recoverable, 4 cases)
Transition tables (App. A): PASS  (pairs tested: 114 legal edges + exhaustive illegal sweep; guarded edges: 9 step
                                   edges the gate names illegal, each asserted)
v9 rulings C24–C38:        PASS   (suite 19 by ruling: C24 transition tables M3/M4; C25 fence sequence and C26 lease
                                   status M7; C28 enum CHECKs M1; C30 admission mapping M8; C31 budget layer and C32
                                   adapter interface M10; C33 budget period M9; C35 dispatch marker M11/M19)
Cancellation:              PASS   (golden M14, 28 cases)
Two Worker Runtimes:       PASS   (double executions: 0; takeovers: 4 scenarios — 3 killed-process recoveries, 1 shared
                                   run with takeover; sweepers claim every orphan exactly once; 5 x M20)
Tenant isolation:          PASS   (forced RLS on every S12 table; cross-tenant read/change/forge refused — M20; I15)
Journeys S0→S15:           8/8 PASS (plus a ninth on the real admission and pre-flight sources, CONF-027);
                           each starts from a state the real S0–S11 pipeline certified and is admitted by S12
                           entry. The S11→S12 handoff is done by the test fixture (fixtures/certified.py); the
                           application has no such handoff (DR-48)
Invariants I1–I18:         PASS   (checker implements I1–I3, I5–I16, called at 123 sites across the goldens; I4 asserted
                                   per test from provider side-effect counts; I17 by CHECK used_count <= limit_value and
                                   M8a; I18 by M8a test_only_an_eligible_worker_is_ever_leased)
Worker management (C39):   PASS   (quota overshoots: 0 — I17 CHECK; leases on ineligible workers: 0 — I18; M8a 49 cases)
Scale-readiness S1–S9:     PASS   (S1 settings from env (M2, M21); S2 InProcessDispatcher (M12); S3 no module state (M10);
                                   S4 SKIP LOCKED sweepers (M20); S5 correlated logs + no-op metrics (M12, M21);
                                   S6 CredentialProvider + redaction (M10, M18); S7 superseded by C34 (M1, M20);
                                   S8 PARTIAL: a semantic PASS never overrides a deterministic FAIL (M15), but
                                   the provider-text-instructs-PASS test needs a real assessor (DR-21, DR-60);
                                   S9 portability (M20). Not met in production terms: see section 4)
Performance baseline:      p50/p95 S12 overhead per step = 42/55 ms (Linux, 210 steps, three runs:
                           41.3/55.0, 41.9/54.6, 42.4/53.8; recorded, no threshold)

S0–S11 regression:         19/19 PASS (S12-S011 row of the owner run at c844cdd)
Full regression:           goldens M1–M21 clean in the owner run at c844cdd (G-M1..G-M21, C rows, X-M21);
                           at ee9c334: 1826/1826 (tests 836, tests_golden 896, tests_agent 94);
                           independent re-run at c844cdd: PENDING (filled in the next revision)
tests_postgres (S0–S11 integration, not run by any certifier):
                           before the pre-tag fixes: 294 passed, 1 FAIL (DR-59), 2 files not importable (DR-58);
                           with P1 and before P2: 326 passed, 1 FAIL (test_schema_audit, fixed by P2);
                           the four changed files at the merged head: 43/43 on the owner host;
                           12 live-model tests need DEEPSEEK_API_KEY (not run)
Skipped: 0   XFail: 0

Recorded blockers:         CONF-001..052: 2 fixed, 50 ruled, 0 open; CONF-035's port applied (48fa283);
                           STOP-001..005 applied; DEF-001, DEF-005 fixed; DEF-003 wontfix by ruling;
                           DEF-002, DEF-004 fixed in code (M12); DEF-006 (admission budget gate) fixed (192e993).
                           Record rows to update: section 3
Open questions:            DR-19 (no post-execution human-approval run state); all others in the deferred register
Deleted tests:             none

Final:                     CERTIFIED at c844cdd (tag s12-s15-certified); pre-tag decisions P1–P4 taken and
                           done (section 5)
```

## 2. Milestones

Owner checkpoint commits on `s12-work` (★ = star milestone, reviewed by the owner). M0 (preflight, no goldens) is
reviewed (`docs/gates/S12_M0_PREFLIGHT.md`).

| Milestone | Goldens | Checkpoint | Milestone | Goldens | Checkpoint |
|---|---|---|---|---|---|
| M1 ★ | 89 | `24c562e`, reviewed `ebaaa21` | M12 | 33 | `591fc73` |
| M2 | 18 | `5bc4805` | M13 | 13 | `fe09926` |
| M3 | 130 | `42ae078` | M14 ★ | 28 | `2c0a8a2`, reviewed `181b7f5` |
| M4 | 79 | `a0b1361` | M15 | 51 | `1fd59b8` |
| M5 | 30 | `4aec3a3` | M16 | 31 | `77ad7ba` |
| M6 | 23 | `d6a538b` | M17 | 37 | `6ca11ef` |
| M7 | 15 | `fdfc7df` | M18 | 19 | `ee9be5a` |
| M8 | 40 | `e51855f` | M19 | 44 | `a89ff73` |
| M8a ★ | 49 | `289d2e8`, reviewed `721e916` | M20 | 12 | `24adafc`, re-verified `7f30892` |
| M9 | 17 | `4fd6fed` | M21 ★ | 28 | `3c2a515`, re-verified at `c844cdd` (`d6b8ad7`), reviewed by the owner |
| M10 | 64 | `7c29d74` | | | |
| M11 | 46 | `6586639` | **Total** | **896** | |

Concurrency rows (5 consecutive runs each): M2, M5, M7, M8a, M9, M20, 30 full-file runs, all PASS in the owner's run.
Sabotage: every milestone's sabotage patches caught (X rows); M21 patches caught in the owner's run.

## 3. Records at certification

- **CONF-001…052.**
  - CONF-001, CONF-002: fixed.
  - Every other CONF: ruled by the owner.
  - None open (certifier S12-REC PASS).
  - Rulings that set statements for this report:
    - **CONF-005 (D-1):** "Autonomy is not used to select verification layers in this phase; layer selection is by
      mutation and risk (`required_verification_layers`); the autonomy source is deferred past S15 (DR-33)."
    - **CONF-027:** the admission snapshot and pre-flight read the database (`PostgresAdmissionSnapshot`,
      `PostgresPreflight`, M21). Two gaps remain: the pre-flight validates no kernel input schema (DR-04), and two
      admission gates have no database source (DR-26).
    - **CONF-049:** LOCKED money has a release path: the tenant-scoped, audited dead-letter admin API (list, resolve,
      retry PROBE/VERIFY only).
    - **CONF-052 (D-12):** production stays read-only for mutations until real adapters pass conformance (DR-41).
- **STOP-001…005:** all applied.
- **DEF:**
  - DEF-001 and DEF-005: fixed.
  - DEF-003: `wontfix` by ruling D-13. Control: forced RLS, a least-privilege role, and the runtime refuses a superuser
    or BYPASSRLS role (DR-09).
  - **DEF-002 and DEF-004: fixed by the M12 rework** (evidence in register DR-R5). Row text for the owner's
    columns in `S12_DEFECTS.md` (on GitHub both rows still read `open` when this revision was written):
    - DEF-002: `fixed in M12 (591fc73): loop step reasons are Appendix A's (started …); step_started / step_completed are
      reservation reasons allowed by A.3; I5 checked by assert_system_invariants across the goldens`
    - DEF-004: `fixed in M12 (591fc73): step pending→running and reservation reserved→locked in one set_step
      transaction (I-3); golden M09 test_lock_joins_the_callers_transaction and M12`
  - **DEF-006** (caused by M21, minor, found 2026-10-03): admission gate 10 read `execution_steps.effective_risk`
    (0–1) as the step cost, so for any pool ≥ 1 it reduced to "pool > 0". **Fixed in `192e993`** before the tag
    (decision P3 a): the gate now asks whether the reserve step would succeed (plan step cost from
    `canonical_plan`, `AVAILABLE_SQL`, live reservation passes, unknown step fails closed). Test
    `tests_agent/test_admission_snapshot_budget_def006.py`: 3 of 7 red before, 7/7 after; goldens unchanged. Row text:
    `DEF-006 | M21 | closed | 2026-10-03 | stage re-check | minor | admission_snapshot.py gate 10 used effective_risk
    as cost | fixed 192e993`. A pinned golden case is DR-65.
- **CONF-035** (ruled): applied in `48fa283` (decision P1 a). Its findings are register DR-61–DR-64.

## 4. What this certification does and does not mean

**Certified.** The single-node durable execution kernel of gate §22, from the S11 manifest through S12 entry, the
step loop, probe, verification, consolidation, dead letter and S15 response, with crash recovery that never
re-executes blindly. Several Worker Runtimes are proven safe on one database. Every behaviour above is pinned by owner
goldens and verified by the owner.

**Not certified. These must be true before anything is called production-ready** (details in the register):

1. **The kernel is not reachable from the application.**
   - The API runs S0–S11 and never admits a plan to S12 (DR-48).
   - No route returns a run's outcome (DR-49).
   - No Worker Runtime exists; the kernel is composed only in tests, and `main.py --worker` is a stub (DR-14).
   - The dead-letter operator has no HTTP route (DR-57).
2. **Only the mock adapter is on `s12-work`.** Real adapters are the next phase (DR-38–DR-43). The cross-check found
   two S0–S11 gaps that block them: single-capability plans reach S12 with no params (DR-39), and S15 returns no
   step data (DR-40).
3. **No production semantic assessor.** Steps that require the semantic layer (risk ≥ 0.7 or IRREVERSIBLE) end in a
   dead letter (DR-21).
4. **Admission is partly sourced.** Seven of the eleven gates are hard-coded to pass (DR-26). Gate 10's defect was
   fixed before the tag (DEF-006, `192e993`). The step's budget reservation, the live authorisation check and the
   guard's breaker remain the effective controls.
5. **Security items:**
   - team test keys must be removed (DR-11);
   - EXECUTE on the recovery function must be revoked from PUBLIC (DR-12);
   - DEF-003's predicate is still to be added (DR-09).

## 5. Pre-tag decisions (owner)

All four were taken as option (a) and done before the tag:

| # | Item | Decision | Done |
|---|---|---|---|
| P1 | DR-58: CONF-035 port | (a) port to the certified loop with the same scenarios | `48fa283`: `test_step_loop.py` 26 passed, `test_chain_full_stack.py` 6 passed. The certified loop differs from the prototype in six places (P1-F1–F6): four are columns it never writes (register DR-61–DR-64; those assertions were removed, not changed to the gap), two are by design and pinned with a comment (F5: a revocation found at the pre-call check settles the attempt through the dispatch marker; F6: every step is offered to the verifier). Two prototype verifier cases were dropped (DR-63) |
| P2 | DR-59: schema audit | (a) teach the audit | `009a0e8`: `of` and `s12_recovery_candidates` named as non-tables; 4/4 |
| P3 | DR-55: admission budget gate | (a) record DEF-006 and fix | `192e993` (section 3); test-author's regression test 7/7; goldens M08/M12/M21 and the scan milestones M02/M04/M13 312 passed |
| P4 | DEF-002, DEF-004 | close as fixed | row text in section 3; the owner updates `S12_DEFECTS.md` |

## 6. Issues found and fixed during M15–M21 certification

| Issue | Root cause | Fix | Evidence |
|---|---|---|---|
| M20 run 4/5 failed in the owner's M21 verification | A real race, not a flake. A sweeper acting on a stale candidate list took over a live run between two steps; the takeover did not re-apply CONF-046's released-lease grace | `bdbc915` (`leases.acquire` re-checks the grace under the ownership lock) | reproduced under CPU load (3/10 before, 0/10 after); `tests_agent/test_recovery_takeover_conf046.py` fails before, passes after |
| S0–S11 certifier 18/19 (OWN-11) | the regression test carried a `pytest.skip` guard under `tests/` | `ee9c334` (moved to `tests_agent/`, no skip) | `owner_certify.py` 19/19 |
| M21 marked `reviewed` without a green checkpoint (`f1e4535`) | made outside `owner_verify_s12.ps1` while a row failed | reverted `df957d0`; M21 then certified properly, `3c2a515` | owner run 34/34 |
| Admission gate 10 never refused an over-cost step (DEF-006) | M21 read the risk score as the cost | `192e993` | section 3 |
| Two `tests_postgres` files could not import | CONF-035 port never done; no certifier runs `tests_postgres` | `48fa283` | 32 tests run again |
| Schema audit failed on a SQL keyword and a SQL function | stale parser heuristic | `009a0e8` | 4/4 |
| The verifier's tag prompt showed no commit (`Create tag s12-s15-certified on  (y/n)`) | the checkpoint push was rejected (the remote had moved), so the script had no pushed commit to offer | the owner rebased and pushed the checkpoint (`d6b8ad7`) and created the three tags by hand on the exact commits | tags listed at the top |

## 7. Owner sign-off

| Step | State |
|---|---|
| 1. Review this report, the register and the stage reference | done (this revision) |
| 2. Decide P1–P4 and record them | decided and done in code (section 5). Record rows: CONF-035 applied; DEF-002, DEF-004 closed; DEF-006 added closed. **On GitHub these rows were not yet updated when this revision was written** |
| 3. Review M21 (`s12_tracker.py set M21 reviewed`), commit, push | run by the owner. **The tracker commit was not yet on GitHub when this revision was written** (`S12_TRACKER.md` still read `green`) |
| 4. Owner verification | `owner_verify_s12.ps1 M21` at `c844cdd`: 34/34 PASS |
| 5. Tags | `s12-s15-certified` → `c844cdd`, `s12-m14-certified` → `181b7f5`, `s12-stage2-pinned` → `dac952e`, pushed |
| 6. Backups and protection (`BACKUP_AND_RESTORE.md` §9.1); `s12-work` read-only; `adapters-work` | `adapters-work` created at `d6b8ad7` (see section 8). Mirror, bundle and rulesets: not yet reported |

Sign-off: `owner ______  date 2026-10-03  decision: CERTIFIED  tag commit c844cdd`

## 8. After the tag

Commits pushed to `s12-work` after `c844cdd`. They are **not** covered by this certification; the certified state
is the tag.

| Commit | What | Effect |
|---|---|---|
| `4b3c45c`, `1e53d53`, `ac62822` | adapter proposals rev 11–12; `ADAPTER_IMPLEMENTATION_GUIDE.md` revision 1.1 | documents only |
| `d6b8ad7` | owner checkpoint "M21 green at c844cdd" | progress file |
| `e3e9cae` | A1 per-operation start-up check (`startup.py`), A4 `Observation.observed_state` typed `dict \| None`, A5 `CredentialProvider.credential_valid` declared (`adapter_interface.py`); `tests_agent/test_startup_per_operation.py` (9 cases) | **source change** to two non-frozen, non-pinned files. Its commit reports goldens 896 passed and `owner_certify_s12 --milestone M21 --fast` 27/27; not owner-verified |
| `4132267`, `22b2db6` | records A1, A4, A5 as implemented | documents only |

`adapters-work` was cut at `d6b8ad7`, so it does not contain `e3e9cae`. Decide before adapter work starts: merge
`s12-work` into `adapters-work` (A1/A4/A5 become the first adapter-phase commits) or revert `e3e9cae` from
`s12-work` and redo it on `adapters-work`. Either way, nothing further lands on `s12-work`.
