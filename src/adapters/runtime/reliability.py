"""Single-node reliability components behind the guard's injected interfaces (gate §21 S3)."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager


class InProcessBulkhead:
    def __init__(self, max_concurrent: int) -> None:
        self._max = max_concurrent
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._in_use: dict[str, int] = {}

    def in_use(self, provider: str) -> int:
        return self._in_use.get(provider, 0)

    @asynccontextmanager
    async def slot(self, provider: str):
        semaphore = self._semaphores.setdefault(provider, asyncio.Semaphore(self._max))
        async with semaphore:
            self._in_use[provider] = self._in_use.get(provider, 0) + 1
            try:
                yield
            finally:
                self._in_use[provider] -= 1


class InProcessRetryStormGuard:
    def __init__(self, max_retries: int, window_s: float, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._max, self._window, self._now = max_retries, window_s, monotonic
        self._seen: dict[tuple[str, str], deque] = {}

    def allow_retry(self, provider: str, operation: str) -> bool:
        now, seen = self._now(), self._seen.setdefault((provider, operation), deque())
        while seen and now - seen[0] >= self._window:
            seen.popleft()
        if len(seen) >= self._max:
            return False
        seen.append(now)
        return True


class InProcessHealthMonitor:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, float]] = []

    def record(self, provider: str, status: str, latency_ms: float, attempt: int = 0) -> None:
        self.events.append((provider, status, latency_ms))


class InProcessBilling:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    def record(self, call_meta, kernel_op_id: str, status: str, attempt: int = 0) -> None:
        self.events.append((call_meta.provider_call_id, kernel_op_id, status))
