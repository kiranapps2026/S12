# S12–S15 golden tests — drafts

Owner-owned drafts of golden tests for the S12–S15 phase (plan v3 §3, §5). The paths
below mirror their location in the implementation repository; the owner copies them
there, pins them, and the coding agent never edits them.

| File | Kind | Rule | Source |
|---|---|---|---|
| — | — | No drafts at present | — |

**Removed 2026-09-29:** `tests/golden/s12/test_arch_no_vector_code.py` (standing guard: no vector
code before blocker register Section 20 MR-1). MR-1 and ADR-14 were decided by the owner, so the
guard and every reference below were removed in one change, as the deletion contract requires.
The owner removes it from the pin list in the implementation repository.

The removed guard read files with `ast`/regex only and imported no project code; its design
(and its 22 sabotage self-tests) remain in git history for the next standing guard.

## Deletion contract — no permanent block (applied 2026-09-29; kept as the pattern for the next guard)

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
