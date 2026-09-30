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
| STOP-002 | M5 | open | 2026-09-30 | G-M5: no golden file `tests_golden/s12/M05_*.py` | plan §5.1 (B2 = M5–M9 incl. M8a), S12_AUTOPILOT loop step 4 | M1–M4 are built (golden 316/316, sabotage 12/12); M5 has no owner golden test, so there is nothing red-first to build against. Building M5 without it would be unverified work | test-author session drafts B2 ("draft B2" per S12_TEST_AUTHOR_BRIEF.md), owner pins, marks this row applied | |
| STOP-003 | M8a | open | 2026-09-30 | S12-REC: CONF-019, CONF-020 open (no ruling); all code rows PASS (`owner_certify_s12.py --milestone M8a`: G-M8a 49/49, C-M8a x5, X-M8a) | C39 17c and soft quota; §19.3 (frozen files) | Two document-vs-code conflicts with no ruling, both needing a frozen S0–S11 file to follow the gate text literally. CONF-019: the gate's "binding row it already reads at entry" is the frozen `PostgresBindingVersionReader`, and pinned M08a limits `runtime_type` to `selection.py`; implemented the proposal (`PostgresSelectionReader.required_runtime_types`, read once at entry by M12). CONF-020: frozen `AdmissionOutcome` has no `detail` for the soft-quota upgrade text; nothing implemented beyond `retry_after_ms`. Raised late: found while building, after the first code change (autopilot session-start step 5) | | |
