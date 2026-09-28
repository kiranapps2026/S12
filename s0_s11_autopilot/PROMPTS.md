# S0–S11 prompt pack — paste these to Fable, in this order

Every prompt is self-contained: Fable does not need chat history, only the repo.
You paste **P0 once**, **P1 once**, and after that only react to the three
messages Fable is allowed to send: `AUTOPILOT STOPPED`, `AUTOPILOT COMPLETE`,
or silence/drift (P3/P4).

---

## P0 — send NOW (corrects Fable's latest run)

Why: Fable said *"Now I'll pin the specs"* (pinning is owner-only), and it
**re-added `raw_input`, `sanitized_input` and `trace` to ExecutionContext**
because "tests expect them". That reverses ruling R-X and is exactly why OWN-17
keeps failing. Its later idea — change S1's handler signature to take
`raw_input` as a parameter — breaks the uniform stage pattern. Stop both before
they get committed.

```text
STOP the current iteration. Do not commit anything from it.

1. Pinning is owner-only. Do not create or modify docs/gates/spec_pins.sha256,
   docs/gates/owner_certify.sha256, .gitattributes, tools/owner_certify.py,
   the runbook, AUTOPILOT.md or anything in docs/implementation/. If you already
   created or changed any of them in this session, restore them:
   git checkout HEAD -- <file>   (or delete the file if it is new and untracked).

2. Do NOT re-add raw_input, sanitized_input or trace to ExecutionContext, and do
   NOT add parameters to any stage handler. ExecutionContext must match
   DATA_CONTRACTS.md exactly (OWN-17). Revert those edits.
   Owner ruling for the data they carried (applies unless runbook R-X already
   names a different carrier — if it does, follow R-X):
   - Raw request input travels in PipelineState as an S0-owned output field
     (typed dataclass, not dict/Any — OWN-03). S1 reads it from state.
   - Sanitized input travels in PipelineState as an S1-owned output field.
     It is untrusted user-derived text and never enters ExecutionContext.
   - trace data that is not in the ExecutionContext spec lives in the stage
     outputs or in logging, not in ExecutionContext.
   Register the new fields with the correct owning stage in the ownership
   mapping, and write them only through with_stage_output.
   Fix tests and fixtures that read these from ExecutionContext to read them
   from state instead. Tests follow the spec, never the reverse.

3. Leave your src/ and tests/ work uncommitted but intact (git stash is fine),
   then reply with exactly:
   git status --porcelain
   git log --oneline -5
   and the line: READY FOR OWNER PIN
   Then wait. The owner will install AUTOPILOT v2, pin, and say
   "continue per AUTOPILOT".
```

When Fable replies `READY FOR OWNER PIN`: do the install steps in README.md
(copy files, run `owner_pin.ps1`), then send P1.

---

## P1 — start the autonomous loop (after owner_pin.ps1 succeeded)

```text
continue per AUTOPILOT

The owner has pinned the specs, runbook and AUTOPILOT v2 (commit titled
"Owner: pin certifier, specs, runbook and AUTOPILOT v2"). AUTOPILOT v2 replaces
v1 and every earlier chat instruction. Start with Part B (session start), then
run the Part C loop until 19/19, self-verifying each milestone per Part D and
building the sabotage kit per Part F. If you had stashed work, `git stash pop`
it first and treat it as the current iteration.

Only three messages are allowed from you: an AUTOPILOT STOPPED report,
AUTOPILOT COMPLETE, or nothing. Do not ask for confirmation between
iterations or milestones.
```

---

## P2 — resume (new session, crash, or after Fable's context was summarized)

```text
continue per AUTOPILOT

You are resuming. Your memory of earlier turns is not reliable; the repository
is. Do Part B exactly: re-read docs/gates/AUTOPILOT.md and runbook Part 0, read
`git log --oneline -15` and the last 15 lines of docs/gates/autopilot_log.md,
check `git status --porcelain`, then continue the Part C loop from step 1.
Before your first edit, write one line: "RESUMING at <hash>, <PASS>/19, next: <OWN id>".
```

---

## P3 — Fable paused or asked a question it should not ask

Use when it says "awaiting your direction", "shall I proceed?", or stops without
a proper STOP report.

```text
That is not a STOP condition in AUTOPILOT Part G. Continue the loop without
waiting. If you believe it is a STOP condition, send the full Part G report
format (condition, check, detail lines, tried, proposal, commit, PASS, tests)
and nothing else.
```

---

## P4 — drift detected (use the matching line; paste with the evidence)

Send when you see any of these in Fable's running output:

| You see Fable… | Send |
|---|---|
| editing `tools/`, `docs/implementation/`, runbook, AUTOPILOT, a `.sha256` file, `.gitattributes` | `Part A rule 1 violation. Revert that file with git checkout HEAD -- <file>, then continue the loop.` |
| re-adding a field "because tests/stages need it" | `Part A rule 3: spec wins. Remove the field, move the data per the ruling, fix the tests. If no ruling says where the data lives, send an S-4 STOP report.` |
| changing an expected value, deleting/skipping/renaming a test | `Part A rule 5 violation. Restore the test exactly (git checkout HEAD -- <test file>) and fix src/ instead.` |
| editing conftest hooks, `pyproject.toml`, `pytest.ini`, addopts | `Part A rule 2/6: out-of-scope file. Revert it and send an S-5 STOP report if you really need the change.` |
| running 50+ commands fixing tests one by one | `Stop fixing tests individually. Find the shared cause (fixture, contract, scenario builder) from ONE failing test's full traceback, fix that, rerun the suite.` |
| "fixed" by `git stash drop`, `reset --hard`, amend, rebase | `Part A rule 7 violation. Do not rewrite history. Show git reflog -10 and restore the lost commits.` |
| claims "all green" without the certifier table | `Paste the full output of python tools/owner_certify.py including detail lines, and the log line for this iteration.` |

---

## P5 — Fable sent `AUTOPILOT STOPPED`

Do not answer it yourself. Paste the report to Claude (chat) with this line on top:

```text
Fable STOP report below. Give me (1) a ruling or approval I can paste to Fable,
and (2) if a pinned document must change, the exact text change and the
PowerShell to re-pin it. Keep the reply to what I paste and what I run.
<paste STOP report>
```

Then send Fable the ruling, followed by `continue per AUTOPILOT`. If a spec
changed, run `owner_pin.ps1` again **before** telling Fable to continue.

---

## P6 — optional milestone audit (any time, especially after M2)

In PowerShell, from the owner folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\owner_checkpoint.ps1          # seconds
powershell -ExecutionPolicy Bypass -File .\owner_checkpoint.ps1 -Full    # with pytest checks
```

Green → do nothing; the agent keeps going. Any red FAIL → send Fable:

```text
Owner checkpoint failed. Treat it as AUTOPILOT STOP S-1 and fix it first:
<paste FAIL lines>
Then continue per AUTOPILOT.
```

---

## P7 — Fable sent `AUTOPILOT COMPLETE`

```powershell
powershell -ExecutionPolicy Bypass -File .\owner_verify.ps1
```

- **CERTIFIED** → answer `y` to tag. S0–S11 is done; bring the result to Claude
  to start the S12 plan.
- **NOT CERTIFIED** → send Fable:

```text
Owner verification failed; AUTOPILOT COMPLETE is withdrawn. Treat every line
below as a failing check and continue the loop until owner_verify would pass:
<paste FAIL lines>
continue per AUTOPILOT
```
