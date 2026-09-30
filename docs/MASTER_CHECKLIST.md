# Master folder checklist (before working in `1SuperAgents`, online or offline)

`C:\Users\Administrator\Documents\1SuperAgents` is the master working folder: an exact clone of branch `s0-s11-repair`.
One command proves it is good to go and writes `MASTER_STATUS.md` (git-ignored, machine specific) with every commit id:

```powershell
cd C:\Users\Administrator\Documents\1SuperAgents
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe tools\master_status.py --fetch --tests --postgres
```

Drop `--fetch` when you are offline (the commit comparison then uses the last fetch and says so). `--tests` runs the unit suite;
`--postgres` runs the real-PostgreSQL suite (needs `TEST_DATABASE_URL` in `.env`, ending in `_test`, about 3 minutes).
The exit code is 0 only when every required check passes.

## What it verifies, and what to do when a check fails

| Check | Fix when it fails |
|---|---|
| Folder is a git clone of `kiranapps2026/S12` on branch `s0-s11-repair` | run `tools\adopt_master_folder.ps1` (makes a fresh clone, keeps the old folder aside) |
| Same commit as `origin/s0-s11-repair` (ahead 0, behind 0) | behind: `git pull origin s0-s11-repair`. Ahead: your local commits are not on GitHub: push them, or drop them if they are accidents (`git branch backup-local; git reset --hard origin/s0-s11-repair`) |
| Working tree clean | commit or discard; never leave `.env.example` edits (real values belong only in `.env`) |
| `s0-s11-baseline` is an ancestor | you are on the wrong history: re-clone. Never merge baseline into the repair branch |
| Tag `s0-s11-certified` | SKIP until `owner_verify.ps1` created it; afterwards it must sit on HEAD, or the code changed since certification |
| Certifier hash = `owner_verify.ps1` = `docs/gates/owner_certify.sha256` | restore the certifier, or (owner decision) update the other two |
| `owner_certify.py` 19/19 and `--selftest` | fix the FAIL rows it prints; never edit the certifier to pass |
| Python 3.11+, packages consistent, code imported from THIS folder | `pip install -e ".[dev]"` inside this folder's `.venv`; a stale editable install from another folder is the usual cause |
| `PYTHONUTF8=1` (Windows) | `setx PYTHONUTF8 1`, then open a new window |
| `.env` has `DATABASE_URL`; not tracked; no key/password in tracked files | `python tools\setup_database.py --reset-password --write-env`; if a secret was committed, rotate it |
| Dev database: plain role, all migrations applied, registry loaded, 0 blocked | `python tools\setup_database.py`, then `python tools\load_catalog.py docs\catalog\catalog.yaml --apply` |
| `pytest tests` / `pytest tests_postgres` all pass, nothing skipped | read the FAILED lines; do not skip or weaken tests |

## Working offline

- Everything above except `--fetch` needs no internet. The live-model tests (`run_live_chain.ps1`) need the DeepSeek API and do not run offline.
- Before going offline: run the command with `--fetch`, keep PostgreSQL running (it is local), and make sure `pip install -e ".[dev]"` finished once.
- Offline commits are fine; push when back online (`git push origin s0-s11-repair`). Push nothing else, and merge nothing into this branch.
- After the tag exists, S0–S11 code is frozen: a change to it needs a new certification. S12 work adds new files and migrations.

## Reading `MASTER_STATUS.md`

`GOOD TO GO` at the top and no FAIL rows. The commit table lists this folder's HEAD, `origin/s0-s11-repair`, the baseline snapshot and the tag,
so two machines (or you and a reviewer) can compare one line: the HEAD commit id. WARN rows (no virtual environment, no DeepSeek key) do not
block work but should be understood.
