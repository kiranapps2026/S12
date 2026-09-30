# S12 test-author brief (second Claude Code session)

Two sessions work on branch `s12-work`, on disjoint files, so the golden tests check the code independently:

| Session | Role | Writes only | Never touches |
|---|---|---|---|
| **Implementation** (the VPS session) | builds each milestone per `docs/gates/S12_AUTOPILOT.md` | `src/**` (not frozen files), new migrations `015+`, prototype tests in `tests/**` (CONF-011), `tests_agent/**`, `docs/gates/s12_autopilot_log.md`, `S12_STOPS.md` (STOP columns), `S12_RECORDS.md`, `S12_DEFECTS.md` | `tests_golden/**`, owner tools, pins |
| **Test author** (this brief) | reviews and drafts golden tests, answers STOPs about tests | `tests_golden/**`, `tests_golden/README.md`, `S12_RECORDS.md` (CONF rows), `S12_STOPS.md` (proposed ruling text only) | `src/**`, `tests/**`, migrations, owner tools (`tools/owner_*`), pins, `s12_milestones.json` |

The owner pins between the two (`tools/owner_pin_s12.ps1`) and runs the checkpoints (`tools/owner_verify_s12.ps1 Mxx`).
A changed golden file fails S12-PIN for the implementation session until the owner re-pins; that is intended.

## Set up the second folder (same machine, second Claude account)

The second session gets its **own clone**; two sessions must never share one working folder. From PowerShell:

```powershell
# first time (the script is in the master folder already)
powershell -ExecutionPolicy Bypass -File C:\Users\Administrator\Documents\1SuperAgents\tools\sync_s12_workspace.ps1
# before every session afterwards (fetch + pull everything, reinstall if needed, re-check)
powershell -ExecutionPolicy Bypass -File C:\Users\Administrator\Documents\1SuperAgents-tests\tools\sync_s12_workspace.ps1 -RunGolden
```

It clones `s12-work` into `C:\Users\Administrator\Documents\1SuperAgents-tests`, refuses to touch local changes or
unpushed commits, creates that folder's own `.venv` (so code is imported from that folder), writes a `.env` holding only
`TEST_DATABASE_URL` (copied from the master `.env`, value never shown), checks the database, and runs the S12 tooling
self-tests. Sharing the master's `_test` database is safe: every golden module works in its own schema. Use
`-TestDatabase suprpg_golden_test` for a separate one (create it first). Then open that folder in the second account.

## Paste this as the first message of the test-author session

```text
You are the S12–S15 TEST AUTHOR for repository kiranapps2026/S12, branch s12-work. You never write product code.
Read, in this order: docs/gates/S12_TEST_AUTHOR_BRIEF.md, docs/implementation/S12_S15_IMPLEMENTATION_PLAN.md
(§3, §4, §5), docs/implementation/S12_S15_EXECUTION_GATE.md (v10; §0, §7–§17, Appendix A), tests_golden/README.md,
docs/gates/S12_RECORDS.md.

Task 1 — independent review of batch B1 (M01–M04, drafted by another session). For each golden case, check it against
the gate text it cites: is it required by the gate, is it satisfiable together with every other case, can it pass on
unfinished code, does each sabotage patch fail it with an assertion? Report findings as a table
(file::case | problem | gate section | proposed fix). Fix only clear defects, in tests_golden/ only, and re-run:
  red-first: the golden file must fail on the current s12-work code;
  satisfiable: build a throw-away reference implementation in a scratch git worktree (never commit it) and show
  every case passes; every sabotage patch must then make >=1 case FAIL and none ERROR.
Record any document conflict as a CONF row in docs/gates/S12_RECORDS.md (status open, quote both sides with file:line).

Task 2 — when the owner says "draft B2" (then B3, B4, B5): draft the golden files for that batch the same way
(plan §5: B2 = M5–M9 incl. M8a, B3 = M10–M14, B4 = M15–M18, B5 = M19–M21), with 2–4 sabotage patches per milestone,
and extend tests_golden/fixtures/invariants.py with the invariants plan §5.4 assigns to those milestones.

Rules: never edit src/, tests/, migrations, tools/owner_*, docs/implementation/, docs/gates/*.sha256 or
s12_milestones.json. Use a PostgreSQL database whose name ends in _test (TEST_DATABASE_URL). Commit as
"golden: <batch or file> <what>", git pull --rebase origin s12-work before every push, push only to s12-work.
End every batch with: cases per file, red count on current code, reference pass count, sabotage caught k/k,
records opened. Then stop and tell the owner to run tools\owner_pin_s12.ps1.
```

## Answering a STOP about a golden test

The implementation session records it as `STOP-nnn` in `S12_STOPS.md`. The owner pastes the STOP into the test-author
session, which proposes a ruling (change the golden file, or explain why the code must change). The owner decides,
re-pins, marks the STOP `applied`, and tells the implementation session "continue per S12 AUTOPILOT".
