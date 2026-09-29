# AUTOPILOT — run S0–S11 to certification without owner hand-holding

Repository: `C:\Users\Administrator\Documents\1SuperAgents`
Save as `docs\gates\AUTOPILOT.md`. When the owner says "continue per AUTOPILOT", do
exactly this. `docs\gates\S0_S11_RUNBOOK.md` holds the rulings; this file holds the loop.

## Guardrails (enforced by the owner certifier, not by trust)

- `tools/owner_certify.py`, `docs/gates/owner_certify.sha256`,
  `docs/gates/spec_pins.sha256`, everything in `docs/implementation/`, the runbook
  and this file: never edit. OWN-20 and the hash files detect any change.
- Fix failures only in `src/` and `tests/` (including `tests/fixtures/`).
- Never change an expected value in runbook Part 6 test code.

## Step 0 (only if `docs/gates/spec_pins.sha256` does not exist)

1. `git log --oneline -- docs/implementation`. Revert every change you (the agent)
   made in `docs/implementation/` except: B1–B4, the ADR-13 register fix, the
   PIPELINE_STAGES transport-normalization caution, and the WORKER_LIFECYCLE
   Re-entry Revalidation section. Commit.
2. STOP with the one-line report: `STEP 0 DONE — owner: run tools\owner_pin.ps1`.
   Do nothing else until the owner says "continue per AUTOPILOT".

## The loop (repeat until done)

1. Run `python tools/owner_certify.py --selftest`. If any row is not OK → STOP.
2. Run `python tools/owner_certify.py`.
3. If every row is PASS → go to "Finish".
4. Take the **first FAIL in this order**: OWN-19, OWN-17, OWN-01, OWN-06, OWN-18,
   OWN-08, OWN-12, OWN-15, then any other. Read its detail lines.
5. Fix it following the runbook ruling for that area (OWN-19: R-T/R-H;
   OWN-17: R-O, R-X, R-V, R-Q, R-R, R-S; OWN-18: R-P; OWN-08: R-Y;
   OWN-12: Part 5/Part 6 and the steps that implement them; OWN-15: Step 10;
   OWN-01/OWN-06: R-G/R-A).
6. Run the full suite. It must be green before committing. If your change broke
   other tests, fix them in the same iteration.
7. Commit with message `autopilot: <OWN id> <what changed>`.
8. Append one line to `docs/gates/autopilot_log.md`:
   `<commit> | <OWN id> | <PASS count>/<total> | <one-line summary>`
9. Go to 1. Do not send the owner a message between iterations.

## STOP conditions (the only reasons to message the owner before the end)

- A fix would require changing a spec document, the certifier or the runbook →
  report the exact proposed text change.
- The same OWN check is still FAIL after 3 iterations aimed at it → report the
  detail lines, what you tried, and your proposed fix.
- The PASS count went down after a commit and you cannot restore it within one
  iteration.
- Two rulings contradict each other.

STOP report format (nothing else):
```text
AUTOPILOT STOPPED — <condition>
Check: <OWN id>   Detail: <the certifier's detail lines>
Tried: <1–3 lines>
Proposal: <1–3 lines>
Commit: <hash>
```

## Finish

1. `python tools/owner_certify.py > docs/gates/owner_certify_final.txt`
2. Write `docs/gates/S0_S11_CERTIFICATION_REPORT.md` (runbook Step 11 format).
3. Commit. Do **not** create the `s0-s11-certified` tag; the owner does that after
   verifying.
4. Send exactly:
```text
AUTOPILOT COMPLETE — owner certifier N/N PASS at commit <hash>
Owner: run tools\owner_verify.ps1
```
