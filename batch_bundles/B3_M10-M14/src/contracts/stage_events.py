"""Stage events: one audit record per stage outcome of an S0–S11 run."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StageEvent:
    """What happened at one stage. Deliberately no payload: no user text or model output is
    ever written to the event log."""
    stage: str                    # S0, S0.1, S1 … S11
    status: str                   # normal | clarify | deny | error
    reason: str | None
    duration_ms: float
    trace_id: str | None          # None only if S0 stopped before a context existed
    request_id: str | None
    tenant_id: str | None         # None only if S0 stopped before identity was known


class EventSink(Protocol):
    async def emit(self, event: StageEvent) -> None:
        """Record one event durably. Raise if it cannot be recorded (the run then stops)."""
