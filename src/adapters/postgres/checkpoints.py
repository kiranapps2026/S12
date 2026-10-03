"""Checkpoint persistence (gate §8, CONF-044, D-4).

A checkpoint row is a hint: recovery never reads it.  The database is the truth.
"""
from __future__ import annotations

import uuid

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, fenced_write

_INSERT = ("INSERT INTO checkpoints (checkpoint_id, tenant_id, execution_id, sequence, completed_steps,"
           " pending_steps, current_step)"
           " VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)")


class PostgresCheckpoints:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def write(self, holder: FenceHolder, completed_steps: list[str], pending_steps: list[str],
                    current_step: str | None = None) -> None:
        async def _write(c):
            seq = await c.fetchval(
                "SELECT coalesce(max(sequence), -1) + 1 FROM checkpoints WHERE tenant_id = $1 AND execution_id = $2",
                holder.tenant_id, holder.execution_id)
            await c.execute(_INSERT, str(uuid.uuid4()), holder.tenant_id, holder.execution_id, seq,
                            __import__("json").dumps(sorted(completed_steps)),
                            __import__("json").dumps(sorted(pending_steps)),
                            current_step)
        await fenced_write(self._db, holder, _write)
