"""Per-provider circuit breaker for a single node (gate C1: no shared state yet).

CLOSED -> OPEN after ``failure_threshold`` consecutive failures; OPEN -> HALF_OPEN once
``cooldown_seconds`` have passed; a success closes it, a failure while HALF_OPEN reopens it.
S8 reads ``state`` (synchronous, R-C); S12 reports outcomes with record_success/record_failure.

M10 additions: ``allow(provider)`` and ``record_ignored(provider)`` so the guard can
admit HALF_OPEN trials one at a time (C37) and release the slot when a trial is refused.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from contracts.execution_states import CircuitBreakerState
from engine.stages.s8_safety_gate.dependencies import CircuitBreaker


class InProcessCircuitBreaker(CircuitBreaker):
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}
        self._trial_in_progress: dict[str, bool] = {}

    def _state(self, provider_id: str) -> CircuitBreakerState:
        opened = self._opened_at.get(provider_id)
        if opened is None:
            return CircuitBreakerState.CLOSED
        if self._monotonic() - opened >= self._cooldown:
            return CircuitBreakerState.HALF_OPEN
        return CircuitBreakerState.OPEN

    def state(self, provider_id: str) -> str:
        """The S8 protocol returns the member name: 'CLOSED', 'OPEN' or 'HALF_OPEN'."""
        with self._lock:
            return self._state(provider_id).name

    def allow(self, provider_id: str) -> bool:
        """Admit a call (C37).

        CLOSED: always True.
        OPEN: always False.
        HALF_OPEN: True only for the first trial; subsequent concurrent calls are refused.
        """
        with self._lock:
            st = self._state(provider_id)
            if st is CircuitBreakerState.CLOSED:
                return True
            if st is CircuitBreakerState.OPEN:
                return False
            # HALF_OPEN
            if self._trial_in_progress.get(provider_id, False):
                return False
            self._trial_in_progress[provider_id] = True
            return True

    def record_success(self, provider_id: str) -> None:
        with self._lock:
            self._failures.pop(provider_id, None)
            self._opened_at.pop(provider_id, None)
            self._trial_in_progress.pop(provider_id, None)

    def record_failure(self, provider_id: str) -> None:
        with self._lock:
            half_open = self._state(provider_id) is CircuitBreakerState.HALF_OPEN
            self._failures[provider_id] = self._failures.get(provider_id, 0) + 1
            if half_open or self._failures[provider_id] >= self._threshold:
                self._opened_at[provider_id] = self._monotonic()
            self._trial_in_progress.pop(provider_id, None)

    def record_ignored(self, provider_id: str) -> None:
        """A trial was refused without calling the adapter (C37).

        In HALF_OPEN this releases the trial slot so the next call is admitted.
        """
        with self._lock:
            self._trial_in_progress.pop(provider_id, None)
