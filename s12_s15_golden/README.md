# S12–S15 golden tests — drafts

Owner-owned drafts of golden tests for the S12–S15 phase (plan v3 §3, §5). The paths
below mirror their location in the implementation repository; the owner copies them
there, pins them, and the coding agent never edits them.

| File | Kind | Rule | Source |
|---|---|---|---|
| `tests/golden/s12/test_arch_no_vector_code.py` | Standing architecture guard (every milestone exit, from M1) | No vector code before blocker register Section 20 MR-1 is decided | Gate v10 §1, §14, suite 2; ADR-14 |

The guard reads files with `ast`/regex only and imports no project code. It finds the
repository root from `S12_REPO_ROOT`, or four levels above the file. Its self-tests
prove each violation kind is caught (18 cases) and that clean code, relative imports of
local modules named `lance`, docstrings, and virtual-environment directories pass.
The owner retires the file when MR-1 is decided.
