# B3 entry pre-flight sheet (M10–M14)

Prepared 2026-10-01 at `s12-work` HEAD `2891cda`. Read it top to bottom once. Part O is owner-only and must be
finished **before** the agent session starts. Part A is the agent's first 20 minutes of that session. Everything else
in the session is the normal `S12_AUTOPILOT.md` loop.

**Nothing in this sheet was run in the session that wrote it.** Every "expected" number below comes from the
repository's own records:
- `tests_golden/README.md`;
- `docs/gates/S12_B3_REVIEW.md`, `S12_B5_REVIEW.md`;
- `docs/gates/s12_autopilot_log.md`;
- the case additions in `150a668`, counted from the diff.

Step A2 re-measures them. A difference is not a failure by itself, but it must be explained before the first code
change.

## Where things stand (why the first session would otherwise be discovery)

| Fact | Evidence | Consequence if not fixed before the session |
|---|---|---|
| Code is built through M9; nothing from M10 on is implemented | log `c377a8d` "M9 reached"; no `reliability.py` / `idempotency.py` / `probe.py` in `src/` | — (this is the starting point) |
| The tracker still says M1 `red_confirmed`, M2–M9 `not_started` | `docs/gates/s12_milestones.json` | AUTOPILOT session start step 2 picks **M1** ("first row … not green/reviewed") and the session re-certifies M1 instead of starting M10 |
| The pins cover B1 only, and three pinned files have changed since | `s12_pins.sha256` lists M01–M04 only; `tests_golden/README.md`, `fixtures/db.py`, `fixtures/invariants.py` differ from their pins (B2/B5 fixture work) | S12-PIN FAILs at every target: the "changed" lines, plus "not pinned" for every B2–B5 file |
| STOP-001 `ruled`; STOP-002, STOP-004, STOP-005 `open` | `S12_STOPS.md:13-17` | S12-REC FAILs for M10 (it blocks on `open` **and** `ruled` STOPs, `owner_certify_s12.py:144`) |
| M8 code and the M08 golden changed **after** M8 was reached | `2cd2f9d` (DEF-005), `150a668` (CONF-032): `admission_control.py` and `M08_admission.py` | No certifier run has re-proved M8 under the 40-case golden; the owner checkpoint O4 does |
| `batch_bundles/` holds an unreviewed reference implementation of M10–M21 | `batch_bundles/B4_M15-M18/MANIFEST.md:7-9` | Without a rule, an agent may copy it into `src/`; see O1 |
| `tests_golden/README.md` counts are stale for M08 (39 → 40) and M14 (27 → 28) | `150a668` adds one parametrize value to M08 and one case to M14 | Only cosmetic, but A2 would otherwise look like a discrepancy |

Expected certifier result **today** for `--milestone M10 --fast`: S12-PIN FAIL and S12-REC FAIL, G-M10 FAIL; the other
13 rows PASS. Expected after Part O: **15/16, only G-M10 FAIL.**

---

## Part O — owner close-out rows (B1, B2, and the B3 gate)

Run these on the master folder (`C:\Users\Administrator\Documents\1SuperAgents`) in a fresh PowerShell, in this order.
Each row gives its exact check.

```powershell
cd C:\Users\Administrator\Documents\1SuperAgents
$env:PYTHONUTF8 = "1"
git fetch origin s12-work; git pull --ff-only origin s12-work      # HEAD must be 2891cda or later
git status --porcelain                                              # must print nothing
```

| # | Row | Command / edit | Done when |
|---|---|---|---|
| O1 | **Decide the `batch_bundles/` rule** (decision) | Recommended: the agent may **read** it for orientation but never copies a file or a block into `src/`; every module is written against the golden docstring. Record it as one line in `s12_autopilot_log.md` (append-only), or move the folder out of the repository. Note: the reference was written by the same author as the goldens, so copying it removes the only independent check that the goldens are satisfiable by someone else's code. | A log line or a commit removing the folder |
| O2 | *(optional)* Refresh the README counts | Edit `tests_golden/README.md`: M08 40, M14 28, M01–M09 490, M01–M14 674. Commit. | Commit exists **before** O3 (pinning freezes the README) |
| O3 | **Re-pin** (closes STOP-001's "pin before the checkpoint" and makes B2/B3 pinned) | `python tools\owner_certify_s12.py --selftest` (every row OK), then `powershell -ExecutionPolicy Bypass -File tools\owner_pin_s12.ps1`. It refuses if `tests_golden` or `tools` is dirty. It pins **every** file under `tests_golden/`, B4/B5 drafts included: S12-PIN fails on any unpinned file in a pinned area, so there is no B3-only pin. That is safe, because the open M15/M19/M20 CONF rows still block those milestones through S12-REC. The ruling pack's golden amendments (M18, M19, M20, M21) then need one more re-pin later. | Commit "Owner: pin S12 golden set…" pushed. `python tools\owner_certify_s12.py --milestone M10 --fast` shows S12-PIN PASS |
| O4a | **STOP rows → applied** | Edit `docs/gates/S12_STOPS.md` (owner columns only), Status cell (third column) → `applied`:<br>• **STOP-001**: Ruling "owner 2026-09-30: start M1 unpinned; pinned abfff2f, re-pinned <O3 commit>"; Applied `<O3 commit>`<br>• **STOP-002**: "B2 drafted (f40a5a6…9f30cef), built M5–M9, pinned <O3>"; Applied `<O3 commit>`<br>• **STOP-004**: see `S12_RULING_PACK.md` § STOP-004; Applied `<O3 commit>`<br>• **STOP-005**: see § STOP-005; Applied `150a668, <O3 commit>`<br>Commit and push. | `python tools\s12_tracker.py check` prints no STOP for M1–M10 |
| O4b | **Tracker backfill M1 → M9 with owner checkpoints** | The tracker moves one step at a time (`s12_tracker.py:152-154`). `owner_verify_s12.ps1` only performs the last step (`set Mxx green`) and **refuses a dirty tree**, so commit the earlier steps first. Exact sequence below. | `s12_milestones.json`: M1 `reviewed`, M2–M8 `green`, M8a `reviewed`, M9 `green` |
| O5 | **M1 ★ review** | Checklist below; then `python tools\s12_tracker.py set M1 reviewed`; commit. | M1 `reviewed` |
| O6 | **M8a ★ review** | Checklist below; then `python tools\s12_tracker.py set M8a reviewed`; commit. | M8a `reviewed` |
| O7 | **Final gate check** | `python tools\owner_certify_s12.py --milestone M10 --fast` | **15/16 PASS; the only FAIL is G-M10** with "64 tests, 63 failed". Anything else: fix before the session |
| O8 | Hand-off line | Tell the agent: `continue per S12 AUTOPILOT` (and the O1 rule, if not logged) | — |

### O4b — exact backfill sequence

`owner_verify_s12.ps1 Mxx` re-runs the **full** certifier for M0..Mxx: every earlier golden, the sabotage of Mxx, and
x5 for M2, M5, M7, M8a and M9. It then commits the `green` move and pushes. Budget for nine full runs. The sabotage
runs of M1..M8a are checked **only** in their own milestone's checkpoint (`owner_certify_s12.py:261-262`), so none can
be skipped.

```powershell
# M1 (red_confirmed -> in_progress -> green -> reviewed)
python tools\s12_tracker.py set M1 in_progress
git add docs\gates\s12_milestones.json docs\gates\S12_TRACKER.md; git commit -m "Owner: M1 in_progress (backfill)"
powershell -ExecutionPolicy Bypass -File tools\owner_verify_s12.ps1 M1
#   -> O5 review, then:
python tools\s12_tracker.py set M1 reviewed
git add docs\gates\s12_milestones.json docs\gates\S12_TRACKER.md; git commit -m "Owner: M1 reviewed"; git push origin s12-work

# M2 .. M9 (not_started -> red_confirmed -> in_progress -> green), one milestone at a time, in this order:
foreach ($m in "M2","M3","M4","M5","M6","M7","M8","M8a","M9") {
  python tools\s12_tracker.py set $m red_confirmed; if ($LASTEXITCODE) { throw "$m red_confirmed refused" }
  python tools\s12_tracker.py set $m in_progress;   if ($LASTEXITCODE) { throw "$m in_progress refused" }
  git add docs\gates\s12_milestones.json docs\gates\S12_TRACKER.md
  git commit -m "Owner: $m status backfill (red confirmed at draft time, see tests_golden/README.md)"
  powershell -ExecutionPolicy Bypass -File tools\owner_verify_s12.ps1 $m; if ($LASTEXITCODE) { throw "$m NOT REACHED" }
  if ($m -eq "M8a") { break }   # stop for the O6 review; M8a must be 'reviewed' before M9 can advance
}
#   -> O6 review, then:
python tools\s12_tracker.py set M8a reviewed
git add docs\gates\s12_milestones.json docs\gates\S12_TRACKER.md; git commit -m "Owner: M8a reviewed"; git push origin s12-work
#   -> run the loop body once more for M9
```

`red_confirmed` is a backfill. Red was confirmed when each golden was drafted (README "Red on `s12-work`" columns:
M02 16/18 … M09 16/17). The commit message says so, so the history does not claim a re-run that did not happen.

If a checkpoint fails ("NOT REACHED"), the FAIL rows name the cause. The likely ones:
- **M8**: the post-M8 changes in `150a668` and `2cd2f9d`.
- **M1–M4**: fixture drift in `db.py` and `invariants.py`.

Stop there and hand the FAIL lines to an agent session as a defect (DEF-nnn), not as M10 work.

### O5 — M1 ★ review checklist (B1: M1–M4)

- **CONF-014** asks the owner to confirm at this review that `idx_workers_workspace` is created together with
  `workers.workspace_id`: `S12_RECORDS.md:25`, `015_s12_schema.sql`.
- **CONF-007**: `operation_quotas.worker_id`, `CHECK (worker_id IS NULL)` and the gate's unique key are in migration 015.
- **CONF-006**: no S12 import of `contracts.state_validators`. This is enforced by
  `M03 test_s12_code_does_not_use_the_non_canonical_validator`.
- **CONF-010**: the 30 M01 cases that passed before M1 are fixture/standing rules (README list), not M1 work.
- Migrations 001–014 are untouched: `git diff s0-s11-certified -- src/adapters/postgres/migrations/00*.sql src/adapters/postgres/migrations/01[0-4]*.sql`
  is empty.
- Note for later: the M03 rule against `StepState.UNKNOWN` can be evaded with an alias. See `S12_RULING_PACK.md`,
  proposed CONF-048 (an M19 issue, not an M1 defect).

### O6 — M8a ★ review checklist

- **CONF-019** (`24e2296`): `PostgresSelectionReader.required_runtime_types` reads the binding row once at entry.
  `runtime_type` appears only in the three files `M08a_worker_mgmt.py:384` allows.
- **CONF-020**: the recorded ruling has **no implementation path** (an entry DENY creates no run; M18 has no
  `quota_exhausted` case). Accept M8a as is: entry returns `quota_exhausted` with `retry_after_ms`, which M8a pins.
  Carry the amendment in `S12_RULING_PACK.md` § CONF-020 to M18.
- **STOP-003** is `applied`. **CONF-016**: filter 14 is a pure function of `SelectionContext`.
- x5 concurrency on the 20-way quota test was part of the O4b M8a checkpoint (C-M8a row).
- No DEF has milestone M8a (the tracker would refuse `reviewed` otherwise).

---

## Part A — the agent session's entry (first commands, before any code)

### A0. Environment

| Variable | Windows (owner box) | Linux (cloud session) | Why |
|---|---|---|---|
| Python | 3.11+, `.venv` in the repo, `pip install -e ".[dev]"` | `python3.11 -m pip install -e ".[dev]"` | `pyproject.toml:7` |
| `PYTHONUTF8` | `1` | `1` | the certifiers set it for their children; set it for manual runs too |
| `PYTHONPATH` | `src;.` | `src:.` | identical to what `owner_certify_s12.py:125` sets: `src` for `contracts.*`/`engine.*`/`adapters.*`, root for `tests_golden.fixtures.*` |
| `TEST_DATABASE_URL` | from `.env` | export it | **superuser** connection (the golden harness refuses otherwise; code under test runs as `golden_app`), database name **must end in `_test`**, PostgreSQL 16 |
| Database | the master's `suprpg_test` | `createdb supragents_test` | each golden module creates, migrates and drops its own schema |

Never print `.env` values (AUTOPILOT guardrail).

### A1. Session start (AUTOPILOT steps 1–4, made concrete)

```bash
git status --porcelain && git log --oneline -15
python -c "import json;print(next(m['id'] for m in json.load(open('docs/gates/s12_milestones.json'))['milestones'] if m['status'] not in ('green','reviewed')))"
#   must print M10. If it prints M1..M9, Part O was not finished: STOP, do not re-certify old milestones
python tools/owner_certify_s12.py --selftest                   # every row OK, else STOP
python tools/owner_certify_s12.py --milestone M10 --fast       # expected 15/16, only G-M10 FAIL (63 failed)
tail -15 docs/gates/s12_autopilot_log.md
grep -E "^\| CONF-[0-9]+ \|[^|]*\| open \|" docs/gates/S12_RECORDS.md     # expected: CONF-005, CONF-042..047 only
grep -E "^\| STOP-[0-9]+ \|[^|]*\| (open|ruled) \|" docs/gates/S12_STOPS.md  # expected: nothing
```

Always pass `--milestone M10`, `M11` and so on explicitly. Without it the certifier picks the first non-green row of
the JSON, which the agent must not edit.

### A2. Baseline: what must already be green (regression floor for every B3 commit)

| Command | Expected |
|---|---|
| `python tools/owner_certify.py` | `19/19 PASS` (S12-S011 / OWN-13) |
| `python -m pytest tests -q` | 836 passed |
| `python -m pytest tests_postgres -q` | 330 passed (log `c377a8d`). **Drops at M12 by design**: `test_step_loop.py` and `test_chain_full_stack.py` import the prototype loop and must be **ported, never deleted** (CONF-035) |
| `python -m pytest -q -p no:cacheprovider tests_golden/s12/M01_schema.py … M09_budget.py` | 490 passed: M01 89, M02 18, M03 130, M04 79, M05 30, M06 23, M07 15, M08 **40**, M08a 49, M09 17 |
| same plus `tests_agent` | 583 passed (`S12_B5_REVIEW.md`) |

### A3. Expected red per B3 golden file (on `s12-work` before any M10 code)

Run each file alone: `python -m pytest -q -p no:cacheprovider tests_golden/s12/<file>`.

| File | Milestone · model | Cases | Expected on `s12-work` | Sabotage patches (X-row) | Cases that already pass, and why |
|---|---|---|---|---|---|
| `M10_guard.py` | M10 · opus | 64 | **63 failed, 1 passed** | 10 | 1 standing rule (README: "1 standing rule passes") |
| `M11_idempotency_retry.py` | M11 · opus | 46 | **45 failed, 1 passed** | 10 | 1 case (README: "1 passes") |
| `M12_loop.py` | M12 · sonnet | 33 | **29 failed, 4 passed** | 8 (2 are `.sql`) | prototype topological order + standing rules |
| `M13_probe.py` | M13 · opus | 13 | **13 failed** | 4 | — |
| `M14_revocation_cancel.py` | M14 ★ · opus | **28** | **28 failed** | 7 | — (27 in the README + `test_a_persistent_provider_outage_ends_as_admission_exhausted_never_cancelled`, `150a668`) |
| **B3 total** | | **184** | **178 failed, 6 passed** | **39** | |

**Red for the right reason:** every failure must be a missing module or attribute (`ModuleNotFoundError` /
`ImportError` / `AttributeError` raised inside the test body). The goldens import inside each case, so the cases fail
one by one. Zero **errors** are allowed: a collection or fixture error means the harness or the database is wrong,
not that M10 is unbuilt (and the certifier refuses errors on X-rows). None of the B3 milestones is in the x5
concurrency set (`owner_certify_s12.py:53`), so a full B3 checkpoint is G-rows plus its X-row only.

Interfaces each file fixes are in its docstring and summarized in `tests_golden/README.md` "Batch B3 status". Build
exactly those, nothing deferred.

### A4. Per-milestone notes for B3 (rulings and records that apply)

| Milestone | Rulings to apply (all `ruled`) | Records to close in this milestone | Traps |
|---|---|---|---|
| M10 | CONF-021 (frozen `AdapterResult`, `ErrorClass` in `contracts.adapter_interface`), CONF-022 (breaker per provider), CONF-023 (4xx trial releases HALF_OPEN; escaping `TimeoutError` = `timeout`) | — | The prototype `s12_execute/guard.py` and `adapters/runtime/circuit_breaker.py` are prototype (CONF-011) and frozen `bootstrap.py:16` imports the breaker: keep that import working |
| M11 | CONF-024 (key `f"{request_id}:{plan_step_id}"`), CONF-025 (no ledger row for exhausted retries or guard refusals) | — | An expired ledger row counts as **no** row and leads to a probe, never a fresh call (§8 step 8) |
| M12 | CONF-026 (`execution_events`, migration 016), CONF-027 (admission snapshot and pre-flight **injected**), CONF-033 (`acquire(..., holder=)`; the in-line loop never takes over), CONF-034 (digest vs **both** stored hashes), CONF-035 (port the `tests_postgres` prototype tests) | **DEF-002** (Appendix A reasons via `transitions.validate`), **DEF-004** (step `running` and reservation `locked` in **one** transaction, I-3): mark both `fixed` with commit and case | The prototype `loop.py` is the thing being replaced; do not "adapt" it in place if that keeps its two-transaction lock |
| M13 | CONF-028 (read step: episode opened and closed `not_executed` / `read_reexecution_safe`), CONF-029 (in-line probing with the run RUNNING; never enter RECONCILING in-line) | — | Every UNKNOWN passes through PENDING_PROBE; never write `StepState.UNKNOWN` (M03 standing rule) |
| M14 ★ | CONF-030 (`CredentialProvider.credential_valid`, fail closed), CONF-031 (event records the reason; the check name only in the log), CONF-032 (gate 8 is DELAY: an outage never revokes or cancels) | — | ★: after `MILESTONE M14 REACHED`, STOP with the milestone report and wait. M15 is blocked anyway by CONF-005 until the ruling pack is applied |

### A5. Per-iteration commands (unchanged AUTOPILOT loop, written out)

```bash
python tools/owner_certify_s12.py --milestone M1x --fast
python -m pytest -q -p no:cacheprovider tests_golden/s12/M1x_*.py          # read the first failing case
# ... change only src/** (not frozen files), new migrations 016+, ported prototype tests ...
python -m pytest tests -q                                                  # 836, OWN-13
python -m pytest -q -p no:cacheprovider tests_golden/s12/M0*.py tests_golden/s12/M1[0-x]_*.py
git commit -m "s12: M1x <check or case> <what changed>"
echo "<commit> | M1x | <check> | <PASS>/<total> | <summary>" >> docs/gates/s12_autopilot_log.md
# milestone end:
python tools/owner_certify_s12.py --milestone M1x                          # full: adds X-M1x
git diff --name-only <milestone-start>..HEAD                               # only files the agent may change
```

Scope check: `batch_bundles/**`, `tests_golden/**`, `docs/implementation/**`, `docs/gates/*.sha256`,
`s12_milestones.json`, `S12_TRACKER.md` and every frozen `src/` file must never appear in that diff.

---

## Exit of this batch

The batch ends at `MILESTONE M14 REACHED`, a ★ stop. The owner runs `owner_verify_s12.ps1` for M10 through M14 and
reviews M14. The ruling pack (`S12_RULING_PACK.md`) must be applied before M15. Its golden amendments to the unpinned
B4/B5 drafts are best made before the next pin.
