"""Clock and event sink ports used by every stage and the runner."""
from __future__ import annotations

from typing import Protocol

from supragents.contracts.events import StageEvent


class Clock(Protocol):
    def now(self) -> float:
        """Authoritative Unix time (the database clock in production, I-019)."""


class EventSink(Protocol):
    async def emit(self, event: StageEvent) -> None:
        """Record one stage event in the execution ledger."""
