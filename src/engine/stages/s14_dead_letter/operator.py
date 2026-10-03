"""Dead-letter operator path (CONF-049, M21).

``DeadLetterOperator`` is the only code path that lets a tenant operator inspect and act on
their own dead-letter records.  Every call first authorizes the caller through ``admin``;
a refusal writes nothing.  Records from other tenants are never returned.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from adapters.postgres.admin import AdminError
from adapters.postgres.database import Database
from adapters.postgres.dead_letters import PostgresDeadLetters
from contracts.principal import Principal


class DeadLetterOperator:
    """Operator actions on a tenant's dead-letter records."""

    def __init__(self, database: Database, *, admin, dead_letters: PostgresDeadLetters,
                 probe: Callable[[Any], Awaitable[Any]], reverify: Callable[[Any], Awaitable[str]]) -> None:
        self._db = database
        self._admin = admin
        self._dead_letters = dead_letters
        self._probe = probe
        self._reverify = reverify

    async def list_open(self, principal: Principal) -> list[dict]:
        actor = await self._admin.authorize(principal)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT dead_letter_id, execution_id, step_id, kernel_op_id, error_type, retry_mode, status"
                " FROM dead_letters"
                " WHERE tenant_id = $1 AND status = ANY($2::text[])"
                " ORDER BY created_at",
                actor.principal.tenant_id, ("pending", "retrying"))
        return [dict(row) for row in rows]

    async def resolve(self, principal: Principal, dead_letter_id: str, outcome: str) -> dict:
        actor = await self._admin.authorize(principal)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            row = await c.fetchrow(
                "SELECT tenant_id, status FROM dead_letters WHERE dead_letter_id = $2",
                actor.principal.tenant_id, dead_letter_id)
            if row is None:
                raise AdminError(404, "dead_letter_not_found")
        await self._dead_letters.resolve(actor.principal.tenant_id, dead_letter_id, outcome)
        await self._audit(actor.principal.tenant_id, "dead_letter.resolve", dead_letter_id,
                          {"outcome": outcome})
        return {"dead_letter_id": dead_letter_id, "outcome": outcome}

    async def retry(self, principal: Principal, dead_letter_id: str) -> str:
        actor = await self._admin.authorize(principal)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            row = await c.fetchrow(
                "SELECT tenant_id, retry_mode, status FROM dead_letters"
                " WHERE tenant_id = $1 AND dead_letter_id = $2",
                actor.principal.tenant_id, dead_letter_id)
            if row is None:
                raise AdminError(404, "dead_letter_not_found")
            if row["retry_mode"] == "NONE":
                raise AdminError(409, "retry_not_allowed")
        from engine.stages.s14_dead_letter.retry import retry_dead_letter
        status = await retry_dead_letter(
            actor.principal.tenant_id, dead_letter_id,
            dead_letters=self._dead_letters, probe=self._probe, reverify=self._reverify)
        await self._audit(actor.principal.tenant_id, "dead_letter.retry", dead_letter_id,
                          {"status": status})
        return status

    async def _audit(self, tenant_id: str, action: str, target_id: str, details: dict) -> None:
        async with self._db.tenant_transaction(tenant_id) as c:
            await c.execute(
                "INSERT INTO admin_audit (tenant_id, action, target_type, target_id, details)"
                " VALUES ($1, $2, 'dead_letter', $3, $4::jsonb)",
                tenant_id, action, target_id, details)
