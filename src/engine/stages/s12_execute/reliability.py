"""Re-exports for S12 engine tests and consumers (gate C4).

The canonical implementations live in ``adapters.runtime.reliability`` so that S8 can
import them without a dependency from ``engine`` down to ``adapters``.  This module
provides the ``engine.stages.s12_execute.reliability`` path the golden tests pin.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from contracts.adapter_interface import (
    AdapterResult,
    BudgetStateError,
    CallMeta,
    ErrorClass,
    GuardedCall,
    Observation,
    ProbeOutcome,
)
from contracts.execution_states import CircuitBreakerState, ReservationState
from contracts.step_execution import StepAdapter

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ budget tracker ----------------------------------------------------------

class BudgetTracker:
    """Read-only precondition: the reservation for this call is LOCKED (C31).

    ``reserver`` is either:
      - a callable ``(tenant_id, reservation_id) -> awaitable row`` (legacy; tests),
      - an object with an async ``.reservation(tenant_id, reservation_id)`` method
        (the PostgresBudgetReserver / BudgetReserver protocol).
    """

    def __init__(self, reserver: Callable[[str, str], Awaitable[object | None]] | object) -> None:
        self._reserver = reserver

    async def _lookup(self, tenant_id: str, reservation_id: str) -> object | None:
        reserver = self._reserver
        if hasattr(reserver, "reservation"):
            return await reserver.reservation(tenant_id, reservation_id)
        if hasattr(reserver, "status"):
            status = await reserver.status(tenant_id, reservation_id)
            if status is None:
                return None
            return type("Row", (), {"status": status, "step_id": None})()
        return await reserver(tenant_id, reservation_id)

    async def check(self, call: GuardedCall) -> None:
        """Raise BudgetStateError when the reservation is absent or not LOCKED."""
        row = await self._lookup(call.context.tenant_id, call.reservation_id)
        if row is None:
            raise BudgetStateError(f"reservation {call.reservation_id} not found")
        # Row-like objects from the DB are dict-access (asyncpg Record); tests build attribute objects.
        status = row["status"] if hasattr(row, "__getitem__") else getattr(row, "status", None)
        step_id = row["step_id"] if hasattr(row, "__getitem__") else getattr(row, "step_id", None)
        if step_id != call.step_id:
            raise BudgetStateError(f"reservation {call.reservation_id} is not for step {call.step_id}")
        if status != ReservationState.LOCKED:
            raise BudgetStateError(
                f"reservation {call.reservation_id} status={status} is not locked"
            )


# ------------------------------------------------------------------ timeout manager ---------------------------------------------------------

class TimeoutManager:
    """Wraps an awaitable with an asyncio timeout (C32).

    ``timeout`` on the call wins over the step default.  ``0`` or ``None`` means no timeout.
    A ``TimeoutError`` from asyncio is surfaced as-is so the guard can normalise it.
    """

    async def run(self, awaitable: Awaitable, timeout_s: float) -> object:
        deadline = max(timeout_s, 0.0)
        if deadline == 0:
            return await awaitable
        try:
            async with asyncio.timeout(deadline):
                return await awaitable
        except TimeoutError:
            raise


# ------------------------------------------------------------------ health / billing --------------------------------------------------------

@dataclass
class HealthEvent:
    provider_id: str
    status: str                  # "ok" | "error" | "timeout" | "circuit_open" | ...
    latency_ms: float
    attempt: int


@dataclass
class BillingEvent:
    provider_id: str
    kernel_op_id: str
    status: str                  # "ok" | "error" | ...
    attempt: int
    call_meta: CallMeta | None = None


class InProcessHealthMonitor:
    """In-memory health event sink (S8 reads this after the guard returns)."""
    def __init__(self) -> None:
        self.events: list[HealthEvent] = []

    def record(self, provider_id: str, status: str, latency_ms: float, attempt: int) -> None:
        self.events.append(HealthEvent(provider_id=provider_id, status=status, latency_ms=latency_ms, attempt=attempt))


class InProcessBilling:
    """In-memory billing event sink."""
    def __init__(self) -> None:
        self.events: list[BillingEvent] = []

    def record(self, call_meta: CallMeta, kernel_op_id: str, status: str, attempt: int) -> None:
        self.events.append(BillingEvent(
            provider_id="", kernel_op_id=kernel_op_id, status=status, attempt=attempt, call_meta=call_meta
        ))


# ------------------------------------------------------------------ bulkhead ---------------------------------------------------------------

class InProcessBulkhead:
    """Per-provider concurrency limiter (RELIABILITY §3).

    ``slot(provider)`` returns an async context manager.  When the limit is reached
    the next caller waits until a slot frees.
    """

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._max = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._in_use: dict[str, int] = {}

    def slot(self, provider: str):
        class _Slot:
            async def __aenter__(_self):
                await self._sem.acquire()
                self._in_use[provider] = self._in_use.get(provider, 0) + 1

            async def __aexit__(_self, *exc):
                self._in_use[provider] = max(0, self._in_use.get(provider, 1) - 1)
                self._sem.release()

        return _Slot()

    def in_use(self, provider: str) -> int:
        return self._in_use.get(provider, 0)


# ------------------------------------------------------------------ retry storm guard -------------------------------------------------------

class InProcessRetryStormGuard:
    """Bounded retries per (provider, operation) within a sliding window (RELIABILITY §6)."""

    def __init__(self, max_retries: int, window_s: float, monotonic: Callable[[], float] = time.monotonic) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._max = max_retries
        self._window = window_s
        self._clock = monotonic
        self._hits: dict[tuple[str, str], list[float]] = {}

    def allow_retry(self, provider: str, operation: str) -> bool:
        key = (provider, operation)
        now = self._clock()
        window_start = now - self._window
        self._hits[key] = [t for t in self._hits.get(key, []) if t > window_start]
        if len(self._hits[key]) >= self._max:
            return False
        self._hits[key].append(now)
        return True


# ------------------------------------------------------------------ reliability guard -------------------------------------------------------

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
        breaker: Callable[[str], str] | None = None,
        budget: Callable[[GuardedCall], Awaitable[None]] | None = None,
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

        # 1. bulkhead
        slot = self._bulkhead.slot(provider)
        async with slot:
            # 2. circuit breaker allow()
            if self._breaker is not None:
                if not self._breaker.allow(provider):
                    self._breaker.record_ignored(provider)
                    # No health/billing for a refused call: adapter never ran.
                    return AdapterResult("error", False, ErrorClass.CIRCUIT_OPEN.value)

            # 3. budget
            if self._budget is not None:
                try:
                    if hasattr(self._budget, "check"):
                        await self._budget.check(call)
                    else:
                        await self._budget(call)
                except BudgetStateError:
                    # Release the breaker trial slot if we're in HALF_OPEN, then re-raise.
                    if self._breaker is not None:
                        self._breaker.record_ignored(provider)
                    raise

            # 4. retry storm (attempt > 1 only)
            if attempt > 1 and self._retry_storm is not None:
                if not self._retry_storm.allow_retry(provider, call.kernel_op_id):
                    self._record_outcome(provider, call, attempt, started, "retry_storm", ErrorClass.RETRY_STORM.value, False)
                    return AdapterResult("error", False, ErrorClass.RETRY_STORM.value)

            # 5. call with timeout
            try:
                inner = self._adapter.call(
                    call.kernel_op_id, call.params, call.binding, call.context, call_meta=call.call_meta
                )
                raw = await self._timeouts.run(inner, call.timeout_s)
            except TimeoutError:
                self._record_failure(provider, call, attempt, started, "timeout", ErrorClass.TIMEOUT.value, False)
                return AdapterResult("timeout", False, ErrorClass.TIMEOUT.value)
            except Exception as exc:  # noqa: BLE001 — C32 adapter defect
                self._record_failure(provider, call, attempt, started, "adapter_defect", ErrorClass.ADAPTER_DEFECT.value, False)
                logger.error("adapter defect", extra={"kernel_op_id": call.kernel_op_id, "attempt_id": call.call_meta.attempt_id, "exception_type": type(exc).__name__})
                return AdapterResult("error", False, ErrorClass.ADAPTER_DEFECT.value)

            # 6. normalise result
            try:
                status = raw.status
                error_class = raw.error_class
                retryable = raw.retryable
                data = raw.data
            except AttributeError:
                self._record_failure(provider, call, attempt, started, "adapter_defect", ErrorClass.ADAPTER_DEFECT.value, False)
                return AdapterResult("error", False, ErrorClass.ADAPTER_DEFECT.value)

            if status == "ok":
                self._record_success(provider, call, attempt, started)
                return AdapterResult("ok", False)

            # Known non-error statuses from adapters: "timeout". Everything else is adapter_defect.
            if status == "timeout":
                self._record_failure(provider, call, attempt, started, "timeout", ErrorClass.TIMEOUT.value, False)
                return AdapterResult("timeout", False, ErrorClass.TIMEOUT.value)

            # Unknown/foreign status: normalize to adapter_defect.
            if status != "error":
                self._record_failure(provider, call, attempt, started, "error", ErrorClass.ADAPTER_DEFECT.value, False)
                return AdapterResult("error", False, ErrorClass.ADAPTER_DEFECT.value)

            if error_class not in {e.value for e in ErrorClass}:
                error_class = ErrorClass.ADAPTER_DEFECT.value

            retryable = error_class in {
                ErrorClass.NOT_DISPATCHED.value,
                ErrorClass.RATE_LIMITED.value,
                ErrorClass.SERVER_ERROR.value,
                ErrorClass.TIMEOUT.value,
                ErrorClass.RETRY_STORM.value,
            }
            self._record_failure(provider, call, attempt, started, status, error_class, retryable)
            return AdapterResult("error", retryable, error_class)

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

    async def observe(self, kernel_op_id: str, observation_spec: dict, binding: FrozenBindingIdentity,
                      context: ExecutionContext) -> Observation:
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
            if error_class == ErrorClass.CLIENT_ERROR.value:
                # Client errors never open the breaker (C23): release trial slot but stay in current state.
                self._breaker.record_ignored(provider)
            else:
                self._breaker.record_failure(provider)
        self._health.record(provider, status, (time.monotonic() - started) * 1000, attempt)
        self._billing.record(call.call_meta, call.kernel_op_id, status, attempt)

    def _record_outcome(self, provider: str, call: GuardedCall, attempt: int, started: float,
                        status: str, error_class: str, retryable: bool) -> None:
        if self._breaker is not None:
            self._breaker.record_ignored(provider)
        self._health.record(provider, status, (time.monotonic() - started) * 1000, attempt)
        self._billing.record(call.call_meta, call.kernel_op_id, status, attempt)
