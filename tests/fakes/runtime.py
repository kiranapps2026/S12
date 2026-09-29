"""Clock and event-sink doubles."""
from __future__ import annotations

from supragents.contracts.events import StageEvent

START_TIME = 1_800_000_000.0


class FakeClock:
    def __init__(self, now: float = START_TIME) -> None:
        self.current = now

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class RecordingEvents:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[StageEvent] = []
        self.fail = fail

    async def emit(self, event: StageEvent) -> None:
        if self.fail:
            raise ConnectionError("ledger down")
        self.events.append(event)

    @property
    def stages(self) -> list[str]:
        return [event.stage for event in self.events]
