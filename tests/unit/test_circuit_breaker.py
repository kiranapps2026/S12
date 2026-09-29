"""In-process circuit breaker (package B): CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN."""
from __future__ import annotations

import asyncio

from supragents.adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from supragents.contracts.vocabulary import CircuitState


class _Ticks:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _breaker():
    ticks = _Ticks()
    return InProcessCircuitBreaker(failure_threshold=2, cooldown_seconds=10, monotonic=ticks), ticks


def _state(breaker, provider="crm"):
    return asyncio.run(breaker.state(provider))


def _fail(breaker, times=1, provider="crm"):
    for _ in range(times):
        asyncio.run(breaker.record_failure(provider))


def test_opens_after_threshold_and_only_for_that_provider():
    breaker, _ = _breaker()
    _fail(breaker)
    assert _state(breaker) is CircuitState.CLOSED
    _fail(breaker)
    assert _state(breaker) is CircuitState.OPEN
    assert _state(breaker, "mail") is CircuitState.CLOSED


def test_half_open_after_cooldown_then_success_closes():
    breaker, ticks = _breaker()
    _fail(breaker, 2)
    ticks.value = 10
    assert _state(breaker) is CircuitState.HALF_OPEN
    asyncio.run(breaker.record_success("crm"))
    assert _state(breaker) is CircuitState.CLOSED


def test_failure_while_half_open_reopens():
    breaker, ticks = _breaker()
    _fail(breaker, 2)
    ticks.value = 10
    _fail(breaker)
    assert _state(breaker) is CircuitState.OPEN
