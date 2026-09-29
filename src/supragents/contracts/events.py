"""Ledger event emitted by the runner after every stage.

Identity fields are None only when S0 stopped before it could build a context.
"""
from __future__ import annotations

from dataclasses import dataclass

from supragents.contracts.vocabulary import StageStatus


@dataclass(frozen=True)
class StageEvent:
    trace_id: str | None
    request_id: str | None
    tenant_id: str | None
    stage: str
    status: StageStatus
    reason: str | None
    duration_ms: float
