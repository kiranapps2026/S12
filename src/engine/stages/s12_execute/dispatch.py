"""Dispatcher (M12, gate C9, C35): the only module in S12 that creates asyncio tasks.

The in-process dispatcher wraps the step-loop body so every step execution goes
through a single, instrumentable entry point.  No other S12-to-S15 module calls
``create_task``, ``ensure_future`` or ``TaskGroup`` directly.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable


class InProcessDispatcher:
    """Wraps a body callable and dispatches calls as asyncio tasks (M12)."""

    def __init__(self, body: Callable[[str, str], Awaitable[object]]) -> None:
        self._body = body

    async def dispatch(self, tenant_id: str, execution_id: str) -> object:
        """Run the body for (tenant_id, execution_id) and return its result."""
        return await self._body(tenant_id, execution_id)
