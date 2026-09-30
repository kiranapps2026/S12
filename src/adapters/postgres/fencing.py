"""fenced_write() — the one path for every durable write of an execution (gate C5, C25).

In ONE tenant transaction: lock this execution's ``execution_ownership`` row (FOR SHARE, so a takeover's UPDATE waits
until the write commits), check that it still names the holder's ``runtime_instance_id`` and ``fence_token``, and only
then run the write. No matching row raises ``FencedOut`` and nothing is written; the Worker Runtime must stop all work
on that execution and never retry the write. The fence is per execution, never per worker or per session (C25).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import asyncpg

from adapters.postgres.database import Database
from contracts.step_execution import FencedOut

T = TypeVar("T")

_FENCE = ("SELECT 1 FROM execution_ownership"
          " WHERE tenant_id = $1 AND execution_id = $2 AND runtime_instance_id = $3 AND fencing_token = $4"
          " FOR SHARE")


@dataclass(frozen=True)
class FenceHolder:
    """Who may write for one execution: the Worker Runtime instance and the fence token of its lease."""
    tenant_id: str
    execution_id: str
    runtime_instance_id: str
    fence_token: int


async def fenced_write(database: Database, holder: FenceHolder,
                       write: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
    async with database.tenant_transaction(holder.tenant_id) as connection:
        held = await connection.fetchval(_FENCE, holder.tenant_id, holder.execution_id,
                                         holder.runtime_instance_id, holder.fence_token)
        if held is None:
            raise FencedOut(holder.execution_id)
        return await write(connection)
