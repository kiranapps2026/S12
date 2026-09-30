"""Per-step admission control (gate §8 step 1, C5, C30; WORKER_LIFECYCLE §10, §11; ruling CONF-017).

``evaluate`` is a pure predicate over a snapshot of live state: gates 1–11 in order, the first failing gate decides.
It reserves nothing and holds no lease (admission is stateless), so it may be evaluated any number of times. Gate 7
(worker capacity) is a QUEUE, never a REJECT (C5); gates 9 and 11 (backpressure) are a DELAY (CONF-017). ``admit_step``
bounds QUEUE/DELAY and ends them as REJECT ``admission_exhausted``; ``reject_outcome`` maps a REJECT to the run's path
by ``gate_failed`` (C30).

Pause, activation and quota are S12 entry checks, never per-step gates (C39); worker eligibility is filtered in worker
selection (§13). The retry delays below are the phase defaults; the loop (M12) supplies ``max_attempts`` from the
settings object and moves these delays there with it (gate §21 S1).
"""
from __future__ import annotations

import asyncio
import types
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields

from contracts.execution_states import StepTerminalReason
from contracts.step_admission import RETRYABLE, AdmissionDecision, AdmissionStatus, DecisionLedger

QUEUE_RETRY_AFTER_MS = 1000
DELAY_RETRY_AFTER_MS = 500
DEGRADED_FEATURES = ("analytics", "notifications", "post_processing")   # WORKER_LIFECYCLE §11 DEGRADE_FEATURES
LEDGER_KIND = "admission_decision"

# REJECT paths (C30): the C23 revocation path, the C15 budget path, or cancel the remaining steps and consolidate.
REVOCATION = "revocation"
BUDGET = "budget"
CONSOLIDATE = "consolidate"


@dataclass(frozen=True)
class AdmissionSnapshot:
    """Live state for one step's admission. Every field is a bool; anything else is refused (fail closed)."""
    kill_switch_engaged: bool
    tenant_quota_exceeded: bool
    tenant_active: bool
    workspace_active: bool
    mode_allowed: bool
    provider_allowed: bool
    worker_capacity_available: bool
    circuit_open: bool
    db_pool_pressure: bool
    budget_available: bool
    system_overloaded: bool
    degrade: bool = False

    def __post_init__(self) -> None:
        for f in fields(self):
            if type(getattr(self, f.name)) is not bool:
                raise TypeError(f"admission snapshot {f.name} must be a bool, got {getattr(self, f.name)!r}")


_A = AdmissionStatus
# (gate, snapshot field, value that fails the gate, §10 reason, decision when it fails) — in evaluation order.
_GATES = (
    ("1", "kill_switch_engaged", True, "system_halted", _A.REJECT),
    ("2", "tenant_quota_exceeded", True, "tenant_quota_exceeded", _A.REJECT),
    ("3", "tenant_active", False, "tenant_inactive", _A.REJECT),
    ("4", "workspace_active", False, "workspace_inactive", _A.REJECT),
    ("5", "mode_allowed", False, "mode_not_allowed", _A.REJECT),
    ("6", "provider_allowed", False, "provider_blocked", _A.REJECT),
    ("7", "worker_capacity_available", False, "worker_at_capacity", _A.QUEUE),
    ("8", "circuit_open", True, "provider_circuit_open", _A.REJECT),
    ("9", "db_pool_pressure", True, "db_pool_pressure", _A.DELAY),
    ("10", "budget_available", False, "budget_exhausted", _A.REJECT),
    ("11", "system_overloaded", True, "system_overloaded", _A.DELAY),
)
_RETRY_AFTER_MS = types.MappingProxyType({_A.QUEUE: QUEUE_RETRY_AFTER_MS, _A.DELAY: DELAY_RETRY_AFTER_MS})

_R = StepTerminalReason
_REJECT_OUTCOMES = types.MappingProxyType({
    "1": (_R.KILL_SWITCH_ENGAGED, REVOCATION),
    "3": (_R.AUTHORIZATION_REVOKED, REVOCATION),
    "10": (_R.BUDGET_EXHAUSTED, BUDGET),
})
_OTHER_REJECT = (_R.ADMISSION_REJECTED, CONSOLIDATE)


def evaluate(snapshot: AdmissionSnapshot) -> AdmissionDecision:
    for gate, field, fails_when, reason, status in _GATES:
        if getattr(snapshot, field) is fails_when:
            return AdmissionDecision(status, reason=reason, detail=f"admission gate {gate} ({field})",
                                     retry_after_ms=_RETRY_AFTER_MS.get(status), gate_failed=gate)
    if snapshot.degrade:
        return AdmissionDecision(_A.DEGRADE, degraded_features=DEGRADED_FEATURES)
    return AdmissionDecision(_A.ACCEPT)


async def admit_step(snapshot_source: Callable[[], Awaitable[AdmissionSnapshot]], *, ledger: DecisionLedger,
                     max_attempts: int, sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
                     ) -> AdmissionDecision:
    """Evaluate a fresh snapshot up to ``max_attempts`` times, waiting ``retry_after_ms`` after each QUEUE/DELAY but
    the last; then REJECT ``admission_exhausted``. Every decision, the final one included, is a ledger event."""
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")
    for attempt in range(1, max_attempts + 1):
        decision = evaluate(await snapshot_source())
        await _record(ledger, decision)
        if decision.status not in RETRYABLE:
            return decision
        if attempt < max_attempts:
            await sleep((decision.retry_after_ms or 0) / 1000)
    exhausted = AdmissionDecision(_A.REJECT, reason=_R.ADMISSION_EXHAUSTED,
                                  detail=f"still {decision.status} ({decision.reason}, gate {decision.gate_failed})"
                                         f" after {max_attempts} attempts")
    await _record(ledger, exhausted)
    return exhausted


def reject_outcome(decision: AdmissionDecision) -> tuple[str, str]:
    """(step terminal reason, path) for a REJECT (C30). An exhausted QUEUE/DELAY keeps its own terminal reason
    ``admission_exhausted`` (§8 step 1, C22; DEF-005) and, like any non-revocation REJECT, the run is consolidated."""
    if decision.status != _A.REJECT:
        raise ValueError(f"only a REJECT has an outcome, got {decision.status}")
    if decision.reason == _R.ADMISSION_EXHAUSTED:
        return (_R.ADMISSION_EXHAUSTED, CONSOLIDATE)
    return _REJECT_OUTCOMES.get(decision.gate_failed, _OTHER_REJECT)


async def _record(ledger: DecisionLedger, decision: AdmissionDecision) -> None:
    await ledger.record(LEDGER_KIND, {"status": decision.status, "gate_failed": decision.gate_failed,
                                      "reason": decision.reason})
