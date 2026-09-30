"""S12-S15 milestone tracker.

Reads docs/gates/s12_milestones.json (status per milestone), the three append-only records (S12_RECORDS.md,
S12_STOPS.md, S12_DEFECTS.md) and the git history (`s12: Mxx ...` commits), and writes docs/gates/S12_TRACKER.md.

    python tools/s12_tracker.py report            # regenerate S12_TRACKER.md and print the summary
    python tools/s12_tracker.py set M07 red_confirmed
    python tools/s12_tracker.py check             # exit 1 when a rule below is broken

This is the interim tracker. The plan's S12_PROGRESS.md is generated from the owner certifier's results and stays the
source of truth once `owner_certify_s12.py` exists; this file only adds the record counts and the ordering rules.

Status order:  not_started -> red_confirmed -> in_progress -> green -> reviewed
  * red_confirmed : the golden tests were run on the current code and FAIL (a golden test that already passes is rejected)
  * green         : golden tests, sabotage, invariants and the S0-S11 certifier pass (the certifier decides, not this tool)
  * reviewed      : required for star milestones before the next milestone starts (owner review)
Rules enforced by `set` and `check`:
  * status moves forward one step at a time (moving backwards is always allowed)
  * green / reviewed need: no open CONF, no open or ruled-but-unapplied STOP, and for reviewed no open DEF, for that milestone
  * a milestone cannot leave not_started while an earlier one is below green (below reviewed for a star milestone)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / "docs" / "gates"
DATA = GATES / "s12_milestones.json"
OUT = GATES / "S12_TRACKER.md"
ORDER = ["not_started", "red_confirmed", "in_progress", "green", "reviewed"]
ROW = re.compile(r"^\|\s*((?:CONF|STOP|DEF)-\d+)\s*\|(.*)\|\s*$")


def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def milestone_key(cell: str) -> str:
    match = re.search(r"\bM\d+a?\b", cell)
    return match.group(0) if match else ""


def records() -> dict[str, list[dict]]:
    """Open entries per kind. Columns: CONF/STOP -> ID | milestone | status ...; DEF -> ID | caused by | status ..."""
    out: dict[str, list[dict]] = {"CONF": [], "STOP": [], "DEF": []}
    for name in ("S12_RECORDS.md", "S12_STOPS.md", "S12_DEFECTS.md"):
        path = GATES / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = ROW.match(line)
            if match:
                cells = [c.strip() for c in match.group(2).split("|")]
                out[match.group(1).split("-")[0]].append({"id": match.group(1), "milestone": milestone_key(cells[0]), "status": cells[1].lower(), "summary": cells[3] if len(cells) > 3 else ""})
    return out


def blocking(rec: dict[str, list[dict]], mid: str, for_status: str) -> list[str]:
    reasons = []
    for e in rec["CONF"]:
        if e["milestone"] == mid and e["status"] == "open":
            reasons.append(f"{e['id']} (open conflict)")
    for e in rec["STOP"]:
        if e["milestone"] == mid and e["status"] in ("open", "ruled"):
            reasons.append(f"{e['id']} (STOP {e['status']})")
    if for_status == "reviewed":
        for e in rec["DEF"]:
            if e["milestone"] == mid and e["status"] == "open":
                reasons.append(f"{e['id']} (open defect)")
    return reasons


def commits(mid: str) -> int:
    try:
        out = subprocess.run(["git", "log", "--oneline", "--extended-regexp", f"--grep=^s12: {mid}( |:)"], cwd=ROOT, capture_output=True, text=True, check=False)
        return len([line for line in out.stdout.splitlines() if line.strip()])
    except OSError:
        return 0


def ready_to_start(ms: list[dict], index: int) -> str:
    for earlier in ms[:index]:
        need = "reviewed" if earlier["review"] else "green"
        if ORDER.index(earlier["status"]) < ORDER.index(need):
            return f"{earlier['id']} is {earlier['status']} (needs {need})"
    return ""


def problems(data: dict, rec: dict[str, list[dict]]) -> list[str]:
    out = []
    ms = data["milestones"]
    for i, m in enumerate(ms):
        if m["status"] not in ORDER:
            out.append(f"{m['id']}: unknown status {m['status']!r}")
            continue
        level = ORDER.index(m["status"])
        if level and (why := ready_to_start(ms, i)):
            out.append(f"{m['id']} is {m['status']} but {why}")
        if level >= ORDER.index("green"):
            out += [f"{m['id']} is {m['status']} but has {r}" for r in blocking(rec, m["id"], m["status"])]
    return out


def render(data: dict, rec: dict[str, list[dict]]) -> str:
    ms = data["milestones"]
    counts = {s: sum(m["status"] == s for m in ms) for s in ORDER}
    lines = ["# S12-S15 tracker", "",
             f"Generated {date.today().isoformat()} by `tools/s12_tracker.py report`. Do not edit by hand: change status with "
             "`python tools/s12_tracker.py set Mxx <status>`. The owner certifier output (S12_PROGRESS.md), when it exists, overrides this file.", "",
             "**Summary:** " + ", ".join(f"{counts[s]} {s}" for s in ORDER) + f" of {len(ms)} milestones. "
             f"Open: {sum(e['status'] == 'open' for e in rec['CONF'])} conflicts, {sum(e['status'] in ('open', 'ruled') for e in rec['STOP'])} stops, "
             f"{sum(e['status'] == 'open' for e in rec['DEF'])} defects.", ""]
    nxt = next((m for i, m in enumerate(ms) if m["status"] != ("reviewed" if m["review"] else "green") and not ready_to_start(ms, i)), None)
    if nxt:
        lines += [f"**Next:** {nxt['id']} {nxt['title']} (model: {nxt['model']}, complexity: {nxt['complexity']}, status: {nxt['status']})", ""]
    lines += ["| Milestone | Batch | Status | Complexity | Model | Review | Prototype state | Commits | Open CONF | Open STOP | Open DEF |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ms:
        oc, os_, od = (sum(e["milestone"] == m["id"] and e["status"] in st for e in rec[k]) for k, st in (("CONF", ("open",)), ("STOP", ("open", "ruled")), ("DEF", ("open",))))
        lines.append(f"| {m['id']} {m['title']} | {m['batch']} | {m['status']} | {m['complexity']} | {m['model']} | {'★' if m['review'] else ''} | {m['prototype_state']} | {commits(m['id'])} | {oc} | {os_} | {od} |")
    bad = problems(data, rec)
    lines += ["", "## Rule violations", ""] + ([f"- {b}" for b in bad] if bad else ["None."])
    open_rows = [e for k in ("CONF", "STOP", "DEF") for e in rec[k] if e["status"] in ("open", "ruled")]
    lines += ["", "## Open records", ""] + ([f"- {e['id']} ({e['milestone'] or 'no milestone'}, {e['status']}): {e['summary']}" for e in open_rows] if open_rows else ["None."])
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    data, rec = load(), records()
    cmd = argv[1] if len(argv) > 1 else "report"
    if cmd == "report":
        OUT.write_text(render(data, rec), encoding="utf-8")
        print(render(data, rec))
        return 1 if problems(data, rec) else 0
    if cmd == "check":
        bad = problems(data, rec)
        print("\n".join(bad) if bad else "tracker consistent")
        return 1 if bad else 0
    if cmd == "set" and len(argv) == 4:
        mid, status = argv[2].upper(), argv[3]
        ms = data["milestones"]
        index = next((i for i, m in enumerate(ms) if m["id"] == mid), -1)
        if index < 0 or status not in ORDER:
            print(f"unknown milestone or status; statuses: {', '.join(ORDER)}")
            return 2
        m = ms[index]
        new, old = ORDER.index(status), ORDER.index(m["status"])
        if new > old + 1:
            print(f"{mid}: cannot jump from {m['status']} to {status}; next is {ORDER[old + 1]}")
            return 1
        if new > old and (why := ready_to_start(ms, index)):
            print(f"{mid}: cannot advance: {why}")
            return 1
        if new >= ORDER.index("green") and (why := blocking(rec, mid, status)):
            print(f"{mid}: cannot become {status}: " + "; ".join(why))
            return 1
        m["status"] = status
        DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        OUT.write_text(render(data, rec), encoding="utf-8")
        print(f"{mid} -> {status}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
