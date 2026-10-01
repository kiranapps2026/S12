"""Reliability guard around one adapter attempt (gate C4, C31, C32, C37; RELIABILITY §8 acquisition order)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
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


class ReliabilityGuard:
    def __init__(self, adapter, *, bulkhead, breaker, budget, retry_storm, timeouts, health, billing,
                 probe_timeout_s: float) -> None:
        self._adapter, self._bulkhead, self._breaker, self._budget = adapter, bulkhead, breaker, budget
        self._storm, self._timeouts, self._health, self._billing = retry_storm, timeouts, health, billing
        self._probe_timeout_s = probe_timeout_s

    async def call(self, call: GuardedCall) -> AdapterResult:
        provider = call.binding.provider
        async with self._bulkhead.slot(provider):
            if not self._breaker.allow(provider):
                return AdapterResult("error", False, ErrorClass.CIRCUIT_OPEN)
            try:
                await self._budget.check(call)
                if call.attempt > 1 and not self._storm.allow_retry(provider, call.kernel_op_id):
                    self._breaker.record_ignored(provider)
                    return AdapterResult("error", False, ErrorClass.RETRY_STORM)
            except BaseException:
                self._breaker.record_ignored(provider)
                raise
            started = time.monotonic()
            try:
                raw = await self._timeouts.run(
                    self._adapter.call(call.kernel_op_id, call.params, call.binding, call.context,
                                       call_meta=call.call_meta), call.timeout_s)
                result = _normalise(raw)
            except TimeoutError:
                result = AdapterResult("timeout", False, ErrorClass.TIMEOUT)
            except Exception as exc:  # noqa: BLE001 — C32
                logger.error("adapter defect", extra={"kernel_op_id": call.kernel_op_id,
                                                      "attempt_id": call.call_meta.attempt_id,
                                                      "exception_type": type(exc).__name__})
                result = _defect()
            except BaseException:
                self._breaker.record_ignored(provider)      # cancelled mid-call: never leave a trial held
                raise
            latency_ms = (time.monotonic() - started) * 1000
            if result.status == "ok":
                self._breaker.record_success(provider)
            elif result.error_class == ErrorClass.CLIENT_ERROR:
                self._breaker.record_ignored(provider)
            else:
                self._breaker.record_failure(provider)
            self._health.record(provider, result.status, latency_ms)
            self._billing.record(call.call_meta, call.kernel_op_id, result.status)
            return result

    async def probe(self, call: GuardedCall) -> ProbeOutcome:
        try:
            async with asyncio.timeout(self._probe_timeout_s), self._bulkhead.slot(call.binding.provider):
                outcome = await self._adapter.probe(call.kernel_op_id, call.params, call.binding, call.context,
                                                    call_meta=call.call_meta)
            return ProbeOutcome(outcome)
        except Exception:  # noqa: BLE001 — a probe never raises
            return ProbeOutcome.INCONCLUSIVE

    async def observe(self, kernel_op_id: str, spec: dict, binding, context) -> Observation:
        try:
            async with asyncio.timeout(self._probe_timeout_s), self._bulkhead.slot(binding.provider):
                seen = await self._adapter.observe(kernel_op_id, spec, binding, context)
            if isinstance(seen, Observation):
                return seen
        except Exception:  # noqa: BLE001 — an observation never raises
            pass
        return Observation(1, time.time(), 0, None, None, "observation_failed")
