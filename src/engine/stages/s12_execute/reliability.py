"""Reliability guard around one adapter attempt (gate C4, C31, C32, C37; RELIABILITY §8 acquisition order)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import Any

from contracts.adapter_interface import (
    RETRYABLE,
    BudgetStateError,
    ErrorClass,
    GuardedCall,
    Observation,
    ProbeOutcome,
)
from contracts.execution_states import ReservationState
from contracts.step_execution import AdapterResult

logger = logging.getLogger(__name__)
_KNOWN = frozenset(ErrorClass)


class BudgetTracker:
    def __init__(self, lookup) -> None:
        self._lookup = lookup

    async def check(self, call: GuardedCall) -> None:
        row = await self._lookup.reservation(call.context.tenant_id, call.reservation_id)
        if row is None or row.step_id != call.step_id or row.status != ReservationState.LOCKED:
            raise BudgetStateError(f"step {call.step_id} has no LOCKED reservation {call.reservation_id}")


class InverseBudget:
    """The budget layer for an explicit rollback's inverse calls (D2, ruling CONF-038): an inverse of a completed step
    has no reservation in this phase, so a call passes only when it has none and is an inverse (its key ends
    ``:inverse``); any other call is refused like a missing reservation."""
    async def check(self, call: GuardedCall) -> None:
        if call.reservation_id is not None or not call.call_meta.idempotency_key.endswith(":inverse"):
            raise BudgetStateError(f"step {call.step_id}: only an inverse call may run without a reservation")


class TimeoutManager:
    async def run(self, awaitable: Awaitable, timeout_s: float):
        async with asyncio.timeout(timeout_s):
            return await awaitable


def _defect() -> AdapterResult:
    return AdapterResult("error", False, ErrorClass.ADAPTER_DEFECT)


def _normalise(result: Any) -> AdapterResult:
    if not isinstance(result, AdapterResult):
        return _defect()
    if result.status == "ok":
        return AdapterResult("ok", False, None, result.data)
    if result.status == "timeout":
        return AdapterResult("timeout", False, ErrorClass.TIMEOUT)
    if result.status == "error" and result.error_class in _KNOWN:
        cls = ErrorClass(result.error_class)
        return AdapterResult("error", cls in RETRYABLE, cls, result.data)
    return _defect()


class InProcessBulkhead:
    def __init__(self, max_concurrent: int) -> None:
        self._max = max_concurrent
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._in_use: dict[str, int] = {}

    def in_use(self, provider: str) -> int:
        return self._in_use.get(provider, 0)

    @asynccontextmanager
    async def slot(self, provider: str):
        semaphore = self._semaphores.setdefault(provider, asyncio.Semaphore(self._max))
        async with semaphore:
            self._in_use[provider] = self._in_use.get(provider, 0) + 1
            try:
                yield
            finally:
                self._in_use[provider] -= 1


class InProcessRetryStormGuard:
    def __init__(self, max_retries: int, window_s: float, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._max, self._window, self._now = max_retries, window_s, monotonic
        self._seen: dict[tuple[str, str], deque] = {}

    def allow_retry(self, provider: str, operation: str) -> bool:
        now, seen = self._now(), self._seen.setdefault((provider, operation), deque())
        while seen and now - seen[0] >= self._window:
            seen.popleft()
        if len(seen) >= self._max:
            return False
        seen.append(now)
        return True


class InProcessHealthMonitor:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, float]] = []

    def record(self, provider: str, status: str, latency_ms: float, attempt: int = 0) -> None:
        self.events.append((provider, status, latency_ms))


class InProcessBilling:
    def __init__(self) -> None:
        self.records: list = []

    def record(self, meta, kernel_op_id: str, status: str, attempt: int = 0) -> None:
        self.records.append((meta.attempt_id if meta else None, kernel_op_id, status, attempt))


class ReliabilityGuard:
    """Orchestrates the 5 guard components around a single adapter call (C4, C37).

    Acquisition order (RELIABILITY §8):
      1. Bulkhead slot
      2. CircuitBreaker.allow()
      3. BudgetTracker.check()
      4. RetryStormGuard.allow_retry() (attempt > 1 only)
      5. TimeoutManager.run(adapter.call)

    Recording order (C4):
      - breaker.record_success / record_failure / record_ignored
      - health.record
      - billing.record

    The bulkhead slot is released on every exit path (success, failure, refusal, exception).
    Probing and observing take their own bulkhead slot and probe_timeout_s; they never
    consult the breaker, budget or retry-storm guard (C37).
    """

    def __init__(
        self,
        adapter: StepAdapter,
        *,
        bulkhead: InProcessBulkhead,
        breaker: InProcessCircuitBreaker | None = None,
        budget: BudgetTracker | None = None,
        retry_storm: InProcessRetryStormGuard | None = None,
        timeouts: TimeoutManager,
        health: InProcessHealthMonitor,
        billing: InProcessBilling,
        probe_timeout_s: float = 0.5,
    ) -> None:
        self._adapter = adapter
        self._bulkhead = bulkhead
        self._breaker = breaker
        self._budget = budget
        self._retry_storm = retry_storm
        self._timeouts = timeouts
        self._health = health
        self._billing = billing
        self._probe_timeout_s = probe_timeout_s

    async def call(self, call: GuardedCall) -> AdapterResult:
        provider = call.binding.provider
        attempt = call.attempt
        started = time.monotonic()

        async with self._bulkhead.slot(provider):
            if self._breaker is not None and not self._breaker.allow(provider):
                self._breaker.record_ignored(provider)
                return AdapterResult("error", False, ErrorClass.CIRCUIT_OPEN)

            if self._budget is not None:
                try:
                    await self._budget.check(call)
                except BudgetStateError:
                    if self._breaker is not None:
                        self._breaker.record_ignored(provider)
                    raise

            if attempt > 1 and self._retry_storm is not None:
                if not self._retry_storm.allow_retry(provider, call.kernel_op_id):
                    self._record_outcome(provider, call, attempt, started, "retry_storm", ErrorClass.RETRY_STORM.value, False)
                    return AdapterResult("error", False, ErrorClass.RETRY_STORM.value)

            try:
                inner = self._adapter.call(
                    call.kernel_op_id, call.params, call.binding, call.context, call_meta=call.call_meta
                )
                raw = await self._timeouts.run(inner, call.timeout_s)
            except TimeoutError:
                self._record_failure(provider, call, attempt, started, "timeout", ErrorClass.TIMEOUT.value, False)
                return AdapterResult("timeout", False, ErrorClass.TIMEOUT.value)
            except BudgetStateError:
                if self._breaker is not None:
                    self._breaker.record_ignored(provider)
                raise
            except Exception as exc:  # noqa: BLE001 — C32 adapter defect
                self._record_failure(provider, call, attempt, started, "adapter_defect", ErrorClass.ADAPTER_DEFECT.value, False)
                logger.error("adapter defect", extra={"kernel_op_id": call.kernel_op_id, "attempt_id": call.call_meta.attempt_id, "exception_type": type(exc).__name__})
                return AdapterResult("error", False, ErrorClass.ADAPTER_DEFECT.value)

            result = _normalise(raw)
            if result.status == "ok":
                self._record_success(provider, call, attempt, started)
            elif result.error_class == ErrorClass.CLIENT_ERROR.value:
                if self._breaker is not None:
                    self._breaker.record_ignored(provider)
                self._health.record(provider, result.status, (time.monotonic() - started) * 1000, attempt)
                self._billing.record(call.call_meta, call.kernel_op_id, result.status, attempt)
            else:
                self._record_failure(provider, call, attempt, started, result.status,
                                     result.error_class or ErrorClass.ADAPTER_DEFECT.value, result.retryable)
            return result

    async def probe(self, call: GuardedCall) -> ProbeOutcome:
        """Probe the provider without side effects (C37)."""
        provider = call.binding.provider
        slot = self._bulkhead.slot(provider)
        async with slot:
            try:
                inner = self._adapter.probe(
                    call.kernel_op_id, call.params, call.binding, call.context, call_meta=call.call_meta
                )
                raw = await self._timeouts.run(inner, self._probe_timeout_s)
            except TimeoutError:
                return ProbeOutcome.INCONCLUSIVE
            except Exception:  # noqa: BLE001 — probe never raises
                return ProbeOutcome.INCONCLUSIVE

            # StrEnum members are also str; pass them through as-is so StrEnum equality works.
            if isinstance(raw, ProbeOutcome):
                return raw
            if isinstance(raw, str):
                return raw
            return ProbeOutcome.INCONCLUSIVE

    async def observe(self, kernel_op_id: str, observation_spec: dict, binding, context) -> Observation:
        """Observe provider state without side effects (C37)."""
        provider = binding.provider
        slot = self._bulkhead.slot(provider)
        async with slot:
            try:
                inner = self._adapter.observe(kernel_op_id, observation_spec, binding, context)
                raw = await self._timeouts.run(inner, self._probe_timeout_s)
            except TimeoutError:
                return Observation(attempt=0, observed_at=time.time(), error="observe_timeout")
            except Exception:  # noqa: BLE001
                return Observation(attempt=0, observed_at=time.time(), error="observe_error")

            try:
                return Observation(
                    attempt=getattr(raw, "attempt", 0),
                    observed_at=getattr(raw, "observed_at", time.time()),
                    provider_response_code=getattr(raw, "provider_response_code", None),
                    observed_state=getattr(raw, "observed_state", None),
                    matches_expected=getattr(raw, "matches_expected", None),
                    error=getattr(raw, "error", None),
                )
            except Exception:  # noqa: BLE001
                return Observation(attempt=0, observed_at=time.time(), error="observe_error")

    # ------------------------------------------------------------------ helpers ----------------------------------------------------------

    def _record_success(self, provider: str, call: GuardedCall, attempt: int, started: float) -> None:
        if self._breaker is not None:
            self._breaker.record_success(provider)
        self._health.record(provider, "ok", (time.monotonic() - started) * 1000, attempt)
        self._billing.record(call.call_meta, call.kernel_op_id, "ok", attempt)

    def _record_failure(self, provider: str, call: GuardedCall, attempt: int, started: float,
                        status: str, error_class: str, retryable: bool) -> None:
        if self._breaker is not None:
            self._breaker.record_failure(provider)
        self._health.record(provider, status, (time.monotonic() - started) * 1000, attempt)
        self._billing.record(call.call_meta, call.kernel_op_id, status, attempt)

    def _record_outcome(self, provider: str, call: GuardedCall, attempt: int, started: float,
                        status: str, error_class: str, retryable: bool) -> None:
        self._health.record(provider, status, (time.monotonic() - started) * 1000, attempt)
        self._billing.record(call.call_meta, call.kernel_op_id, status, attempt)
