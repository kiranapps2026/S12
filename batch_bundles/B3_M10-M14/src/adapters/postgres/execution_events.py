"""The execution ledger writer (FINAL_ARCHITECTURE §40; append-only; every row a fenced write, gate C5).

``insert_event`` writes one row on a caller's connection, so an operation that must record its event in its own
transaction (consolidation, a dead letter, a refund) does so atomically; the recorder is the fenced stand-alone path.
"""
from __future__ import annotations

import json
import uuid

import asyncpg

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, fenced_write
from contracts import codec

_INSERT = ("INSERT INTO execution_events (event_id, tenant_id, execution_id, trace_id, event_type, step_id,"
           " attempt_id, provider_call_id, runtime_instance_id, fence_token, payload)"
           " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)")


async def insert_event(c: asyncpg.Connection, *, tenant_id: str, execution_id: str | None, trace_id: str, kind: str,
                       payload: dict, step_id: str | None = None, runtime_instance_id: str | None = None,
                       fence_token: int | None = None) -> None:
    body = dict(payload)
    await c.execute(_INSERT, str(uuid.uuid4()), tenant_id, execution_id, trace_id, str(kind),
                    body.get("step_id", step_id), body.get("attempt_id"), body.get("provider_call_id"),
                    runtime_instance_id, fence_token, json.dumps(codec.encode(body), sort_keys=True))


class EventRecorder:
    def __init__(self, database: Database, holder: FenceHolder, trace_id: str, step_id: str | None) -> None:
        self._db, self._holder, self._trace_id, self._step_id = database, holder, trace_id, step_id

    async def record(self, kind: str, payload) -> None:
        h = self._holder

        async def write(c):
            await insert_event(c, tenant_id=h.tenant_id, execution_id=h.execution_id, trace_id=self._trace_id,
                               kind=kind, payload=dict(payload), step_id=self._step_id,
                               runtime_instance_id=h.runtime_instance_id, fence_token=h.fence_token)
        await fenced_write(self._db, h, write)


class PostgresExecutionEvents:
    def __init__(self, database: Database) -> None:
        self._db = database

    def recorder(self, holder: FenceHolder, *, trace_id: str, step_id: str | None = None) -> EventRecorder:
        return EventRecorder(self._db, holder, trace_id, step_id)

    async def layer_verdicts(self, tenant_id: str, step_id: str) -> dict[str, str]:
        """The latest persisted verdict per verification layer of a step (``verification_layer`` events, CONF-036)."""
        async with self._db.tenant_transaction(tenant_id) as c:
            rows = await c.fetch("SELECT payload FROM execution_events WHERE tenant_id = $1 AND step_id = $2"
                                 " AND event_type = 'verification_layer' ORDER BY seq", tenant_id, step_id)
        latest: dict[str, str] = {}
        for r in rows:
            body = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            latest[body["layer"]] = body["verdict"]
        return latest
