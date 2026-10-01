"""Per-step admission decision (WORKER_LIFECYCLE §11; gate C30; ruling CONF-015).

S12 uses this contract, not the frozen ``contracts.worker.AdmissionDecision`` (DATA_CONTRACTS §38 shape), because C30
maps a REJECT by ``gate_failed``, which only the §11 shape carries. A decision is never persisted: it is a ledger
event (``status``, ``gate_failed``, ``reason``).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class AdmissionStatus(StrEnum):
    ACCEPT = "ACCEPT"      # all gates passed: select a worker
    QUEUE = "QUEUE"        # capacity temporarily unavailable: retry after retry_after_ms
    DELAY = "DELAY"        # backpressure: wait retry_after_ms, then re-admit
    REJECT = "REJECT"      # denied: mapped by gate_failed (C30)
    DEGRADE = "DEGRADE"    # accepted with degraded_features disabled


RETRYABLE = frozenset({AdmissionStatus.QUEUE, AdmissionStatus.DELAY})


@dataclass(frozen=True)
class AdmissionDecision:
    status: str                                   # an AdmissionStatus value
    reason: str | None = None                     # machine-readable reason code (§10)
    detail: str | None = None                     # human-readable explanation
    retry_after_ms: int | None = None             # QUEUE / DELAY
    degraded_features: tuple[str, ...] | None = None   # DEGRADE (a tuple: the decision is immutable)
    gate_failed: str | None = None                # the gate number "1".."11" that decided


class DecisionLedger(Protocol):
    """Where S12 records its per-step decisions (C30: every admission decision is a ledger event)."""

    async def record(self, kind: str, payload: Mapping[str, Any]) -> None: ...
