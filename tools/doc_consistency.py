"""Document consistency check for the S12-S15 specification set.

Read-only. Compares the places where the same fact is written down more than once and prints every mismatch as a
CONF candidate. It decides nothing: a finding is a question for the ruling process (precedence: gate Appendix A >
gate rulings > gate sections > repaired documents > code sketches), not a verdict.

    python tools/doc_consistency.py                # human report, exit 1 when unaccepted findings exist
    python tools/doc_consistency.py --json         # machine report
    python tools/doc_consistency.py --list-checks

Checks
  C1  Transition edges: gate Appendix A.x  vs  STATE_TRANSITIONS.md (arrow lists)      for every machine
  C2  Step edges: gate Appendix A.2        vs  DATA_CONTRACTS.md section 19.2 (python dict)
  C3  StepState members: DATA_CONTRACTS 19.1 vs STATE_TRANSITIONS section 2 vs Appendix A.2
  C4  Ruling references: every `Cnn` / `Dn` cited in the plan or other documents has a heading in the gate
  C5  Version pins: gate / architecture versions quoted by the plan equal the versions in the documents
  C6  Milestone references: every `Mxx` cited in the gate exists in the plan
  C7  Structure: every checked document has balanced code fences (an unclosed fence hides later text from readers and tools)

A finding that the owner has ruled on is listed in docs/gates/S12_CONFLICTS_ACCEPTED.txt (one `key | ruling` per line)
and no longer fails the run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMPL = ROOT / "docs" / "implementation"
GATE = IMPL / "S12_S15_EXECUTION_GATE.md"
PLAN = IMPL / "S12_S15_IMPLEMENTATION_PLAN.md"
STATES = IMPL / "STATE_TRANSITIONS.md"
CONTRACTS = IMPL / "DATA_CONTRACTS.md"
ARCH = IMPL / "FINAL_ARCHITECTURE.md"
ACCEPTED = ROOT / "docs" / "gates" / "S12_CONFLICTS_ACCEPTED.txt"

# gate Appendix A section -> (STATE_TRANSITIONS section number, machine name)
MACHINES = {
    "A.1": (1, "run"), "A.2": (2, "step"), "A.3": (3, "budget reservation"), "A.4": (5, "lease"),
    "A.5": (4, "worker"), "A.6": (9, "dead letter"), "A.7": (10, "reconciliation episode"),
    "A.8": (8, "confirmation"), "A.9": (11, "circuit breaker"),
}
ARROW = re.compile(r"\b([A-Za-z_]+)\s*(?:──→|-->|->|→)\s*([A-Za-z_]+)")
Edge = tuple[str, str]
# Documented as in-memory or non-state tokens; they are not persisted states, so edges touching them are not compared.
IGNORED_NODES = {"A.3": {"pending"}, "A.4": {"pending"}, "A.7": {"none", "resolves"}}
# Milestone ids of the S0-S11 multi-step series (M2a chains), not S12-S15 plan milestones.
NUMBERED_HEADING = re.compile(r"^#{2,4} (?:\d+(?:\.\d+)*[. ]|A\.\d|APPENDIX)")
FOREIGN_MILESTONES = {"M2a", "M2b", "M2c"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, heading_re: str, level: int) -> str:
    """Body of the first heading matching heading_re, up to the next heading of the same or higher level.
    Lines inside code fences are never headings (a python comment starts with '# ')."""
    marks = "#" * level
    start_re = re.compile(rf"^{marks} {heading_re}")
    stop_re = re.compile(rf"^#{{1,{level}}} ")
    body: list[str] = []
    fenced = collecting = False
    for line in text.splitlines():
        if fenced and NUMBERED_HEADING.match(line):
            fenced = False  # an unclosed fence (reported by C7) must not swallow the rest of the document
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and collecting and stop_re.match(line):
            break
        elif not fenced and not collecting and start_re.match(line):
            collecting = True
            continue
        if collecting:
            body.append(line)
    return "\n".join(body)


def split_alternatives(cell: str) -> list[str]:
    cell = re.sub(r"\*\*.*?\*\*", "", cell)
    return [p.strip().strip("`").lower() for p in cell.split("/") if p.strip().strip("`")]


def appendix_edges(gate: str, key: str) -> set[Edge] | None:
    body = section(gate, rf"{re.escape(key)} ", 3)
    if not body:
        return None
    edges: set[Edge] = set()
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or len(cells) < 2 or cells[0].lower() in ("from", "") or set(cells[0]) <= {"-", " "}:
            continue
        for a in split_alternatives(cells[0]):
            for b in split_alternatives(cells[1]):
                if re.fullmatch(r"[a-z_]+", a) and re.fullmatch(r"[a-z_]+", b):
                    edges.add((a, b))
    if not edges:  # prose form (A.8, A.9): `a -> b | c`, `a -> b` (`reason`)
        flat = body.replace("`", "")
        for a, rhs in re.findall(r"\b([a-z_]+) (?:→|->) ([a-z_]+(?: \| [a-z_]+)*)", flat):
            edges |= {(a, b.strip()) for b in rhs.split("|")}
    return edges or None


def arrow_edges(states: str, number: int) -> set[Edge] | None:
    body = section(states, rf"{number}\. ", 2)
    if not body:
        return None
    # legal edges only: stop at the first "Illegal" / "Invalid" heading line inside a code block
    legal = re.split(r"^\s*(?:Illegal|Invalid)[^\n]*$", body, maxsplit=1, flags=re.M)[0]
    edges = {(a.lower(), b.lower()) for a, b in ARROW.findall(legal)}
    return edges or None


def contracts_step_edges(contracts: str) -> set[Edge] | None:
    body = section(contracts, r"19\.2 ", 3)
    if not body:
        return None
    edges: set[Edge] = set()
    for src, targets in re.findall(r"StepState\.(\w+):\s*\{(.*?)\}", body, re.S):
        for dst in re.findall(r"StepState\.(\w+)", targets):
            edges.add((src.lower(), dst.lower()))
    return edges or None


def enum_members(contracts: str) -> set[str]:
    body = section(contracts, r"19\.1 ", 3)
    return {m.lower() for m in re.findall(r'^\s+([A-Z_]+)\s*=\s*"', body, re.M)}


def states_members(states: str) -> set[str]:
    body = section(states, r"2\. ", 2)
    match = re.search(r"StepState members[^\n]*\n((?:[ \t]+[A-Z_, \n]+)+)", body)
    return {m.lower() for m in re.findall(r"[A-Z_]{3,}", match.group(1))} if match else set()


def finding(check: str, key: str, message: str, detail: list[str] | None = None) -> dict:
    return {"check": check, "key": f"{check}:{key}", "message": message, "detail": detail or []}


def diff_edges(check: str, key: str, label_a: str, a: set[Edge], label_b: str, b: set[Edge]) -> list[dict]:
    out = []
    only_a, only_b = sorted(a - b), sorted(b - a)
    if only_a or only_b:
        detail = [f"only in {label_a}: {x} -> {y}" for x, y in only_a] + [f"only in {label_b}: {x} -> {y}" for x, y in only_b]
        out.append(finding(check, key, f"{label_a} and {label_b} disagree on {len(only_a) + len(only_b)} edge(s)", detail))
    return out


def check_edges(gate: str, states: str, contracts: str) -> tuple[list[dict], list[str]]:
    found, notes = [], []
    for key, (number, name) in MACHINES.items():
        if key == "A.5":
            notes.append("C1 A.5 (worker): by design Appendix A defers to STATE_TRANSITIONS s4 (no table to compare)")
            continue
        ref = appendix_edges(gate, key)
        other = arrow_edges(states, number)
        if ref is None:
            notes.append(f"C1 {key} ({name}): Appendix A table not parsed - check by hand")
        elif other is None:
            notes.append(f"C1 {key} ({name}): STATE_TRANSITIONS section {number} not parsed as arrows - check by hand")
        else:
            drop = IGNORED_NODES.get(key, set())
            ref = {e for e in ref if not drop & set(e)}
            other = {e for e in other if not drop & set(e)}
            found += diff_edges("C1", f"{key}-{name.replace(' ', '_')}", f"gate {key}", ref, f"STATE_TRANSITIONS s{number}", other)
    ref, dc = appendix_edges(gate, "A.2"), contracts_step_edges(contracts)
    if ref is None or dc is None:
        notes.append("C2 step edges: DATA_CONTRACTS 19.2 or Appendix A.2 not parsed - check by hand")
    else:
        found += diff_edges("C2", "step-A.2-vs-DATA_CONTRACTS", "gate A.2", ref, "DATA_CONTRACTS 19.2", dc)
    return found, notes


def check_members(gate: str, states: str, contracts: str) -> tuple[list[dict], list[str]]:
    dc, st = enum_members(contracts), states_members(states)
    ap = {s for e in (appendix_edges(gate, "A.2") or set()) for s in e}
    if not dc or not st:
        return [], ["C3 StepState members: enum block not parsed - check by hand"]
    found = []
    if dc != st:
        found.append(finding("C3", "step-members-DC-vs-ST", "StepState members differ between DATA_CONTRACTS 19.1 and STATE_TRANSITIONS 2",
                             [f"only in DATA_CONTRACTS: {m}" for m in sorted(dc - st)] + [f"only in STATE_TRANSITIONS: {m}" for m in sorted(st - dc)]))
    extra = ap - dc
    if extra:
        found.append(finding("C3", "step-members-A2-not-in-enum", "Appendix A.2 uses states the enum does not define", sorted(extra)))
    return found, []


def check_rulings(gate: str, others: dict[str, str]) -> list[dict]:
    defined = set(re.findall(r"^#{2,4} (C\d+)\b", gate, re.M)) | set(re.findall(r"^#{2,4} (D\d+)\b", gate, re.M))
    defined |= set(re.findall(r"^\|\s*\**(C\d+|D\d+)\**\s*\|", gate, re.M))
    defined |= set(re.findall(r"^\*\*(D\d+)\b", gate, re.M))
    found = []
    for name, text in others.items():
        cited = set(re.findall(r"\b([CD]\d{1,2})\b", text))
        cited = {c for c in cited if not (c[0] == "D" and int(c[1:]) > 6)}  # D-numbers above D6 belong to other series
        missing = sorted(cited - defined, key=lambda c: (c[0], int(c[1:])))
        if missing:
            found.append(finding("C4", f"rulings-{name}", f"{name} cites rulings the gate defines no heading or row for", missing))
    return found


def check_versions(gate: str, plan: str, arch: str) -> list[dict]:
    found = []
    m = re.search(r"EXECUTION_GATE\.md`\s*\*\*(v\d+)\*\*", plan)
    g = re.search(r"\bv(\d+)\b", "\n".join(gate.splitlines()[:12]))
    if m and g and m.group(1) != f"v{g.group(1)}":
        found.append(finding("C5", "gate-version", f"plan pins gate {m.group(1)} but the gate header says v{g.group(1)}"))
    m = re.search(r"FINAL_ARCHITECTURE\.md`\s*\*\*v([\d.]+)\*\*", plan)
    a = re.search(r"\bv(\d+\.\d+\.\d+)\b", "\n".join(arch.splitlines()[:25]))
    if m and a and m.group(1) != a.group(1):
        found.append(finding("C5", "architecture-version", f"plan pins architecture v{m.group(1)} but the document says v{a.group(1)}"))
    return found


def check_milestones(gate: str, plan: str) -> list[dict]:
    defined = set(re.findall(r"^### (M\d+a?)\b", plan, re.M))
    cited = set(re.findall(r"\b(M\d{1,2}a?)\b", gate))
    missing = sorted(cited - defined - FOREIGN_MILESTONES, key=lambda c: (int(re.sub(r"\D", "", c)), c))
    return [finding("C6", "gate-cites-unknown-milestone", "gate cites milestones the plan does not define", missing)] if missing else []


def check_fences(docs: dict[Path, str]) -> list[dict]:
    """A fence with a language tag (```python) opened while another is still open means the earlier one was never closed."""
    found = []
    for path, text in docs.items():
        open_at = 0
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("```"):
                continue
            tagged = len(stripped) > 3
            if open_at and tagged:
                found.append(finding("C7", f"unclosed-fence-{path.name}-{open_at}",
                                     f"{path.name}: code fence opened at line {open_at} is never closed (next fence opens at line {number})"))
                open_at = number
            else:
                open_at = 0 if open_at else number
        if open_at:
            found.append(finding("C7", f"unclosed-fence-{path.name}-{open_at}", f"{path.name}: code fence opened at line {open_at} is never closed"))
    return found


def load_accepted() -> dict[str, str]:
    if not ACCEPTED.exists():
        return {}
    out = {}
    for line in read(ACCEPTED).splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, ruling = line.partition("|")
            out[key.strip()] = ruling.strip()
    return out


def run() -> tuple[list[dict], list[str], list[str]]:
    missing = [str(p.relative_to(ROOT)) for p in (GATE, PLAN, STATES, CONTRACTS, ARCH) if not p.exists()]
    if missing:
        return [], [], [f"missing document: {m}" for m in missing]
    gate, plan, states, contracts, arch = (read(p) for p in (GATE, PLAN, STATES, CONTRACTS, ARCH))
    found, notes = check_edges(gate, states, contracts)
    f3, n3 = check_members(gate, states, contracts)
    found += check_fences({p: t for p, t in zip((GATE, PLAN, STATES, CONTRACTS, ARCH), (gate, plan, states, contracts, arch))})
    found += f3 + check_versions(gate, plan, arch) + check_milestones(gate, plan)
    others = {"plan": plan, "STATE_TRANSITIONS": states, "DATA_CONTRACTS": contracts}
    found += check_rulings(gate, others)
    return found, notes + n3, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-checks", action="store_true")
    args = parser.parse_args()
    if args.list_checks:
        print("\n".join(line.strip() for line in (__doc__ or "").splitlines() if re.match(r"\s+C\d ", line)))
        return 0
    found, notes, errors = run()
    accepted = load_accepted()
    open_findings = [f for f in found if f["key"] not in accepted]
    if args.json:
        print(json.dumps({"findings": found, "accepted": sorted(accepted), "unparsed": notes, "errors": errors}, indent=2))
    else:
        for e in errors:
            print(f"ERROR  {e}")
        for f in found:
            tag = f"RULED ({accepted[f['key']]})" if f["key"] in accepted else "CONFLICT?"
            print(f"{tag:<10} {f['key']}: {f['message']}")
            for d in f["detail"]:
                print(f"             - {d}")
        for n in notes:
            print(f"UNPARSED   {n}")
        print(f"\n{len(open_findings)} unruled finding(s), {len(found) - len(open_findings)} ruled, {len(notes)} unparsed, {len(errors)} error(s)")
        if open_findings:
            print("Record each real conflict as CONF-nnn in docs/gates/S12_RECORDS.md; add its key to docs/gates/S12_CONFLICTS_ACCEPTED.txt once ruled.")
    return 1 if open_findings or errors else 0


if __name__ == "__main__":
    sys.exit(main())
