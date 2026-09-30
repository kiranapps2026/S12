"""Canonical state machines (STATE_TRANSITIONS §1–§3, gate Appendix A): the only legal moves.

Values are the stored (lowercase) ones. A move outside these tables raises IllegalStateTransition
before anything is written; terminal states have no outgoing edge."""
from __future__ import annotations

import types

from contracts.errors import StateTransitionError  # noqa: F401 (re-exported)

RUN = types.MappingProxyType({
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "partial", "failed", "cancelled", "dead_letter", "reconciling"}),
    "reconciling": frozenset({"completed", "partial", "failed", "dead_letter", "cancelled"}),
    "completed": frozenset(), "partial": frozenset(), "failed": frozenset(),
    "cancelled": frozenset(), "dead_letter": frozenset(),
})

STEP = types.MappingProxyType({
    "pending": frozenset({"running", "skipped", "cancelled"}),
    "running": frozenset({"completed", "partial", "failed", "cancelled", "timeout", "pending_probe"}),
    "timeout": frozenset({"pending_probe"}),
    "unknown": frozenset({"pending_probe", "dead_letter"}),
    "pending_probe": frozenset({"completed", "pending", "failed", "dead_letter"}),
    "completed": frozenset(), "partial": frozenset(), "failed": frozenset(),
    "cancelled": frozenset(), "skipped": frozenset(), "dead_letter": frozenset(),
})

BUDGET = types.MappingProxyType({
    "pending": frozenset({"reserved", "released"}),
    "reserved": frozenset({"locked", "released"}),
    "locked": frozenset({"committed", "released"}),
    "committed": frozenset(), "released": frozenset(),
})

TERMINAL_STEP = frozenset(s for s, to in STEP.items() if not to)


def _check(table, kind: str, current: str, new: str) -> None:
    if new not in table.get(current, frozenset()):
        raise StateTransitionError(f"illegal {kind} transition {current} -> {new}")


def check_run(current: str, new: str) -> None:
    _check(RUN, "run", current, new)


def check_step(current: str, new: str) -> None:
    _check(STEP, "step", current, new)


def check_budget(current: str, new: str) -> None:
    _check(BUDGET, "budget", current, new)
