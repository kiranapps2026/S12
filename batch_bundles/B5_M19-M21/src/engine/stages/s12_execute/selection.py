"""Worker selection and lease acquisition for one step (gate §8 steps 2–3, C5; WORKER_LIFECYCLE §13).

Candidates arrive already filtered for eligibility (C39, M8a). A worker at capacity is never chosen (C5). The score is
the §13 weighted sum over the signals that exist in this phase: state locality (1.0 on the execution's current owner,
else 0.0; no worker versions or hosts are recorded, so the 0.7/0.5 tiers never apply) and free capacity; health,
queue, fairness and cost have no inputs yet and add nothing. Locality is advisory: it only breaks the ordering, never
the capacity rule. Ties go to the smallest ``worker_id``, so selection is deterministic.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import TypeVar

from contracts.execution_states import StepTerminalReason
from engine.stages.s12_execute.eligibility import WorkerCandidate

LOCALITY_WEIGHT = 0.30
CAPACITY_WEIGHT = 0.20

L = TypeVar("L")


def score(candidate: WorkerCandidate, *, current_owner: str | None) -> float:
    locality = 1.0 if candidate.worker_id == current_owner else 0.0
    free = 1.0 - candidate.current_load / candidate.capacity
    return LOCALITY_WEIGHT * locality + CAPACITY_WEIGHT * free


def select_worker(candidates: Iterable[WorkerCandidate], *, current_owner: str | None) -> str | None:
    """The best-scoring worker with free capacity, or None when every candidate is full (or there is none)."""
    selectable = [c for c in candidates if 0 <= c.current_load < c.capacity]
    if not selectable:
        return None
    return min(selectable, key=lambda c: (-score(c, current_owner=current_owner), c.worker_id)).worker_id


async def lease_for_step(*, candidates: Callable[[], Awaitable[Sequence[WorkerCandidate]]],
                         acquire: Callable[[str], Awaitable[L | None]], current_owner: str | None,
                         max_attempts: int) -> L | str:
    """Select and lease, re-reading the candidates after every failed round, at most ``max_attempts`` rounds.

    No eligible candidate on a read → ``no_worker``. Candidates exist but no lease was obtained within the bound
    (every acquisition refused, or every candidate full) → ``lease_unavailable``.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")
    for _ in range(max_attempts):
        pool = await candidates()
        if not pool:
            return StepTerminalReason.NO_WORKER
        worker_id = select_worker(pool, current_owner=current_owner)
        if worker_id is not None:
            lease = await acquire(worker_id)
            if lease is not None:
                return lease
    return StepTerminalReason.LEASE_UNAVAILABLE
