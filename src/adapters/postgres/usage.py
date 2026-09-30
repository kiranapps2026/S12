"""Language-model usage metering: one `llm_usage` row per model call, attributed to the tenant, user and request the call
served. The attribution travels in a per-request scope (a context variable held by the meter object, not module state), so
no stage or contract changes: the API binds the scope, `MeteredIntentModel` reads it after each call."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from adapters.postgres.database import Database
from contracts.intent_model import IntentCompletion, IntentModel

logger = logging.getLogger(__name__)


class UsageMeter:
    def __init__(self, database: Database) -> None:
        self._db = database
        self._scope: ContextVar[tuple[str, str, str] | None] = ContextVar("usage_scope", default=None)

    @contextmanager
    def scope(self, tenant_id: str, user_id: str, request_id: str) -> Iterator[None]:
        token = self._scope.set((tenant_id, user_id, request_id))
        try:
            yield
        finally:
            self._scope.reset(token)

    async def record(self, completion: IntentCompletion) -> None:
        scope = self._scope.get()
        if scope is None:                      # a model call outside any request scope cannot be billed to anyone
            logger.error("LLM call without a usage scope: %d tokens not attributed", completion.total_tokens)
            return
        tenant_id, user_id, request_id = scope
        async with self._db.tenant_transaction(tenant_id) as c:
            await c.execute("INSERT INTO llm_usage (tenant_id, user_id, request_id, model, total_tokens) VALUES ($1,$2,$3,$4,$5)",
                            tenant_id, user_id, request_id, completion.model, completion.total_tokens)


class MeteredIntentModel:
    """Wraps the real model: the call is made first, then its tokens are recorded (a failed call costs nothing)."""

    def __init__(self, inner: IntentModel, meter: UsageMeter) -> None:
        self._inner, self._meter = inner, meter

    async def complete(self, text: str, intents: tuple[str, ...], feedback: str | None) -> IntentCompletion:
        completion = await self._inner.complete(text, intents, feedback)
        await self._meter.record(completion)
        return completion


async def usage_summary(database: Database, tenant_id: str, days: int = 30) -> dict:
    async with database.tenant_transaction(tenant_id) as c:
        total = await c.fetchrow("SELECT count(*) AS calls, COALESCE(sum(total_tokens), 0)::bigint AS tokens FROM llm_usage"
                                 " WHERE tenant_id = $1 AND called_at >= now() - make_interval(days => $2)", tenant_id, days)
        by_day = await c.fetch("SELECT date_trunc('day', called_at)::date AS day, model, count(*) AS calls,"
                               " sum(total_tokens)::bigint AS tokens FROM llm_usage WHERE tenant_id = $1"
                               " AND called_at >= now() - make_interval(days => $2) GROUP BY 1, 2 ORDER BY 1 DESC, 2",
                               tenant_id, days)
        by_user = await c.fetch("SELECT user_id, count(*) AS calls, sum(total_tokens)::bigint AS tokens FROM llm_usage"
                                " WHERE tenant_id = $1 AND called_at >= now() - make_interval(days => $2)"
                                " GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT 50", tenant_id, days)
    return {"days": days, "calls": total["calls"], "total_tokens": total["tokens"],
            "by_day": [dict(r) for r in by_day], "by_user": [dict(r) for r in by_user]}
