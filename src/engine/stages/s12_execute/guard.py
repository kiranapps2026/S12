"""Reliability guard around ONE adapter call (gate C4, C31, C32).

Components by name: BudgetTracker (a read-only precondition: the step's reservation must be LOCKED),
CircuitBreaker (OPEN refuses without calling), TimeoutManager (asyncio timeout, never text matching).
An exception escaping the adapter becomes `adapter_defect` (not retryable). Provider failures
(error, timeout) count against the breaker; client errors do not (C37).
"""
from __future__ import annotations

import asyncio
import logging

from contracts.execution_states import CircuitBreakerState, ReservationState
from contracts.step_execution import AdapterResult, StepAdapter, StepCall

logger = logging.getLogger(__name__)

CLIENT_ERRORS = frozenset({"client_error", "unauthorized", "forbidden", "not_found", "unprocessable"})


class BreakerRecorder:
    """What the guard needs of the breaker: read the state, report outcomes (InProcessCircuitBreaker)."""
    def state(self, provider_id: str) -> str: ...
    def record_success(self, provider_id: str) -> None: ...
    def record_failure(self, provider_id: str) -> None: ...


class ReliabilityGuard:
    def __init__(self, adapter: StepAdapter, breaker: BreakerRecorder | None) -> None:
        self._adapter, self._breaker = adapter, breaker

    async def execute(self, call: StepCall, *, reservation_status: str | None) -> AdapterResult:
        # BudgetTracker layer (C31): read-only. No LOCKED reservation, no adapter call.
        if reservation_status != ReservationState.LOCKED.value:
            return AdapterResult("error", False, "budget_not_locked")
        provider = call.binding.provider
        if self._breaker is None:
            return AdapterResult("error", False, "circuit_unavailable")
        try:
            if self._breaker.state(provider) == CircuitBreakerState.OPEN.name:
                return AdapterResult("error", False, "circuit_open")
        except Exception:  # noqa: BLE001 — fail closed
            return AdapterResult("error", False, "circuit_unavailable")
        try:
            async with asyncio.timeout(max(1, call.step.timeout)):
                result = await self._adapter.call(call)
        except TimeoutError:
            self._safe(self._breaker.record_failure, provider)
            return AdapterResult("timeout", False, "timeout")
        except Exception:  # noqa: BLE001 — C32: an adapter defect, never propagated
            logger.exception("adapter raised for step %s", call.step.id)
            self._safe(self._breaker.record_failure, provider)
            return AdapterResult("error", False, "adapter_defect")
        if not isinstance(result, AdapterResult) or result.status not in ("ok", "error", "timeout"):
            self._safe(self._breaker.record_failure, provider)
            return AdapterResult("error", False, "adapter_defect")
        if result.status == "ok":
            self._safe(self._breaker.record_success, provider)
        elif result.status == "timeout" or result.error_class not in CLIENT_ERRORS:
            self._safe(self._breaker.record_failure, provider)
        return result

    @staticmethod
    def _safe(fn, provider: str) -> None:
        try:
            fn(provider)
        except Exception:  # noqa: BLE001 — bookkeeping must not change an outcome
            logger.exception("circuit breaker bookkeeping failed")
