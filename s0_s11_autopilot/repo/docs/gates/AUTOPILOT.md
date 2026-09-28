# AUTOPILOT v2 — run S0–S11 to certification, autonomously

Repository: `C:\Users\Administrator\Documents\1SuperAgents`
When the owner says **"continue per AUTOPILOT"**, do exactly this file.
`docs/gates/S0_S11_RUNBOOK.md` holds the rulings; this file holds the loop.
This file replaces AUTOPILOT v1 and every earlier chat instruction.

Total checks: **19** (OWN-01,02,03,05,06,07,08,09,10,11,16,17,18,19,20 static + OWN-12,13,14,15).
Done = `python tools/owner_certify.py` prints `19/19 PASS`.

---

## Part A — Hard rules (the owner verifies all of these independently)

1. **Never edit, create, or regenerate** any of these:
   `tools/owner_certify.py`, `docs/gates/owner_certify.sha256`,
   `docs/gates/spec_pins.sha256`, anything in `docs/implementation/`,
   `docs/gates/S0_S11_RUNBOOK.md`, `docs/gates/AUTOPILOT.md`, `.gitattributes`.
   **Pinning is owner-only.** You never compute or write a pin or hash file.
2. **You may write only:** `src/**`, `tests/**`, and in `docs/gates/` only:
   `autopilot_log.md`, `test_manifest_baseline.txt`, `test_manifest_final.txt`,
   `test_reconciliation.md`, `owner_certify_final.txt`,
   `S0_S11_CERTIFICATION_REPORT.md`, `sabotage/*`.
   Any other file (e.g. `pyproject.toml`, `pytest.ini`, root `conftest.py`,
   requirements files) → STOP (condition S-5) with the proposed change.
3. **Spec wins over code and over tests.** If code disagrees with
   `DATA_CONTRACTS.md`, change the code. Never re-add a field the spec or a
   ruling removed because "tests expect it" or "stages need it" — change the
   tests/fixtures instead, or STOP (S-4) if no ruling says where the data lives.
4. **Stage handler signature is fixed:** `async def handle(state: PipelineState) -> PipelineState`
   (plus injected deps where the runbook already defines them). Do not add
   parameters to pass data between stages; data flows through `PipelineState`
   fields owned by the producing stage.
5. **Tests:** never delete, skip, xfail, weaken, or rename a required test; never
   change an expected value in runbook Part 6 code. A test may only be changed
   when it builds state by hand (OWN-19) or uses a contract shape the spec
   removed — and the new version must assert the same behavior.
6. **Test infrastructure is not an escape hatch.** Never add pytest hooks that
   alter results or selection (`pytest_runtest_makereport`,
   `pytest_collection_modifyitems`, `hookwrapper`, `force_result`,
   `report.outcome`) and never add `--testmon`, `--lf`, `-k`, `--deselect`,
   `-p no:` to any config.
7. **Never** rewrite history (`rebase`, `amend`, `reset --hard` over a commit,
   force), never create or move tags, never touch files outside the repository.

## Part B — Session start (every time, including after a context reset)

Your chat memory is not the source of truth; the repository is. At the start of
every session, and **whenever your context was summarized or you are unsure what
you were doing**:

1. Re-read this file and runbook Part 0.
2. `git log --oneline -15` and the last 15 lines of `docs/gates/autopilot_log.md`.
3. `git status --porcelain`. If there are uncommitted changes you cannot
   account for from the log, `git stash` them and log `STASHED <reason>`.
4. If `docs/gates/spec_pins.sha256` does not exist, or the latest commit touching
   it is not titled `Owner: pin ...` → STOP (S-1). Do not pin it yourself.
5. Resume the loop at step 1.

## Part C — The loop (repeat until 19/19)

1. `python tools/owner_certify.py --selftest` — any row not `OK` → STOP (S-1).
2. Delete every `__pycache__` folder, then `python tools/owner_certify.py`.
   Save the full output (including indented detail lines).
3. All 19 PASS → go to Part E.
4. **OWN-20 FAIL → STOP (S-1) immediately.** Never "fix" OWN-20.
5. Pick the **first FAIL in this order**:
   OWN-19, OWN-17, OWN-01, OWN-06, OWN-02, OWN-03, OWN-05, OWN-18, OWN-07,
   OWN-09, OWN-10, OWN-16, OWN-08, OWN-11, OWN-12, OWN-13, OWN-14, OWN-15.
6. Fix it using the runbook ruling for that area (OWN-19: R-T/R-H;
   OWN-17: R-O, R-X, R-V, R-Q, R-R, R-S; OWN-18: R-P; OWN-08: R-Y;
   OWN-12: Part 5/Part 6; OWN-15: Step 10; OWN-01/OWN-06: R-G/R-A).
   Keep each iteration small: **one check, one contract, or one test file**.
7. Run the full suite: `python -m pytest -q -p no:cacheprovider`.
   It must be green (0 failed, 0 error, 0 skipped) before you commit. If your
   change broke other tests, fix them in the same iteration.
8. Run the certifier again. **No check that was PASS before this iteration may
   now be FAIL.** If one is, fix it in this iteration or revert your change
   (`git checkout -- <files>`) and try a different approach.
9. Commit: `autopilot: <OWN id> <what changed>`.
10. Append one line to `docs/gates/autopilot_log.md` and commit it with the change:
    `<short hash> | <OWN id> | <PASS count>/19 | tests <passed> | <one-line summary>`
11. If a milestone's exit criteria are now met → run Part D, then continue.
12. Go to 1. Do **not** message the owner between iterations.

## Part D — Milestones (self-verified; the owner can audit any time)

| Milestone | Exit criteria (all must hold) |
|---|---|
| **M1 Fixtures** | OWN-19 PASS. The S0→S11 journey test contains no `with_stage_output` and no `dataclasses.replace` on state. |
| **M2 Contracts** | OWN-17, OWN-02, OWN-03 PASS. No contract class has a field outside DATA_CONTRACTS + approved extensions. |
| **M3 Vocabulary & safety defaults** | OWN-18, OWN-01, OWN-06, OWN-07, OWN-09, OWN-10, OWN-16 PASS. |
| **M4 Module state** | OWN-08 PASS. |
| **M5 Required tests** | OWN-12, OWN-13, OWN-14 PASS. |
| **M6 Evidence** | OWN-15 PASS, sabotage kit complete (Part F), 19/19 PASS. |

At each milestone run this **cross-check** and record the result:

1. Full certifier: every check that belonged to an earlier milestone is still PASS.
2. Order-independence: run the suite serially
   (`python -m pytest -q -p no:cacheprovider`) and in parallel
   (`python -m pytest -q -p no:cacheprovider -n 4`, xdist). Both green.
   If only one is green, the tests share state: fix it now (fixtures, not asserts).
3. Scope: `git diff --name-only <owner pin commit> HEAD` lists only paths allowed
   by Part A rule 2.
4. Log: `MILESTONE <Mx> REACHED | <hash> | <PASS>/19 | tests <n> | serial+parallel green | scope OK`

A milestone that fails its cross-check is **not reached**: fix it before moving on.

## Part E — Finish

1. `python tools/owner_certify.py > docs/gates/owner_certify_final.txt`
2. `python -m pytest --collect-only -q -p no:cacheprovider > docs/gates/test_manifest_final.txt`
3. Write `docs/gates/S0_S11_CERTIFICATION_REPORT.md` (runbook Step 11 format),
   including the milestone lines from the log and the sabotage table (Part F).
4. Commit. Do **not** create any tag.
5. Send exactly:
```text
AUTOPILOT COMPLETE — owner certifier 19/19 PASS at commit <hash>
Milestones M1–M6 reached; sabotage kit: 10/10 patches break their test.
Owner: run owner_verify.ps1
```

## Part F — Sabotage kit (proves the critical tests really test something)

Passing tests prove little if they would also pass against broken code. For each
rule below, create two files in `docs/gates/sabotage/`:

- `SAB-NN.patch` — a `git diff` against `src/` only, at most 6 changed lines,
  that breaks exactly that rule. It must not cause a syntax or import error.
- `SAB-NN.test` — one line: the pytest node id that must **fail with an
  assertion** when the patch is applied.

| ID | Rule the patch breaks |
|---|---|
| SAB-01 | S8: kill switch engaged no longer denies |
| SAB-02 | S8: a check returning UNKNOWN is treated as pass |
| SAB-03 | S8: a missing dependency (e.g. policy provider) no longer denies |
| SAB-04 | S9: step risk taken from TaskProfile instead of FrozenBindingIdentity |
| SAB-05 | S10: expired confirmation is accepted |
| SAB-06 | S10: confirmation from another user is accepted |
| SAB-07 | S11: plan hash mismatch is not denied |
| SAB-08 | PipelineState: second write to a stage output is allowed |
| SAB-09 | PipelineState: a stage may write a field it does not own |
| SAB-10 | S7: unmatched combination no longer returns CLARIFY |

Verify each yourself: `git apply docs/gates/sabotage/SAB-NN.patch`, run the test
(must fail with `AssertionError`), `git apply -R` the patch, run it again (must
pass). If a sabotage does **not** make its test fail, the test is weak: strengthen
the test (not the patch) and log it. The owner replays every patch independently.

## Part G — STOP conditions (the only reasons to message the owner)

- **S-1 Protection:** self-test not OK, OWN-20 FAIL, or pins missing / not owner-made.
- **S-2 Stuck:** the same OWN check is still FAIL after 3 iterations aimed at it.
- **S-3 Regression:** a PASS turned FAIL and one iteration did not restore it.
- **S-4 Ruling gap or conflict:** two rulings contradict, or code needs a place
  for data that no spec/ruling defines (e.g. where raw request input lives once
  it leaves ExecutionContext). Propose; do not invent.
- **S-5 Out-of-scope file:** a fix needs a file outside Part A rule 2.

STOP report (nothing else):
```text
AUTOPILOT STOPPED — <S-n name>
Check: <OWN id>   Detail: <the certifier's detail lines, verbatim>
Tried: <1–3 lines, with commit hashes>
Proposal: <exact text/code change you want approved, 1–10 lines>
Commit: <hash>   PASS: <n>/19   Tests: <passed>/<collected>
```
