# Improvement guide for B1 and B2 (M1–M9): extra points, fix method, tests, cross-stage checks

**What this is.** A second-pass review of the **built** B1/B2 code on `s12-work` (not drafts: this code is live and
verified), its guides, golden tests and records. It lists what the golden tests do not fully pin, where the code can
fail silently, what B3–B5 rely on, and the intended behaviours an agent must **not** "fix".

**What it is not.** It does not change the existing flow:

- The milestone guides (`B1_M01-M04/`, `B2_M05-M09/`), the golden files, the autopilot and the owner rows stay as they
  are.
- B1/B2 are built and await owner sign-off. Every change here must be **additive** and justified by an agent test in
  `tests_agent/`.
- Changing a B1/B2 file re-opens its milestone's checks **and** every later milestone that uses it (§3).

**Basis.** The code on `s12-work` (`e8787d1`), the golden tests `tests_golden/s12/M01…M09` and their 33 sabotage
patches, a database built from migrations 001–015 (`B1_M01-M04/SCHEMA.md`), and the records (`S12_RECORDS.md`,
`S12_DEFECTS.md`, `S12_STOPS.md`). Companion: `IMPROVEMENT_GUIDE_B3-B5.md`.

---

## 1. Baseline (verified on plain `s12-work`, PostgreSQL 16, Python 3.11)

| Milestone | Golden cases | Sabotage | Concurrency x5 | Existing agent tests |
|---|---|---|---|---|
| M1 schema ★ | 89 | 4 (SQL) | | — |
| M2 fencing core | 18 | 3 | yes | — |
| M3 machines I | 130 | 3 | | — |
| M4 machines II | 79 | 2 | | — |
| M5 confirmation check | 30 | 3 | yes | `test_m5_confirmation_entry.py` (4) |
| M6 S12 entry | 23 | 3 | | — |
| M7 leases | 15 | 4 | yes | `test_m7_leases.py` (14) |
| M8 admission and selection | 40 | 4 | | `test_m8_admission_selection.py` (16) |
| M8a worker management ★ | 49 | 3 | yes | `test_m8a_worker_mgmt.py` (21) |
| M9 budget | 17 | 4 | yes | `test_m9_budget.py` (9) |
| **Total** | **490** | **33** | | **64** |

Also: `pytest tests` 836, `tests_agent` 93 (64 of them B2), `tests_postgres` 330, S0–S11 certifier 19/19 (with
`PYTHONPATH=src`). `owner_certify_s12.py --milestone M9` is 18/21: only owner rows fail (S12-PIN, S12-REC), plus
S12-S011 when the package is not importable.

**Coverage hole:** **M1–M4 have no agent tests at all.** Their only guards are the golden files and 12 sabotage
patches. Several items below add the first ones.

---

## 2. Method (stricter than for B3–B5, because this code is already built)

```text
1. LOCATE    the item's file:line; read the milestone's golden docstring and its guide.
2. PROVE     add the agent test named in the item (tests_agent/test_imp_mXX_*.py). If it PASSES on s12-work,
             keep it as a guard and STOP: nothing to fix. Most B1/B2 items are guards.
3. FIX       only if the test is red, and only additively: a new optional parameter, a new helper, a new check
             that the pinned golden cases still satisfy. Never change a value, a reason string, a signature, a
             CHECK constraint or a migration 001–015.
4. VERIFY    a) the agent test; b) the owning milestone's golden file + its sabotage patches (and x5 if it has a
             C-row); c) ALL of M01–M09 (B1/B2 share fixtures and invariants); d) every downstream consumer in §3
             that is built on your machine (B3–B5); e) tests 836, tests_agent, tests_postgres 330; f) both
             certifiers with PYTHONPATH=src.
5. RECORD    "s12: Mxx IMP-nn <what>"; one log line (append only). A behaviour change to a ★ milestone (M1, M8a)
             goes into the owner's review notes.
6. STOP      for anything frozen (S0–S11, e.g. confirmations.py), pinned (tests_golden/**), owner-only (pins,
             statuses, rulings), or "by design" (§5).
```

**Agent-test rules:**

- Reuse the golden fixtures (`db_schema`, `run`, `tests_golden.fixtures.invariants`) and the existing `tests_agent`
  helpers.
- Import from `src/`, never from `batch_bundles/`.
- Database tests need `TEST_DATABASE_URL` ending in `_test`.

---

## 3. Cross-stage dependency map: who stands on B1/B2

| B1/B2 artefact | Used by (golden files / later code) | A change here must re-run |
|---|---|---|
| `contracts.execution_states` (M1) | every S12–S15 module; every CHECK in 001–015 | M01, M03, M04 + everything built |
| migrations 001–015 (M1) | all of M2–M21; the B3–B5 drafts expect them **byte-identical** | never change; add 016+ |
| `fencing.FenceHolder`, `fenced_write`, `check_fence` (M2, M9) | 8 imports in M10–M21 goldens; every repository | M02 (x5), M07, M09, M12–M21 |
| `transition_log.log_transition` (M2) | every repository; I5 reads its rows | M02–M09, and I5 everywhere |
| `transitions.validate`, `IllegalStateTransition`, `RUN`/`STEP`/`BUDGET` (M3/M4) | M17 golden (A.6), M17 `settle_dead_letter_reservation`, the prototype loop | M03, M04, M17 |
| `settings.ExecutionSettings` (M2, M8a, M9) | M21 golden; M19 adds a field | M02, M08a, M21 |
| `admission_control.AdmissionSnapshot`, `admit_step`, `reject_outcome` (M8) | 10 imports in M12–M21 goldens (`PASSING`, `circuit_open=True`); the loop | M08, M12–M21 |
| `selection.lease_for_step`, `eligibility.*` (M8, M8a) | the loop (M12); M12 adds `step_context`, `binding_requirements` | M08, M08a, M12 |
| `leases.PostgresLeaseManager` (M7) | the loop; M19 golden (`release`, `expire_lapsed`); M12 adds `holder=`, M19 `skip_locked=` | M07 (x5), M12, M19, M20 (x5) |
| `budget_reserver.PostgresBudgetReserver` (M9) | M10/M11 goldens (`reserve`, `lock`), M10 `BudgetTracker` (`reservation`), the loop (`lock(connection=)`), M17 settle | M09 (x5), M10–M13, M17 |
| S12 entry (`check_entry`, `admit_run`, `PostgresExecutionAdmission`, `PostgresSelectionReader`) (M5–M8a) | M12's `_admit`/`_deps` helpers, used by **every** golden from M12 to M21 | M05–M08a, then M12–M21 |
| `confirmation_records`, `s12_entry.confirmation` (M5) | entry only | M05 (x5), M06 |

---

## 4. Improvement items

Format: **ID — title.** Why · File(s):line · Fix method · Agent test · Validate. "Guard" means the code is
already right on `s12-work` and the test only keeps it that way.

### 4.1 Cross-cutting

**IMP-B-X1: Every transition-log write is preceded by a reason check.**
- Why: `log_transition` does not validate (by design, M2). Two writers call it after a **pair-only** check:
  - `adapters/postgres/execution.py:93` (`check_step`) and `:117` (`check_run`), the prototype store;
  - so reasons are not checked there. This is the root of **DEF-002** (non-Appendix-A loop reasons).
  - `budget_reserver.py:88, :121` validate correctly.
- Fix: none in B1/B2. M12's `PostgresExecutionStore` replaces those calls with `transitions.validate(..., reason=)`.
  Do not "fix" the prototype store separately: it disappears with M12.
- Agent test: `tests_agent/test_imp_b_x1_log_after_validate.py`, an AST scan. Every function that calls
  `log_transition`, or a `_log` wrapper, also calls `transitions.validate` (allow-list `execution.py` until M12, then
  remove the entry).
- Validate: I5 in every integration case; M12.

**IMP-B-X2: Rules the database does not enforce.**
- Why: `SCHEMA.md` "Where the database enforces a rule". These rules exist only in code:
  - `state_transitions.reason` is nullable;
  - nothing in the schema prevents a second active lease per execution;
  - the budget ceiling and commit-only-from-LOCKED.
- Fix: none (no migration 001–015 may change). An optional **016+** constraint such as `reason IS NOT NULL` is a
  schema change outside every card, so it needs an owner ruling.
- Agent test: `tests_agent/test_imp_b_x2_only_code_writes.py`, a scan. No S12 module issues
  `INSERT INTO worker_leases` outside `leases.py`, `INSERT INTO budget_reservations` outside `budget_reserver.py`, or
  `INSERT INTO state_transitions` outside `transition_log.py`.
- Validate: M07, M09, I5, I7, I8, I1.

**IMP-B-X3: Tenant filter on every query, including later code.**
- Why: C34. The M02 scan checks S12 SQL at the time it runs; later files are added by B3–B5.
- Fix: none.
- Agent test: run `tests_golden/s12/M02_fencing_core.py::test_every_s12_query_filters_on_tenant_id` after every
  B3–B5 commit (it scans all S12 files). It is one fast command.
- Validate: M02.

**IMP-B-X4: First agent tests for M1–M4 (coverage hole).**
- Why: §1. B1 has zero agent tests.
- Add:
  - `tests_agent/test_imp_m01_enum_check_parity.py`: for every `CHECKED` column (M01 golden list), compare the live
    CHECK values with the enum. This duplicates a golden case on purpose, so a future 016+ migration that widens a
    CHECK by hand is caught in `tests_agent` too.
  - `tests_agent/test_imp_m03_reason_codes_in_code.py`: every reason **literal** passed to `validate(...)` anywhere in
    `src/` exists in `transitions._EDGES` or `_INITIAL` (catches a typo the golden only finds when that path runs).
- Validate: M01, M03.

**IMP-B-X5: Certifier environment.**
- Why: `owner_certify.py` reports 16/19 with 22 collection errors when `src` is not importable. An agent may "fix"
  code for it.
- Fix: run with `PYTHONPATH=src` or after `pip install -e .`. Put this in your VPS shell profile and CI.
- Validate: S0–S11 19/19.

### 4.2 B1: M1–M4

**IMP-M01-1: Never touch 001–015; extend with 016+.**
- Why: CONF-010; the B3–B5 drafts are byte-identical on 001–015.
- Agent test: `tests_agent/test_imp_m01_migrations_frozen.py`. The SHA-256 of each of 001–015 equals the value
  recorded in the test (computed once from `s12-work`).
- Validate: M01 `test_new_migrations_are_new_files`.

**IMP-M01-2: Unused columns stay unused, and say so.**
- Why: `SCHEMA.md`: 14 columns no code reads or writes (`workers.heartbeat_at`, `drain_state`, …;
  `dead_letters.is_idempotent`, `next_retry_at`; `checkpoints.*`).
- Fix: none. Do not start reading them as if they held information.
- Agent test: none. List them in the M21 deferred register.

**IMP-M01-3: `workers.worker_class` is NOT NULL without a default.**
- Why: any worker registration (not S12 code; test fixtures do it) must supply it. A future registration path that
  omits it fails at insert time.
- Fix: none in this phase. Note it for the worker-lifecycle phase.

**IMP-M02-1: Fence lock strength.**
- Why: `fencing.py:21-23` uses `FOR SHARE` on purpose: concurrent fenced writes of one execution do not block each
  other, and a takeover's `UPDATE` waits for them. Changing it to `FOR UPDATE` serializes every write of a run;
  removing it reintroduces the race (sabotage `M02_check_without_lock`).
- Agent test (guard): `tests_agent/test_imp_m02_fence_lock_mode.py` asserts the `_FENCE` SQL ends with `FOR SHARE`.
- Validate: M02 (x5).

**IMP-M02-2: Settings: a step longer than the lease.**
- Why: `settings.py:51-56` check C37 only. Nothing relates `step_timeout_s` to `lease_ttl_s`, and the pinned valid
  settings use 30 / 30. Without renewal (CONF-045, open), a step that outlives the TTL can be taken over.
- Fix: **no hard check** (it would fail M02 and M21). At most a startup WARNING when `step_timeout_s >= lease_ttl_s`,
  until CONF-045 is ruled. Same item as IMP-X7 in the B3–B5 guide.

**IMP-M02-3: Settings types.**
- Why: `settings.py:47-50`. Every field must be > 0, and the quota count fields must be `int`.
- Agent test (guard): `from_env` with `S12_QUOTA_RETRY_MAX=2.5` → `ValueError`; with `S12_QUOTA_BACKOFF_S=0` →
  `ValueError`.
- Validate: M02 settings cases, M08a.

**IMP-M03-1: Not-produced edges accept any reason.**
- Why: `transitions.py:66-69` (`running → partial`, `unknown → pending_probe`, `unknown → dead_letter`) use
  `ANY_REASON`, so `validate` accepts any non-empty reason there. That is safe only because nothing produces those
  edges.
- Agent test: `tests_agent/test_imp_m03_unproduced_edges_unused.py`, a scan. No S12–S15 code moves a step to
  `partial`, or from `unknown`; combined with M03's "no code writes UNKNOWN".
- Validate: M03.

**IMP-M04-1: Renewal changes the fence token (cross-stage trap).**
- Why: `leases.py:121-145`. `renew` returns a lease with a **new, larger** token and moves ownership to it. Any
  `FenceHolder` built from the old lease is then fenced out. This matters as soon as lease renewal during a step is
  built (CONF-045, M20/M21 or the fleet phase).
- Fix: whoever adds renewal must replace the holder after every `renew` (see the B5 guide).
- Agent test: `tests_agent/test_imp_m07_renew_rotates_holder.py`. After `renew`, `fenced_write` with the old token
  raises `FencedOut` and the new token writes.
- Validate: M07 (x5), M12.

### 4.3 B2: M5–M9

**IMP-M05-1: DEF-003 (owner).**
- Why: the frozen `adapters/postgres/confirmations.py:32-50` UPDATEs lack `AND tenant_id = :t`; forced RLS is the only
  guard.
- Fix: **none by the agent** (frozen). The owner decides between §19.3 change control and accepting RLS.
- Agent test (guard, allowed because it changes no frozen file):
  `tests_agent/test_imp_m05_cross_tenant_consume_blocked.py`. As the app role `golden_app`, consuming tenant A's
  confirmation with tenant B's id updates 0 rows.
- Validate: M05.

**IMP-M05-2: `user_id` read but not compared.**
- Why: `s12_entry/confirmation.py:36-39`. By design: C20 binds tenant, execution and plan hash; S10's consume binds the user.
- Fix: none. C20 does not ask for it; adding one would be new behaviour that needs a ruling.

**IMP-M06-1: Entry denial order.**
- Why: `checks.py:103-179`. Order 1, 1a, 2, 3, 4, 5, 5a, 5b, 6, 7, C20. The golden tests one failure at a time.
- Agent test: `tests_agent/test_imp_m06_denial_precedence.py`. A state that fails both 5 (`plan_integrity`) and 7
  (`tenant_paused`) is denied `plan_integrity`; one that fails both 5b and C20 is denied with the 5b reason, and the
  confirmation reader is **not** read.
- Validate: M06.

**IMP-M06-2: Registry version bump denies certified plans (CONF-008).**
- Why: the fail-closed rule is accepted for this phase. After any `registry_versions` bump, every plan certified
  earlier is denied `binding_version_mismatch`.
- Fix: none. Operational note: a registry bump must not happen while runs are being admitted. Put it in the M21
  deferred register.

**IMP-M06-3: Immutable manifest and plan.**
- Why: triggers `execution_manifests_immutable` / `execution_plans_immutable` (`reject_update()`, migration 009).
- Agent test (guard): an `UPDATE execution_plans …` after admission raises.
- Validate: M06 (I9).

**IMP-M07-1: One owner per execution is a lock, not a constraint.**
- Why: `leases.py` `acquire` serializes on the ownership row (`FOR UPDATE`); there is no unique index.
- Fix: none. See IMP-B-X2's scan.
- Agent test: `tests_agent/test_imp_m07_parallel_acquire_two_workers.py`. 10 concurrent `acquire` calls for one
  execution on 10 different workers produce exactly 1 active lease. The golden tests capacity per worker; this tests
  the per-execution side under heavy concurrency.
- Validate: M07 (x5).

**IMP-M07-2: `release` returns False silently.**
- Why: `leases.py:148-164` returns `False` when the lease already left `active` (released before, or expired by an
  acquisition).
- Fix: callers (the M12 loop) should log a WARNING with the lease id when it is False; the release itself stays as is.
- Agent test: a double release returns `True` then `False`, with exactly one `released` transition row.
- Validate: M07; M12 lease-bracket cases.

**IMP-M08-1: Hard-coded retry timings (§21 S1).**
- Why: `admission_control.py:24-25` (`QUEUE_RETRY_AFTER_MS = 1000`, `DELAY_RETRY_AFTER_MS = 500`). The M8 log noted
  "retry delays to settings" for M12.
- Fix: optional `ExecutionSettings` fields with these defaults. **Never** change the defaults (golden M08 checks that
  `retry_after_ms` is present). Same item as IMP-X8 in the B3–B5 guide.
- Agent test: `tests_agent/test_imp_m08_timings_from_settings.py`.
- Validate: M08, M12, M21.

**IMP-M08-2: The snapshot is bool-only.**
- Why: `AdmissionSnapshot.__post_init__` raises `TypeError` on non-bool values. A future producer (CONF-027,
  production admission sources) reading `0`/`1` or `None` from SQL breaks every step.
- Agent test (guard): `AdmissionSnapshot(**{**PASSING, "circuit_open": 0})` raises `TypeError`. The producer must
  cast to `bool`.
- Validate: M08, M12.

**IMP-M08a-1: The quota transaction is ordered and bounded.**
- Why: `admission.py:125` locks tenant-level then workspace-level rows `ORDER BY quota_id FOR UPDATE` (no deadlock),
  then retries a soft quota `quota_retry_max` times with `asyncio.sleep(backoff × attempt)` (`:82-92`).
- Agent test: `tests_agent/test_imp_m08a_quota_no_deadlock.py`. 20 concurrent entries against a tenant **and** a
  workspace quota both at 5: exactly 5 admitted, no deadlock error, and each row's `used_count` is 5.
- Validate: M08a (x5), I17.

**IMP-M08a-2: Filter inputs are database time.**
- Why: `selection.py` returns times as database epoch, and `ctx.now` must come from `database_now()`. Mixing in
  `time.time()` silently mis-filters paused workers on a clock-skewed host.
- Agent test: an AST scan. `eligibility.py` and `selection.py` never call `time.time()` / `datetime.now()`.
- Validate: M08a.

**IMP-M09-1: The budget period is by creation time (intended).**
- Why: `budget.py:17`. Availability counts reservations **created** in the current period. A LOCKED reservation from
  last period that commits now does not reduce this period's pool (C33).
- Fix: none. This is the gate's rule. Do not "fix" it to count by commit time.
- Agent test (guard): reserve and lock a reservation, then (as the superuser fixture) backdate its `created_at` into
  the previous period. The current period's availability is the full pool again, while I1 still holds for each
  period.
- Validate: M09 `test_only_the_current_period_counts`.

**IMP-M09-2: I12 lives in the database too.**
- Why: `uq_budget_reservation_open_step` (partial unique). A second live reservation for a step raises a unique
  violation, not a clean domain error.
- Fix: `reserve` already returns the live one (idempotent). Callers must never insert directly (IMP-B-X2).
- Agent test (guard): two concurrent `reserve` calls for one step return the same `reservation_id`.
- Validate: M09 (x5), M13 NOT_EXECUTED retry.

**IMP-M09-3: `lock(connection=)` joins and re-checks the fence.**
- Why: I-3; the M12 loop depends on it (DEF-004).
- Agent test (guard): inside one `fenced_write`, move the step `pending → running`, call `lock(..., connection=c)`,
  then raise. Both moves roll back and no reservation is `locked`.
- Validate: M09 (`M09_lock_in_own_transaction`), M12 (IMP-M12-1 in the B3–B5 guide).

---

## 5. Intended behaviour: do NOT "fix" these

| Behaviour | Where | Why it is right |
|---|---|---|
| `fenced_write` locks `FOR SHARE` | `fencing.py:23` | concurrent writes of one owner; a takeover waits |
| availability counts by `created_at` period | `budget.py:17` | C33 |
| a confirmation's `user_id` is not compared | `s12_entry/confirmation.py` | C20 scope; S10 already bound the user |
| gates 7, 8, 9 and 11 never REJECT directly | `admission_control.py` | C30, CONF-017, CONF-032 |
| quota consumed once at entry, never per step | `admission.py` | §7.2, C39 |
| pause checked at entry, not per step | `checks.py` item 7 | C39; mid-run pause is M14's "cancels nothing" |
| `pending → cancelled` excludes `budget_exhausted` | `transitions.py` | no budget is spent before admission |
| durable admission writes without a fence | `admission.py` | it creates the ownership row (README rule 7) |
| `bindings` has no RLS; confirmations have no FK to runs | migrations 001/009 | global registry; C20 |
| a registry bump denies older plans | `checks.py` 5b | CONF-008 (fail closed) |
| worker pause and activation are columns, not states | 015, `eligibility.py` | C39 (M04 case) |

---

## 6. Validation runbook

```bash
export TEST_DATABASE_URL=postgresql://…/<name>_test PYTHONPATH=$PWD/src
git diff origin/s12-work -- tests_golden docs/gates/*.sha256                       # empty
python tools/owner_certify_s12.py --selftest && python tools/owner_certify.py      # OK, 19/19
for f in tests_golden/s12/M0*.py; do python -m pytest -q "$f" || break; done      # 490 in total
python tools/owner_certify_s12.py --milestone M9                                   # 18/21: only owner rows fail
python -m pytest -q tests tests_agent && python -m pytest -q tests_postgres        # 836 + agent, 330
python -m pytest -q tests_agent/test_imp_*.py                                     # this guide's tests
# if B3–B5 are built on this machine: re-run their golden files (IMPROVEMENT_GUIDE_B3-B5.md §5)
```

**Done** for an item: its agent test passes; M01–M09 (490) and the 33 patches still pass and are caught; every
downstream file in §3 that exists on your machine passes; the regression counts hold.

---

## 7. Item index

| ID | Milestone | Kind | Ruling? |
|---|---|---|---|
| B-X1 log after validate | M2/M12 | scan; resolved by M12 | no |
| B-X2 rules only code enforces | M2, M7, M9 | scan | 016+ constraint needs one |
| B-X3 tenant filter | all | re-run golden scan | no |
| B-X4 first M1–M4 agent tests | M1, M3 | new tests | no |
| B-X5 certifier environment | — | process | no |
| M01-1 migrations frozen | M1 | hash test | no |
| M01-2 unused columns | M1 | deferred register | owner |
| M01-3 `worker_class` NOT NULL | M1 | note | later phase |
| M02-1 fence lock mode | M2 | guard | no |
| M02-2 step vs lease TTL | M2 | warning only | CONF-045 |
| M02-3 settings types | M2 | guard | no |
| M03-1 not-produced edges | M3 | scan | no |
| M04-1 renewal rotates token | M7 (B1 machine) | guard; affects renewal work | CONF-045 |
| M05-1 DEF-003 | M5 | guard test only | **owner** |
| M05-2 `user_id` | M5 | by design | no |
| M06-1 denial precedence | M6 | test | no |
| M06-2 registry bump | M6 | deferred register | CONF-008 |
| M06-3 immutable manifest/plan | M6 | guard | no |
| M07-1 parallel acquire | M7 | test | no |
| M07-2 silent release False | M7/M12 | log in caller | no |
| M08-1 timings to settings | M8 | additive | no |
| M08-2 bool-only snapshot | M8 | guard; note for CONF-027 | CONF-027 sources |
| M08a-1 quota ordering | M8a | test | no |
| M08a-2 database time only | M8a | scan | no |
| M09-1 period by creation | M9 | guard (by design) | no |
| M09-2 I12 in database | M9 | guard | no |
| M09-3 joined lock rollback | M9 | guard | no |
