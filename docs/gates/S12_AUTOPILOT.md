# S12 AUTOPILOT — build S12–S15 milestone by milestone without owner hand-holding

Repository: `C:\Users\Administrator\Documents\1SuperAgents`, branch `s12-work`.
When the owner says **"continue per S12 AUTOPILOT"**, do exactly this. The binding rules are
`docs\implementation\S12_S15_EXECUTION_GATE.md` (v10) and the milestone cards in
`docs\implementation\S12_S15_IMPLEMENTATION_PLAN.md` §4 (v3); this file is the loop. Owner-pinned: never edit it.

## Guardrails (enforced by `tools/owner_certify_s12.py`, not by trust)

- **Never edit** (S12-PIN, OWN-20, S12-FRZ detect any change):
  `tests_golden/**`, `tools/owner_certify_s12.py`, `tools/owner_certify.py`, `tools/owner_pin*.ps1`,
  `tools/owner_verify*.ps1`, `tools/doc_consistency.py`, `tools/s12_tracker.py`, `docs/gates/*.sha256`,
  `docs/gates/s12_milestones.json`, `docs/gates/S12_PROGRESS.md`, `docs/gates/S12_TRACKER.md`, this file, anything in
  `docs/implementation/`, and every frozen S0–S11 source file (`src/` at tag `s0-s11-certified` minus the prototype list
  in `tests_golden/fixtures/code_scan.py`, ruling CONF-011).
- **You may change:** `src/**` except frozen files; new migrations `src/adapters/postgres/migrations/015_*.sql` onwards
  (never 001–014); `tests/**` only where a prototype S12 test must follow a reworked prototype (CONF-011; the six S0–S11
  golden tests pinned by OWN-20 never); `tests_agent/**` (your own extra tests; they never count).
- **Append only:** `docs/gates/s12_autopilot_log.md`, `docs/gates/S12_RECORDS.md`, `docs/gates/S12_STOPS.md`,
  `docs/gates/S12_DEFECTS.md`.
- Never skip, xfail or weaken a test; never change an expected value in a golden test; never run against a database whose
  name does not end in `_test`; never read or print credentials (`.env` values).
- Never create a tag. Never push anywhere but `origin s12-work`.

## Session start (every session, and after any context summary)

1. `git status` and `git log --oneline -15`. The repository, not memory, is the state.
2. The milestone = the first row of `docs/gates/s12_milestones.json` whose status is not `green`/`reviewed`.
3. Read that milestone's card in plan §4, then every gate section and ruling the card names, then the golden file
   `tests_golden/s12/Mxx_*.py` (its docstring states the interface you must build), then `tests_golden/README.md`.
4. Read the last 15 lines of `docs/gates/s12_autopilot_log.md` and every `open` row of `S12_RECORDS.md` and `S12_STOPS.md`.
5. Before the first code change of a milestone, list any mismatch between the card's documents as `CONF-nnn` in
   `S12_RECORDS.md` (quote both sides with file:line). A ruling that already settles it: apply it and continue. Otherwise STOP.

## The loop (repeat inside one milestone)

1. `python tools/owner_certify_s12.py --selftest`. Any row not OK → STOP.
2. `python tools/owner_certify_s12.py --milestone Mxx --fast`.
3. Every row PASS → go to "Milestone end".
4. Take the **first FAIL in this order**: S12-S011, S12-FRZ, S12-PIN, S12-DOC, S12-REC, the earliest `G-` row. Read its
   detail lines; for a `G-` row run the golden file yourself and read the first failing case.
5. Fix it in the files you may change, following the gate section the golden case cites. Build only what the card asks;
   nothing deferred (C40, C41, §14, Laya, vector memory).
6. Run `python -m pytest tests -q` (must stay green: OWN-13) and the golden files of this and every earlier milestone.
7. Commit: `s12: Mxx <check or case> <what changed>` (one logical change per commit).
8. Append one line to `docs/gates/s12_autopilot_log.md`:
   `<commit> | Mxx | <check> | <PASS count>/<total> | <one-line summary>`
9. Go to 1. Do not message the owner between iterations.

## Milestone end

1. `python tools/owner_certify_s12.py --milestone Mxx` (full: sabotage patches and 5× concurrency). All PASS, else back
   to the loop with the first FAIL.
2. Scope check: `git diff --name-only <commit at milestone start>..HEAD` lists only files you may change.
3. Append `MILESTONE Mxx REACHED at <commit>` to the log; push `origin s12-work`.
4. If the milestone is ★ (M1, M8a, M14, M21) → STOP with the milestone report (below) and wait for
   "continue per S12 AUTOPILOT". Otherwise send the milestone report and continue with the next milestone.
   The owner's checkpoint (`tools/owner_verify_s12.ps1 Mxx`) moves the milestone to `green`; you never edit its status.

## STOP conditions (the only reasons to message the owner before a milestone ends)

- A golden test contradicts the gate or another golden test (gate §19.1): report the test, the gate section, your reasoning.
- A fix would need a pinned or frozen file changed (gate §19.3): report the exact proposed change.
- The same check still FAILs after 3 iterations aimed at it.
- The PASS count went down after a commit and one more iteration does not restore it.
- Two rulings contradict each other, or a document conflict has no ruling.
- Record every STOP as `STOP-nnn` (status `open`) in `docs/gates/S12_STOPS.md` before reporting.

STOP report (nothing else):
```text
S12 AUTOPILOT STOPPED — <condition>          STOP-nnn
Milestone: Mxx   Check: <row or golden case>   Gate: <section / ruling>
Detail: <certifier or pytest lines>
Tried: <1–3 lines>
Proposal: <1–3 lines>
Commit: <hash>
```

Milestone report:
```text
S12 MILESTONE Mxx REACHED — owner_certify_s12 N/N PASS at commit <hash>
Golden: <n> cases; sabotage <k>/<k> caught; concurrency x5: <yes/n.a.>
Records opened: <CONF/DEF ids or none>
Owner: run tools\owner_verify_s12.ps1 Mxx
```

## Model and effort (plan §4 complexity; owner may override)

Opus-class for M7, M9, M10, M11, M13, M14, M17, M19, M20 and every STOP ruling; Sonnet-class for the others. After three
failed iterations on one check a Sonnet session stops rather than guessing (STOP condition 3).
