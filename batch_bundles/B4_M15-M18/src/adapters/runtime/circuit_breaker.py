"""Per-provider circuit breaker for a single node (gate C1: no shared state yet; C37).

CLOSED -> OPEN after ``failure_threshold`` consecutive failures; OPEN -> HALF_OPEN once
``cooldown_seconds`` have passed; a success closes it, a failure while HALF_OPEN reopens it.
S8 reads ``state`` (synchronous, R-C). S12's guard asks ``allow`` before a call (HALF_OPEN admits one trial at a
time) and reports the outcome with record_success / record_failure, or record_ignored (a client error, or a trial
that never reached the adapter), which releases the trial without counting.
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
        self._threshold, self._cooldown, self._monotonic = failure_threshold, cooldown_seconds, monotonic
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}
        self._trial: set[str] = set()

    def _state(self, provider_id: str) -> CircuitBreakerState:
        opened = self._opened_at.get(provider_id)
        if opened is None:
            return CircuitBreakerState.CLOSED
        if self._monotonic() - opened >= self._cooldown:
            return CircuitBreakerState.HALF_OPEN
        return CircuitBreakerState.OPEN

    def state(self, provider_id: str) -> str:
        with self._lock:
            return self._state(provider_id).name

    def allow(self, provider_id: str) -> bool:
        with self._lock:
            state = self._state(provider_id)
            if state is CircuitBreakerState.CLOSED:
                return True
            if state is CircuitBreakerState.HALF_OPEN and provider_id not in self._trial:
                self._trial.add(provider_id)
                return True
            return False

    def record_success(self, provider_id: str) -> None:
        with self._lock:
            self._trial.discard(provider_id)
            self._failures.pop(provider_id, None)
            self._opened_at.pop(provider_id, None)

    def record_failure(self, provider_id: str) -> None:
        with self._lock:
            half_open = self._state(provider_id) is CircuitBreakerState.HALF_OPEN
            self._trial.discard(provider_id)
            self._failures[provider_id] = self._failures.get(provider_id, 0) + 1
            if half_open or self._failures[provider_id] >= self._threshold:
                self._opened_at[provider_id] = self._monotonic()

    def record_ignored(self, provider_id: str) -> None:
        with self._lock:
            self._trial.discard(provider_id)
