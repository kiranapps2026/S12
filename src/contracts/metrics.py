"""The metrics hook (gate S21 S5): counters and timings for S12-S15; a no-op in this phase."""
from __future__ import annotations

from typing import Protocol


class MetricsHook(Protocol):
    def increment(self, name: str, **labels: str) -> None: ...

    def timing(self, name: str, value: float, **labels: str) -> None: ...


class NoMetrics:
    def increment(self, name: str, **labels: str) -> None:
        return None

    def timing(self, name: str, value: float, **labels: str) -> None:
        return None


STEP_OUTCOME = "step_outcome"
PROBE = "probe"
DEAD_LETTER = "dead_letter"
FENCED_OUT = "fenced_out"
STEP_DURATION_MS = "step_duration_ms"
