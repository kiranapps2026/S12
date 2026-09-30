# S12 stops and rulings

Append-only. A STOP is raised when the loop cannot continue (gate section 19.1): a golden test that contradicts the gate,
the same check failing after 3 iterations, a PASS turning FAIL that is not restored in one iteration, or a need to touch
S0-S11 code (gate section 19.3). Fable writes the STOP columns; the owner writes the ruling columns. Fable never edits a
golden test, a specification or a pinned file.

Status: `open` (waiting for a ruling), `ruled` (ruling recorded, not yet applied), `applied` (re-pinned / code changed), `withdrawn`.
A milestone cannot be marked `green` or `reviewed` while one of its STOPs is `open` or `ruled`.

| ID | Milestone | Status | Opened | Failing test / check | Gate section | Fable's reasoning (short) | Ruling (by, date) | Applied in commit |
|---|---|---|---|---|---|---|---|---|
| STOP-001 | M1 | ruled | 2026-09-30 | S12-PIN (`owner_certify_s12.py --milestone M1 --fast`: 4/6 PASS) | plan §5.6, S12_AUTOPILOT guardrails | `docs/gates/s12_pins.sha256` and `owner_certify_s12.sha256` do not exist on `origin/s12-work` (last commit `bca563b`): the golden set is unpinned, and pinning is owner-only | owner 2026-09-30: "start M1 unpinned" — build M1 against the current (unreviewed) golden set; pin before the M1 checkpoint | |
