"""The in-process dispatcher (gate §21 S2): the one place S12–S15 schedules a task.

Single node: ``dispatch`` starts ``run(tenant_id, execution_id)`` on the running event loop and returns its handle. A
fleet dispatcher (a queue) replaces this class later behind the same method; no other S12–S15 module creates tasks.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class InProcessDispatcher:
    def __init__(self, run: Callable[[str, str], Awaitable[Any]]) -> None:
        self._run = run

    def dispatch(self, tenant_id: str, execution_id: str) -> asyncio.Task:
        return asyncio.get_running_loop().create_task(self._run(tenant_id, execution_id))
