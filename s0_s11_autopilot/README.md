# S0–S11 certification kit v2 (autonomous loop + milestone verification + cross-checks)

## What changed from v1, and why

| Gap in v1 | Fix in v2 |
|---|---|
| AUTOPILOT said the runbook and AUTOPILOT.md are protected by OWN-20, but only `docs/implementation/*.md` were pinned. | `owner_pin.ps1` also pins `S0_S11_RUNBOOK.md` and `AUTOPILOT.md` in `spec_pins.sha256`. OWN-20 already supports any path, so the certifier (hash `F8E4C933…50F2`) is unchanged. |
| The agent could edit a spec **and regenerate `spec_pins.sha256`**; OWN-20 would still pass. Fable's latest run said "Now I'll pin the specs". | The pin commit is recorded **outside the repo** (`pin_record.txt`). Checkpoint/verify diff every protected path against that commit and check it is still in history. |
| `owner_verify.ps1` ran the certifier copy that lives in the repo, which the agent can reach. | Owner scripts and a **trusted certifier copy** live in a separate owner folder; verify runs that copy against the repo. |
| Loop order said "then any other", so an OWN-20 failure would have been "fixed" by the agent. | OWN-20 FAIL or self-test failure is an immediate STOP. |
| Nothing prevented a PASS count regression inside an iteration. | Loop step 8: no PASS may turn FAIL; checkpoint flags drops in the log. |
| Tests could pass without really testing anything (the gap flagged in the last chat). | **Sabotage kit**: 10 small patches that break a critical rule; owner_verify replays each in a throw-away worktree and requires its test to fail with an assertion. |
| Earlier breakage came from tests sharing state. | Every milestone and owner_verify run the suite serially and in parallel (`-n 4`). |
| Dependent files (`conftest.py`, `pyproject.toml` addopts, `PYTEST_ADDOPTS`) could hide tests. | Scope check lists every file changed outside `src/`, `tests/` and the allowed evidence files; conftest hooks that rewrite results and addopts such as `--testmon`, `--lf`, `--deselect`, `-k` fail. |
| Context loss made Fable forget instructions. | AUTOPILOT Part B: the repo and log are the state; re-read on every resume (prompt P2). |
| Check count was stated as 20. | The certifier has **19** checks (15 static + OWN-12..15). |

## Install (about 5 minutes, once)

1. Create the owner folder **outside** the repo:
   `C:\Users\Administrator\Documents\1SuperAgents_owner`
2. Copy into it: `owner_tools\owner_common.ps1`, `owner_pin.ps1`,
   `owner_checkpoint.ps1`, `owner_verify.ps1`, and your downloaded
   `owner_certify_5.py` **renamed to** `owner_certify.py`.
   Check it: `(Get-FileHash .\owner_certify.py -Algorithm SHA256).Hash` must be
   `F8E4C933B09884B3106B48710FACE7F6B07AEA24E31F5CAE6258CE88BA1550F2`.
3. (The old `tools\owner_pin.ps1` / `tools\owner_verify.ps1` in the repo are
   removed automatically by the new `owner_pin.ps1`.)
4. Send Fable **P0** from `PROMPTS.md`. Wait for `READY FOR OWNER PIN`.
5. Copy `repo\docs\gates\AUTOPILOT.md` over `1SuperAgents\docs\gates\AUTOPILOT.md`.
6. From the owner folder run:
   `powershell -ExecutionPolicy Bypass -File .\owner_pin.ps1 -Baseline d972516`
   (`d972516` = "Pre-R0 baseline", the first commit with the docs in 1SuperAgents.)
   Read the spec diff stat it shows; answer `y` only if it lists nothing beyond
   the allowed changes.
7. Send Fable **P1**. From here you only react to STOP / COMPLETE (P5, P7),
   and can audit any time with `owner_checkpoint.ps1` (P6).

## Your time per phase

| When | You do | Time |
|---|---|---|
| Now | P0, install, pin, P1 | ~10 min |
| At M2 (optional) | `owner_checkpoint.ps1` | 1 min |
| On STOP | forward to Claude, paste ruling back | ~3 min |
| On COMPLETE | `owner_verify.ps1`, answer `y` | ~3 min |

## Files

```
owner_tools/            -> copy to C:\...\1SuperAgents_owner (NOT into the repo)
  owner_common.ps1        shared settings, protection and scope checks
  owner_pin.ps1           owner-only: approve and freeze specs, record pin commit
  owner_checkpoint.ps1    read-only audit at any time / milestone
  owner_verify.ps1        final independent verification + sabotage replay + tag
repo/docs/gates/
  AUTOPILOT.md            v2 loop for the agent (gets pinned)
PROMPTS.md              every message you send to Fable, in order
```

Note: these scripts were written for Windows PowerShell 5.1 and were not executed
here (no Windows or PowerShell in this environment). The certifier self-test
was run here: all 15 static checks are OK. Run `owner_checkpoint.ps1` once
right after pinning, before sending P1, so you catch any path/setup problem
before the loop starts.
