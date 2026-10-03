# Backup and restore: certified work (S0–S11, S12–S15)

Owner procedure. Written 2026-10-03 against `s12-work` at `dac952e`. **This is not a record**; the records stay
`S12_RECORDS.md`, `S12_STOPS.md` and `S12_DEFECTS.md`. Every command here is run by the **owner**, never handed to an
agent, unless a section says otherwise.

Why: certified work took weeks of owner rulings, pinned golden tests and owner checkpoints. One force-push already
removed 30 commits from `s12-work` (recovered from `backup/s12-work-before-force-push`), and agents have edited golden
files, pinned tools and frozen files by mistake. The adapter phase (roadmap 2c) adds more agents and more branches.
This document makes every certified state recoverable, makes damage visible at once, and keeps new work away from
certified code.

Contents: [1 What can go wrong](#1-what-can-go-wrong) · [2 What is protected](#2-what-is-protected-inventory) ·
[3 The five layers](#3-the-five-layers) · [4 Routines](#4-routines-when-to-do-what) ·
[5 Restore playbooks](#5-restore-playbooks) · [6 Rules for agents](#6-rules-for-agents) ·
[7 Restore drill](#7-restore-drill) · [8 Windows notes](#8-windows-notes) · [9 Checklists](#9-checklists) ·
[10 Backup log](#10-backup-log)

---

## 1. What can go wrong

| # | Event | Example seen in this project | Detected by | Recovered by |
|---|---|---|---|---|
| T1 | History rewritten (force-push, rebase) | 30 commits lost from `s12-work` | missing commits, `git log` | §5.5, layer 2 prevents |
| T2 | Branch or tag deleted or moved | — | `git ls-remote` vs §2 | §5.6, §5.7, layer 2 prevents |
| T3 | Golden test edited to make code pass | M01/M10/M11/M12 edited by an implementation session | certifier `S12-PIN` | §5.2 |
| T4 | Frozen S0–S11 file edited | — | certifier `S12-FRZ` | §5.3 |
| T5 | Owner tool or pin edited | `owner_pin_s12.ps1` edited by an agent | `S12-PIN`, certifier hash check | §5.4 |
| T6 | Bad code committed and pushed | 018/019 migrations, regressions in M12/M13/M15 | golden suite, certifier | §5.1 (revert) |
| T7 | Stale or uncommitted local work, wrong folder | `loop.py` D-5 edits in the main folder; missing `checkpoints.py` in a push | `git status`, suite | §5.8 |
| T8 | Repository damaged or GitHub unavailable | — | clone/fetch fails | §5.9 |
| T9 | Owner machine lost | — | — | §5.10 |
| T10 | Agent uses owner powers (pins, tags, rulings) | an agent ran a pin; an agent wrote ruling columns | commit author/message review, §6 | §5.4, §5.11 |

---

## 2. What is protected (inventory)

Verify these against the remote with `git ls-remote --tags --heads origin` (§3.5). Hashes are short; the full hash is
what `git rev-parse <name>` prints.

### 2.1 Tags (immutable checkpoints)

| Tag | Commit | Meaning | Status |
|---|---|---|---|
| `s0-s11-certified` | `f14a956` | S0–S11 certified (owner decisions R-AB..R-AL, R-BB..R-BU) | exists |
| `s12-m14-certified` | `181b7f5` | S12 M1–M14 certified by `owner_verify_s12.ps1`, M0/M1/M8a/M14 reviewed | **create (§3.1)** |
| `s12-stage2-pinned` | `dac952e` | Stage 2 rulings recorded; golden set pin #4 (before M15–M21 code) | **create (§3.1)** |
| `s12-s15-certified` | M21 checkpoint | S12–S15 certified (M15–M21), report and deferred register written | at the tag (§4.3) |

### 2.2 Branches

| Branch | Head | Role | Protection (layer 2) |
|---|---|---|---|
| `s12-work` | moving | S12–S15 development until the tag; afterwards read-only except owner merges | no force-push, no deletion |
| `s0-s11-baseline` | `8ddf4a3` | snapshot of the S0–S11 starting point | no force-push, no deletion |
| `s0-s11-repair` | `845b26f` | S0–S11 repair line | no force-push, no deletion |
| `backup/s12-work-before-force-push` | `f192b67` | recovery copy of the 30 commits lost in the force-push | no force-push, no deletion |
| `adapters-work` | — | adapter phase, created from `s12-s15-certified` (§3.4) | no force-push, no deletion |

### 2.3 Owner checkpoints on `s12-work` (for reference and audits)

| Milestone | Checkpoint commit | Review commit |
|---|---|---|
| M1 | `24c562e` | `ebaaa21` (the earlier `997d7dd` carries the label but only a progress file) |
| M2 | `5bc4805` | — |
| M3 | `42ae078` | — |
| M4 | `a0b1361` | — |
| M5 | `4aec3a3` | — |
| M6 | `d6a538b` | — |
| M7 | `fdfc7df` | — |
| M8 | `e51855f` | — |
| M8a | `289d2e8` | `721e916` |
| M9 | `4fd6fed` | — |
| M10 | `7c29d74` | — |
| M11 | `6586639` | — |
| M12 | `591fc73` | — |
| M13 | `fe09926` | — |
| M14 | `2c0a8a2` | `181b7f5` |
| M15–M21 | (to add at certification) | M21 review (to add) |

### 2.4 Pins and rulings

| Commit | What |
|---|---|
| `db847c4` | pin #1 (B1–B5 golden set) |
| `fa5042f` | STOP-001/002/004/005 applied |
| `4df48fa`, `3aeddde` | Stage 2 owner rulings (CONF-005, 042–052, DEF-003, amendments) |
| `422c457` | golden Stage 2 amendments (M10, M18–M21, three sabotage patches) |
| `49b1fb9` | pin #2 |
| `67b044d`, `157a173` | golden fix M19 D-10; pin #3 |
| `2ee4dd1`, `dac952e` | golden fix M20 D-5; pin #4 |

### 2.5 Owner tool fingerprints

| File | SHA256 | Where it is also recorded |
|---|---|---|
| `tools/owner_certify_s12.py` | `C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD` | `docs/gates/owner_certify_s12.sha256`, `tools/owner_verify_s12.ps1` |
| every pinned file (138) | — | `docs/gates/s12_pins.sha256` (checked by `S12-PIN`) |

---

## 3. The five layers

Each layer covers a failure the others do not. Do all five; layers 1–3 before any agent works again.

### 3.1 Layer 1: annotated tags at every certified state

A tag names one commit for good. Annotated tags carry the owner's name, date and message.

```powershell
cd C:\Users\Administrator\Documents\1SuperAgents
git fetch origin --tags
git tag -a s12-m14-certified 181b7f5 -m "S12 M1-M14 certified by owner_verify_s12.ps1; M0, M1, M8a, M14 reviewed"
git tag -a s12-stage2-pinned dac952e -m "S12 Stage 2 rulings recorded; golden set pin #4 before M15-M21 implementation"
git push origin s12-m14-certified s12-stage2-pinned
git ls-remote --tags origin
```

Naming: `<stage>-<scope>-<state>`, lowercase, for example `s12-m14-certified`, `s12-s15-certified`,
`adapters-<provider>-certified`. Never reuse or move a tag name; if a tag is wrong, create a new one with a suffix
(`-r2`) and note it in §10.

### 3.2 Layer 2: GitHub rulesets (prevents T1, T2, part of T10)

GitHub → repository → **Settings → Rules → Rulesets → New ruleset**. Owner account only.

**Ruleset A: "certified tags"**

| Setting | Value |
|---|---|
| Target | Tags; include patterns `s0-*`, `s12-*`, `adapters-*` |
| Enforcement | Active |
| Rules | Restrict creations (owner only), Restrict updates, Restrict deletions |
| Bypass list | Repository admin (the owner) only |

**Ruleset B: "protected branches"**

| Setting | Value |
|---|---|
| Target | Branches; include `s12-work`, `s0-s11-*`, `backup/*`, `adapters-work` |
| Enforcement | Active |
| Rules | Block force pushes, Restrict deletions |
| Bypass list | Repository admin (the owner) only |

After the S12 tag, add **Restrict updates** to `s12-work` in ruleset B (it becomes read-only; fixes go through a
branch and an owner merge).

**Credentials.** Agents use a fine-grained token (or the GitHub App) with **Contents: read and write** on this
repository only, and **no Administration** permission, so they cannot change rulesets, create protected tags or bypass
the rules. The owner's own account keeps admin rights. Never give an agent the owner's token.

**Check that it works:** from an agent's credentials, `git push --force` to `s12-work` and `git push --delete origin
s12-m14-certified` must both be rejected.

### 3.3 Layer 3: copies outside this repository (T8, T9, last resort for T1/T2)

**3.3a Private mirror repository.** Create an empty private repository, for example `kiranapps2026/S12-backup`, that
no agent can access (not a fork: a fork of a private repository shares its access settings). Mirror into it after
every checkpoint in §4:

```powershell
cd C:\Users\Administrator\Documents\1SuperAgents
git fetch origin --prune --tags
git push --mirror https://github.com/kiranapps2026/S12-backup.git
```

`--mirror` copies every branch and tag exactly as they are in your local clone, so fetch first. Never mirror from a
clone an agent has worked in without checking §3.5 first, or a damage would be mirrored too (the bundles of §3.3b
are the guard against that).

**3.3b Offline bundles.** A bundle is one file holding the complete history, restorable with plain `git clone`.

```powershell
$dir = "D:\S12-backups"                                  # another drive, or a synced cloud folder
New-Item -ItemType Directory -Force $dir | Out-Null
$d = Get-Date -Format yyyy-MM-dd
$name = "S12-$d-s12-m14-certified.bundle"                # name it after the newest tag
git fetch origin --prune --tags
git bundle create "$dir\$name" --all
git bundle verify "$dir\$name"
(Get-FileHash "$dir\$name" -Algorithm SHA256).Hash | Out-File "$dir\$name.sha256" -Encoding ascii
```

Retention: keep **every** bundle made at a tag; keep the last 5 others. Keep at least two places (for example a
second drive and a cloud folder). Record each one in §10.

**3.3c What is not in git.** These live outside the repository and need their own copy:

| Item | Where | Backup |
|---|---|---|
| `.env` (database URLs, keys) | repository root, untracked | password manager or encrypted vault, never in the bundle folder in plain text |
| Test database contents | PostgreSQL | not needed: every golden run creates its own schema |
| Production database (later) | PostgreSQL | `pg_dump` schedule, part of the operations phase |
| GitHub settings (rulesets, tokens) | GitHub | screenshot or export the ruleset JSON after each change, keep with the bundles |

### 3.4 Layer 4: keep new work away from certified code (T3, T6, T7)

Branch model from the S12 tag onwards:

```
s12-s15-certified (tag) ──> s12-work (read-only)
          │
          └──> adapters-work ──> adapters/<provider> (one per agent task)
```

```powershell
git fetch origin --tags
git switch -c adapters-work s12-s15-certified
git push -u origin adapters-work
```

Rules:
1. Agents work only on `adapters/<provider>` (or another task branch named in their prompt), in their **own worktree**
   with their **own Python environment** and **own test database**:
   ```powershell
   git worktree add ..\S12-adapters-<provider> -b adapters/<provider> origin/adapters-work
   ```
2. Only the owner merges a task branch into `adapters-work`, after §3.5 passes on the task branch. Merge, never rebase.
3. Nothing is merged back into `s12-work` after the tag. A fix to certified S12 code is its own branch from the tag,
   with its own golden case, re-certified, and a new tag (`s12-s15-certified-r2`).
4. One agent per worktree. Remove a worktree when its task ends (`git worktree remove`, then `git worktree prune`).

### 3.5 Layer 5: detection before accepting any agent's work

The owner tools already detect tampering. Run this before every merge, pin, checkpoint or mirror:

```powershell
cd C:\Users\Administrator\Documents\1SuperAgents
git fetch origin --prune --tags
git status --short                                                     # must print nothing
(Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256).Hash       # must equal §2.5
python tools\owner_certify_s12.py --selftest                           # exit 0
python tools\owner_certify_s12.py --milestone M21 --fast               # S12-PIN, S12-FRZ, S12-S011, S12-DOC, S12-REC PASS
git diff s12-stage2-pinned --stat -- tests_golden tools\owner_pin_s12.ps1 tools\owner_verify_s12.ps1 tools\owner_certify_s12.py   # empty unless a pin was made since
git ls-remote --tags origin                                            # every tag of §2.1 at its commit
git log --format="%h %an %s" -20 origin/s12-work                       # read every commit message and author
```

Meaning of a failure:

| Row fails | What happened | Playbook |
|---|---|---|
| `S12-PIN` | a pinned golden file or owner tool changed since the last pin | §5.2 / §5.4 |
| `S12-FRZ` | a frozen S0–S11 file changed | §5.3 |
| certifier hash differs | `owner_certify_s12.py` itself changed | §5.4, then stop all agents |
| a tag points elsewhere or is missing | tag moved or deleted | §5.7 |
| `G-Mxx` red that was green | a regression | §5.1 |

---

## 4. Routines: when to do what

### 4.1 After every owner checkpoint or pin (2 minutes)
1. §3.5 detection passes.
2. `git push --mirror` to the backup repository (§3.3a).
3. Add a line to §10.

### 4.2 At every certified milestone group (for example M15–M21)
1. Everything in 4.1.
2. A bundle (§3.3b) named after the newest tag.

### 4.3 At the S12 tag (`s12-s15-certified`)
1. M21 certified by `owner_verify_s12.ps1 M21`, reviewed (`s12_tracker.py set M21 reviewed`).
2. Certification report and deferred register committed.
3. Tag (answer **y** to the offer of `owner_verify_s12.ps1 M21`, or by hand):
   ```powershell
   git tag -a s12-s15-certified <M21 checkpoint commit> -m "S12-S15 certified (M0-M21), report and deferred register written"
   git push origin s12-s15-certified
   ```
4. Bundle, mirror, §10.
5. Ruleset B: add **Restrict updates** to `s12-work`.
6. Create `adapters-work` (§3.4).

### 4.4 Start and end of every agent session
Start:
```powershell
git fetch origin; git status --short; git worktree list; echo "GOLDEN_SABOTAGE=[$env:GOLDEN_SABOTAGE]"
```
End (before accepting its report): `git status --short` in its worktree prints nothing, its branch is pushed, and
§3.5 passes on that branch.

### 4.5 Monthly
1. Restore drill (§7) from the newest bundle.
2. `git bundle verify` on every kept bundle; compare each `.sha256`.
3. Re-read the rulesets on GitHub; they must still match §3.2.

---

## 5. Restore playbooks

Rule for every playbook: **never rewrite shared history** (no `reset --hard` + force-push on a shared branch, no
rebase). Fix forward with new commits, so every agent's clone stays valid. The only exception is §5.5 with the owner's
bypass, after all agents are stopped.

Before any restore, stop all agents and copy the damaged state so nothing is lost:
```powershell
git switch -c incident/<date>-<what> ; git push -u origin incident/<date>-<what>
```

### 5.1 A bad commit was pushed (T6)
```powershell
git switch s12-work; git pull origin s12-work
git log --oneline -15                                      # find the bad commit(s)
git revert --no-edit <bad>                                 # one per bad commit, newest first
python -m pytest -q -p no:cacheprovider tests_golden/s12   # back to the last good count
git push origin s12-work
```
A merge commit: `git revert -m 1 <merge>`.

### 5.2 A golden file was edited (T3)
```powershell
git log --oneline -5 -- tests_golden/s12/M19_recovery.py             # who changed it, when
git diff s12-stage2-pinned -- tests_golden                           # what differs from the last pinned state
git restore --source s12-stage2-pinned -- tests_golden/s12/M19_recovery.py   # or the newest pin commit
git commit -m "Owner: restore pinned golden file (agent edit reverted)"; git push origin s12-work
python tools\owner_certify_s12.py --milestone M21 --fast             # S12-PIN PASS again
```
If the edit was a genuine test fix, it goes through the test-author role, a commit starting `golden:` and a new pin
instead (as done for `67b044d` and `2ee4dd1`).

### 5.3 A frozen S0–S11 file was edited (T4)
```powershell
git diff s0-s11-certified -- src/adapters/postgres/admin.py           # example file
git restore --source s0-s11-certified -- src/adapters/postgres/admin.py
git commit -m "Owner: restore frozen S0-S11 file"; git push origin s12-work
python tools\owner_certify_s12.py --milestone M21 --fast             # S12-FRZ PASS
```
A change to a frozen file is only ever made under gate §19.3 change control with an owner ruling.

### 5.4 An owner tool or pin was edited, or an agent used owner powers (T5, T10)
1. Stop all agents.
2. Compare: `git diff s12-stage2-pinned -- tools docs/gates/s12_pins.sha256 docs/gates/owner_certify_s12.sha256`.
3. Restore from the tag: `git restore --source s12-stage2-pinned -- <file>`; commit, push.
4. Check the certifier hash (§2.5) and run `--selftest`.
5. If an agent ran `owner_pin_s12.ps1`: read the pin commit's diff; if it pinned anything you did not review, restore
   `docs/gates/s12_pins.sha256` from the previous pin commit and pin again yourself.
6. Remove that agent's write access until §6 is in its prompt.

### 5.5 History was rewritten (force-push, T1)
1. Do not pull. Every clone that still has the old commits is a source.
2. Find the lost head, in this order:
   - your local clone: `git reflog show origin/s12-work` and `git reflog` (old commits stay there for 90 days);
   - the mirror: `git fetch https://github.com/kiranapps2026/S12-backup.git s12-work:refs/remotes/backup/s12-work`;
   - the newest bundle: `git fetch D:\S12-backups\<bundle> s12-work:refs/remotes/bundle/s12-work`.
3. Save it before doing anything else:
   ```powershell
   git branch backup/s12-work-before-rewrite-<date> <lost head>
   git push origin backup/s12-work-before-rewrite-<date>
   ```
4. Restore by **merge** (keeps everyone's clone valid), as was done with `f76a7f4`:
   ```powershell
   git switch s12-work; git pull origin s12-work
   git merge backup/s12-work-before-rewrite-<date>
   ```
   Resolve conflicts keeping the certified side for `tests_golden/`, `tools/owner_*` and frozen files.
5. Run the full suite and §3.5; push. Then fix layer 2 so it cannot happen again.

### 5.6 A branch was deleted (T2)
```powershell
git ls-remote --heads origin                                    # confirm it is gone
git reflog show origin/<branch>                                 # last known head, or take it from §2.2 / the mirror
git push origin <hash>:refs/heads/<branch>
```

### 5.7 A tag was moved or deleted (T2)
```powershell
git ls-remote --tags origin
git rev-parse <tag>^{commit}           # your local copy; compare with §2.1
git push origin :refs/tags/<tag>       # remove the wrong remote tag (owner bypass)
git push origin <tag>                  # push your correct local tag
```
If your local tag is also wrong, take it from the mirror (`git fetch <mirror> "refs/tags/*:refs/tags/*"`) or a bundle.

### 5.8 Uncommitted, misplaced or half-pushed work (T7)
```powershell
git status --short                     # anything listed is not on GitHub
git stash push -m "<what and why>" -- <paths>      # keep a copy before cleaning
git stash list ; git stash show -p stash@{N}
```
A push that left a file behind (as with `checkpoints.py`): add, commit and push the missing file at once; run the suite
on the remote head. Never `git add -A` in a folder an agent used.

### 5.9 The repository is damaged or GitHub is unavailable (T8)
```powershell
git clone D:\S12-backups\<newest bundle> S12-restore
cd S12-restore
git branch -a; git tag                 # all branches and tags from the bundle
git remote set-url origin https://github.com/kiranapps2026/S12.git   # when GitHub is back, or a new repository
```
Or clone the mirror repository directly.

### 5.10 The owner machine is lost (T9)
1. New machine: install Git, Python, PostgreSQL.
2. `git clone https://github.com/kiranapps2026/S12.git` (or the mirror, or a bundle from the second location).
3. Restore `.env` from the vault (§3.3c).
4. `python tools\owner_certify_s12.py --selftest` and §3.5.
5. Rotate every token the old machine held.

### 5.11 Records damaged (ruling columns changed)
```powershell
git log -p --follow -- docs/gates/S12_RECORDS.md | more
git restore --source <last good commit> -- docs/gates/S12_RECORDS.md
python tools\doc_consistency.py ; python tools\s12_tracker.py check
```
Commit as `Owner: restore records`. Rulings are only ever written by the owner.

---

## 6. Rules for agents

Paste this block into every agent prompt from now on (implementation, test-author, adapter):

> **Repository safety rules (owner policy, `docs/gates/BACKUP_AND_RESTORE.md`).**
> 1. Work only on the branch and in the folder this prompt names. Never switch to `s12-work`, `s0-s11-*`,
>    `backup/*` or `adapters-work` to commit.
> 2. Never force-push, rebase a pushed branch, delete a branch, or create, move or delete a tag.
> 3. Never run `tools/owner_*` scripts, never edit `tools/owner_*`, `docs/gates/s12_pins.sha256`,
>    `docs/gates/owner_certify_s12.sha256`, frozen S0–S11 files, or the owner columns of the record files.
> 4. Never edit `tests_golden/` unless this prompt explicitly makes you the test-author session.
> 5. Before every push: `git status --short` shows only files you meant to commit; stage files by name, never
>    `git add -A`. After pushing, `git status --short` prints nothing.
> 6. If anything here blocks your task, stop and report; do not work around it.

---

## 7. Restore drill

Monthly, and once now, so the procedure is known to work before it is needed. About 15 minutes.

```powershell
$drill = "$env:TEMP\s12-restore-drill"
Remove-Item -Recurse -Force $drill -ErrorAction SilentlyContinue
git clone D:\S12-backups\<newest bundle> $drill
cd $drill
git tag                                           # every tag of §2.1
git rev-parse s12-m14-certified^{commit}          # equals §2.1
git switch --detach s12-m14-certified
(Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256).Hash   # equals §2.5
python tools\owner_certify_s12.py --selftest
cd ..; Remove-Item -Recurse -Force $drill
```
Record the result in §10 (`drill: pass`).

---

## 8. Windows notes

- **Line endings.** Git warns "CRLF will be replaced by LF" on the pin files; that is expected. Pins are compared after
  normalisation, so do not change `core.autocrlf` in the middle of a phase.
- **Editing pinned files.** Use an editor or a small Python script reading and writing bytes (as for `2ee4dd1`).
  PowerShell's `Get-Content`/`Set-Content` can change the encoding of non-ASCII text (`→`, `—`) and so every hash.
- **Pager.** `git log` may open a pager showing `(END)`: press `q`.
- **Locked folders.** A folder that a terminal, editor or agent still uses cannot be deleted; close it first (or
  restart) and then `git worktree prune`.
- **Typing code into PowerShell.** Python lines such as `assert ...` are not PowerShell commands; they go into files.

---

## 9. Checklists

### 9.1 Now (before any agent works again)
- [ ] Tags `s12-m14-certified` (`181b7f5`) and `s12-stage2-pinned` (`dac952e`) created and pushed (§3.1)
- [ ] Ruleset A (tags) and ruleset B (branches) active, owner-only bypass (§3.2)
- [ ] Agent tokens without Administration permission (§3.2)
- [ ] Backup repository created; first `git push --mirror` (§3.3a)
- [ ] First bundle on two locations, `.sha256` beside it (§3.3b)
- [ ] `.env` stored in a vault (§3.3c)
- [ ] §6 rules pasted into the running implementation prompt
- [ ] First restore drill passed (§7)
- [ ] §10 filled in

### 9.2 At the S12 tag
- [ ] M15–M21 certified, M21 reviewed, certification report and deferred register committed
- [ ] `s12-s15-certified` tagged and pushed
- [ ] Bundle (two locations) and mirror
- [ ] `s12-work` set to Restrict updates in ruleset B
- [ ] `adapters-work` created from the tag (§3.4)

### 9.3 Before the adapter phase
- [ ] Each adapter agent has its own branch, worktree, Python environment and test database (§3.4)
- [ ] §6 rules in every adapter prompt
- [ ] §3.5 detection run before every merge into `adapters-work`

---

## 10. Backup log

Append one line per action. Newest last.

| Date | Action | Tag / commit | Location | SHA256 (bundles) | By |
|---|---|---|---|---|---|
| 2026-10-03 | document written; inventory at `dac952e` | `dac952e` | `docs/gates/BACKUP_AND_RESTORE.md` | — | owner |
| | | | | | |
