# S12–S15 golden tests — drafts

Owner-owned drafts of golden tests for the S12–S15 phase (plan v3 §3, §5). The paths
below mirror their location in the implementation repository; the owner copies them
there, pins them, and the coding agent never edits them.

| File | Kind | Rule | Source |
|---|---|---|---|
| `tests/golden/s12/test_arch_no_vector_code.py` | Standing architecture guard (every milestone exit, from M1) | No vector code before blocker register Section 20 MR-1 is decided | Gate v10 §1, §14, suite 2; ADR-14 |

The guard reads files with `ast`/regex only and imports no project code. It finds the
repository root from `S12_REPO_ROOT`, or four levels above the file. Its self-tests
prove each violation kind is caught (22 cases, including `scripts/`, top-level files and
nested `pyproject.toml`), that clean code, relative imports of local modules named `lance`,
docstrings and virtual-environment directories pass, and that the guard never flags its
own sabotage data once installed (audit round 2 C7: the first draft did, because it
scanned `tests/` for SQL).
## Deletion contract — no permanent block

**When MR-1 is decided, delete this guard file and the gate §1 entry in the same change.**
A guard without its gate rule, or a gate rule without its guard, is a defect. That same
change must also update every other reference, so nothing is left pointing at a deleted
file:

| # | Location | Change |
|---|---|---|
| 1 | `tests/golden/s12/test_arch_no_vector_code.py` (implementation repo) and this draft | Delete; remove it from the owner pin list |
| 2 | `S12_S15_EXECUTION_GATE.md` §1 "You MUST NOT" — "Write any vector code …" | Delete the entry |
| 3 | `S12_S15_EXECUTION_GATE.md` header — "v10 addendum … vector memory / RAG is blocked …" | Replace with the revision that lifts the block |
| 4 | `S12_S15_EXECUTION_GATE.md` §14 — "Vector memory / RAG …" | Point to the decided MR-1 and its target phase; drop "no vector code of any kind" |
| 5 | `S12_S15_EXECUTION_GATE.md` §16 suite 2 — "(v10) No vector code …" | Delete the check |
| 6 | `S12_S15_IMPLEMENTATION_PLAN.md` §4 milestone exit — "the standing guard … passes" | Delete the bullet |
| 7 | `S12_S15_IMPLEMENTATION_PLAN.md` §5 item 5 "Standing guards", M21 "no vector code", §7 risk row | Delete or reword |
| 8 | `VALIDATION.md` — `test_no_vector_code_in_repository()` row | Delete the row |
| 9 | `SUPERSESSION_AWARE_BLOCKER_REGISTER.md` Section 20 — blocking rule and "Enforcement" line; MR-1 status | MR-1 → DECIDED; blocking rule and enforcement line marked lifted, citing the change |
| 10 | This README | Remove the row for the guard |

A quick check that nothing is missed: after the change,
`grep -rn "test_arch_no_vector_code\|no vector code" *.md s12_s15_golden/` returns only
historical records: the register's Section 20 note, `ADR-14_VECTOR_MEMORY_BACKEND.md`
(the decision record) and this contract section (keep it until the next guard is added,
or delete the README with the last guard).
