# S12 defects in already-passed work

Append-only. A defect is a bug found in work that a milestone had already passed (for example M12 code that breaks an M7
invariant). Record where it was found and which milestone caused it. `Severity`: `blocker` (data or money at risk, or a
fenced/idempotent write can be bypassed), `major`, `minor`. A milestone cannot be marked `reviewed` while a defect it
caused is `open`.

Status: `open`, `fixed` (fix commit recorded, golden test added or extended), `wontfix` (owner ruling required, cite it).

| ID | Caused by | Status | Opened | Found in | Severity | Description and reproduction | Fix commit / test |
|---|---|---|---|---|---|---|---|
