"""The transition log (gate C24, invariant I5): one row per state change, written in the same transaction as the
change (inside ``fenced_write``). A creation is logged with ``from_state`` None. Retries are not transitions."""
from __future__ import annotations

import asyncpg

_INSERT = ("INSERT INTO state_transitions (tenant_id, entity_type, entity_id, execution_id, from_state, to_state,"
           " reason, runtime_instance_id, fence_token) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)")


async def log_transition(connection: asyncpg.Connection, *, tenant_id: str, machine: str, entity_id: str,
                         from_state: str | None, to_state: str, reason: str, runtime_instance_id: str | None,
                         fence_token: int | None, execution_id: str | None = None) -> None:
    if not reason:
        raise ValueError("every transition carries a reason code (C24)")
    await connection.execute(_INSERT, tenant_id, machine, entity_id, execution_id, from_state, to_state, reason,
                             runtime_instance_id, fence_token)
