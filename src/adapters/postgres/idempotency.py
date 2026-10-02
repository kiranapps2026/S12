"""Idempotency ledger (gate §8 step 8, C9, C17, C34)."""
from __future__ import annotations

import json

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, fenced_write
from contracts.idempotency import IdempotencyConflict, LedgerRecord
from contracts.step_execution import AdapterResult

SUCCESS, FAILURE = "success", "failure"
_LOOKUP = ("SELECT kernel_op_id, result FROM idempotency_ledger WHERE tenant_id = $1 AND idempotency_key = $2"
           " AND expires_at > now()")
_INSERT = ("INSERT INTO idempotency_ledger (idempotency_key, tenant_id, kernel_op_id, result, expires_at)"
           " VALUES ($1, $2, $3, $4::jsonb, now() + make_interval(secs => $5))"
           " ON CONFLICT (idempotency_key) DO NOTHING"
           " RETURNING idempotency_key")
_EXISTING = "SELECT kernel_op_id, result FROM idempotency_ledger WHERE tenant_id = $1 AND idempotency_key = $2"


def _kind(result: AdapterResult) -> str:
    return SUCCESS if result.status == "ok" else FAILURE


def _decode(kernel_op_id: str, raw) -> LedgerRecord:
    body = json.loads(raw) if isinstance(raw, str) else raw
    result = AdapterResult(body["status"], False, body.get("error_class"), body.get("data") or {})
    return LedgerRecord(kernel_op_id, _kind(result), result)


class PostgresIdempotencyLedger:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def lookup(self, tenant_id: str, idempotency_key: str) -> LedgerRecord | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            row = await c.fetchrow(_LOOKUP, tenant_id, idempotency_key)
        return None if row is None else _decode(row["kernel_op_id"], row["result"])

    async def store(self, holder: FenceHolder, *, idempotency_key: str, kernel_op_id: str, result: AdapterResult,
                    ttl_s: float) -> None:
        # a failure is stored as its class only: a provider's error body never reaches a persisted row (§21 S6, M18)
        data = (result.data or {}) if result.status == "ok" else {}
        body = json.dumps({"status": result.status, "error_class": result.error_class, "data": data}, sort_keys=True)

        async def write(c):
            if await c.fetchval(_INSERT, idempotency_key, holder.tenant_id, kernel_op_id, body, float(ttl_s)):
                return
            row = await c.fetchrow(_EXISTING, holder.tenant_id, idempotency_key)
            if row is None:
                raise IdempotencyConflict(idempotency_key)  # the key is held by a row this tenant cannot see (C9)
            if row["kernel_op_id"] != kernel_op_id \
                    or _decode(row["kernel_op_id"], row["result"]).kind != _kind(result):
                raise IdempotencyConflict(idempotency_key)

        await fenced_write(self._db, holder, write)
