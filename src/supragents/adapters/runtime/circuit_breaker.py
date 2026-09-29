"""Per-provider circuit breaker for a single node (gate C1: no shared state yet).

CLOSED → OPEN after ``failure_threshold`` consecutive failures; OPEN → HALF_OPEN once
``cooldown_seconds`` have passed; a success closes it, a failure while HALF_OPEN reopens it.
S8 reads ``state``; S12 reports outcomes with ``record_success`` / ``record_failure``.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from supragents.contracts.vocabulary import CircuitState


@dataclass
class _Provider:
    failures: int = 0
    opened_at: float | None = None


class InProcessCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._monotonic = monotonic
        self._providers: dict[str, _Provider] = {}

    async def state(self, provider: str) -> CircuitState:
        entry = self._providers.get(provider)
        if entry is None or entry.opened_at is None:
            return CircuitState.CLOSED
        if self._monotonic() - entry.opened_at >= self._cooldown:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    async def record_success(self, provider: str) -> None:
        self._providers.pop(provider, None)

    async def record_failure(self, provider: str) -> None:
        entry = self._providers.setdefault(provider, _Provider())
        half_open = await self.state(provider) is CircuitState.HALF_OPEN
        entry.failures += 1
        if half_open or entry.failures >= self._threshold:
            entry.opened_at = self._monotonic()
