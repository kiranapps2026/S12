# S12 stops and rulings

Append-only. A STOP is raised when the loop cannot continue (gate section 19.1): a golden test that contradicts the gate,
the same check failing after 3 iterations, a PASS turning FAIL that is not restored in one iteration, or a need to touch
S0-S11 code (gate section 19.3). Fable writes the STOP columns; the owner writes the ruling columns. Fable never edits a
golden test, a specification or a pinned file.

Status: `open` (waiting for a ruling), `ruled` (ruling recorded, not yet applied), `applied` (re-pinned / code changed), `withdrawn`.
A milestone cannot be marked `green` or `reviewed` while one of its STOPs is `open` or `ruled`.

| ID | Milestone | Status | Opened | Failing test / check | Gate section | Fable's reasoning (short) | Ruling (by, date) | Applied in commit |
|---|---|---|---|---|---|---|---|---|
