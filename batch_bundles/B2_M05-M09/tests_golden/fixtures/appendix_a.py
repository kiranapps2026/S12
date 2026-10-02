"""Gate Appendix A as data (owner fixture). The golden tests read the legal transitions from the pinned gate text itself,
so a golden test can never disagree with the gate by copying it wrongly.

    machines() -> {machine: Machine}
    Machine.edges: {(from, to): Edge}; Edge.reasons: frozenset | ANY_TERMINAL_REASON | ANY_REASON; Edge.produced: bool
    Machine.initial: (state, reason) | None

Machine names: run, step, reservation, lease, worker, dead_letter, episode, confirmation, breaker.
Rules taken from the Appendix A preamble and C24:
  * a "not produced" edge is legal for the validator (reasons as listed; ANY_REASON when none are listed);
  * `pending → cancelled` (step) accepts any StepTerminalReason value (C22);
  * `reconciling → cancelled` (run) takes "the same reasons as running → cancelled";
  * worker (A.5) implements STATE_TRANSITIONS §4 exactly; worker and confirmation list no reason codes, so any
    non-empty reason is accepted (CONF-012);
  * parenthesised text in a reason cell is a guard or a citation, never a reason code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "docs" / "implementation" / "S12_S15_EXECUTION_GATE.md"
STATES = ROOT / "docs" / "implementation" / "STATE_TRANSITIONS.md"

ANY_TERMINAL_REASON = "ANY_TERMINAL_REASON"
ANY_REASON = "ANY_REASON"

SECTIONS = {"run": "A.1", "step": "A.2", "reservation": "A.3", "lease": "A.4", "worker": "A.5",
            "dead_letter": "A.6", "episode": "A.7", "confirmation": "A.8", "breaker": "A.9"}


@dataclass(frozen=True)
class Edge:
    reasons: object          # frozenset[str] | ANY_TERMINAL_REASON | ANY_REASON
    produced: bool


@dataclass(frozen=True)
class Machine:
    name: str
    edges: dict
    initial: tuple | None
    terminal: frozenset


def _section(text: str, key: str) -> str:
    match = re.search(rf"^### {re.escape(key)} .*$", text, re.M)
    if not match:
        raise AssertionError(f"gate Appendix A section {key} not found")
    rest = text[match.end():]
    end = re.search(r"^#{2,3} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _strip_parens(cell: str) -> str:
    previous = None
    while previous != cell:
        previous, cell = cell, re.sub(r"\([^()]*\)", "", cell)
    return cell


def _states(cell: str) -> list[str]:
    return [s.strip().strip("`*").strip() for s in cell.split("/") if s.strip().strip("`*").strip()]


def _table(body: str) -> dict:
    edges: dict = {}
    copies = []
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or len(cells) < 3 or cells[0] in ("From", "") or set(cells[0]) <= {"-", " "}:
            continue
        sources, targets, cell = _states(cells[0]), _states(cells[1]), cells[2]
        produced = "not produced" not in cell
        if "any `StepTerminalReason`" in cell:
            reasons: object = ANY_TERMINAL_REASON
        elif "same reasons as" in cell:
            reasons = None
            copies.append((sources, targets, re.search(r"`(\w+) → (\w+)`", cell).groups()))
        else:
            found = frozenset(re.findall(r"`([a-z_]+)`", _strip_parens(cell.split("—")[0])))
            reasons = found or ANY_REASON
        for a in sources:
            for b in targets:
                edges[(a, b)] = Edge(reasons, produced)
    for sources, targets, (a0, b0) in copies:
        for a in sources:
            for b in targets:
                edges[(a, b)] = Edge(edges[(a0, b0)].reasons, True)
    return edges


def _initial(body: str) -> tuple | None:
    m = re.search(r"Initial on insert: `(\w+)` \(reason `(\w+)`\)", body)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"Created with status `(\w+)`.*?\(reason `(\w+)`\)", body, re.S)
    return (m.group(1), m.group(2)) if m else None


def _terminal(body: str) -> frozenset:
    m = re.search(r"Terminal: (.*?)(?:\.|\n)", body)
    return frozenset(re.findall(r"`(\w+)`", m.group(1))) if m else frozenset()


def _worker() -> dict:
    text = STATES.read_text(encoding="utf-8")
    body = text[text.index("## 4. Worker States"):text.index("## 5. Lease States")]
    legal = body.split("Illegal Transitions")[0]
    return {(a, b): Edge(ANY_REASON, True) for a, b in re.findall(r"\b([A-Z_]+)\s+──→\s+([A-Z_]+)\b", legal)}


def _prose(body: str) -> dict:
    """A.8 / A.9: `a → b` (`reason`, `reason`) and `a → b | c | d`."""
    edges: dict = {}
    flat = " ".join(body.split())
    for a, targets, reasons in re.findall(r"`(\w+) → ([\w |]+)`(?: \(([^)]*)\))?", flat):
        found = frozenset(re.findall(r"`(\w+)`", reasons)) or ANY_REASON
        for b in targets.split("|"):
            edges[(a, b.strip())] = Edge(found, True)
    return edges


@lru_cache(maxsize=1)
def machines() -> dict:
    text = GATE.read_text(encoding="utf-8")
    appendix = text[text.index("## APPENDIX A"):text.index("## APPENDIX B")]
    out = {}
    for name, key in SECTIONS.items():
        body = _section(appendix, key)
        if name == "worker":
            edges, initial, terminal = _worker(), None, frozenset({"TERMINATED"})
        elif name in ("confirmation", "breaker"):
            edges, initial = _prose(body), (("pending", "created") if name == "confirmation" else None)
            terminal = _terminal(body) if name == "confirmation" else frozenset()
        else:
            edges, initial, terminal = _table(body), _initial(body), _terminal(body)
        out[name] = Machine(name, edges, initial, terminal)
    return out
