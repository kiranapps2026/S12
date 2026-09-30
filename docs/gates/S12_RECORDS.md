# S12 records: document conflicts and precedence decisions

Append-only. One row per conflict found between source documents (or between a document and the code).
Precedence (plan section 2): gate Appendix A > gate rulings > gate sections > repaired documents > code sketches.
A passage without a repair marker that contradicts a ruling: follow the ruling, record it here, continue (gate section 0 item 5).

Find candidates with `python tools/doc_consistency.py`. When a finding is ruled, add its key to `S12_CONFLICTS_ACCEPTED.txt`.
Status: `open` (unruled), `ruled` (decision recorded, documents not yet fixed), `fixed` (owner corrected the document and re-pinned).

| ID | Milestone | Status | Opened | Summary (quote both sides with file:line) | Ruling / commit |
|---|---|---|---|---|---|
| CONF-001 | M0 | fixed | 2026-09-30 | `DATA_CONTRACTS.md` line 131: python code fence (section 2 ExecutionContext) has no closing fence before line 215; text between renders as code. Tool key `C7:unclosed-fence-DATA_CONTRACTS.md-131` | fixed in 165a42e (fence closed, re-pinned in 524c07a) |
| CONF-002 | M0 | fixed | 2026-09-30 | `DATA_CONTRACTS.md` line 1240: python code fence (19.1 StepState) has no closing fence before line 1256 (heading 19.2). Key `C7:unclosed-fence-DATA_CONTRACTS.md-1240` | fixed in 165a42e (fence closed, re-pinned in 524c07a) |
