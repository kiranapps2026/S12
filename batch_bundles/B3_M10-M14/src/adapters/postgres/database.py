"""Connection pool, tenant-scoped transactions, and the sync bridge for S8 providers."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import TypeVar

import asyncpg

from contracts.errors import DependencyUnavailable

T = TypeVar("T")

_DRIVER_PREFIXES = ("postgresql+asyncpg://", "postgres+asyncpg://")
SYNC_CALL_TIMEOUT_SECONDS = 10.0


def normalize_url(url: str) -> str:
    """Accept SQLAlchemy-style URLs (``postgresql+asyncpg://``) as plain libpq URLs."""
    for prefix in _DRIVER_PREFIXES:
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> Database:
        return cls(await asyncpg.create_pool(normalize_url(url), min_size=1, max_size=10))

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def tenant_transaction(self, tenant_id: str | None) -> AsyncIterator[asyncpg.Connection]:
        """A transaction in which row-level security sees only ``tenant_id``'s rows."""
        async with _fail_closed(), self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT set_config('app.current_tenant', $1, true)", tenant_id or "")
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """A transaction for global (non-tenant) tables such as the registry and api_keys."""
        async with _fail_closed(), self._pool.acquire() as connection, connection.transaction():
            yield connection


@asynccontextmanager
async def _fail_closed() -> AsyncIterator[None]:
    """Driver/connection failures become DependencyUnavailable (callers deny; never guess).
    Constraint violations (programming errors) keep their own type."""
    try:
        yield
    except (asyncpg.InterfaceError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError,
            asyncpg.QueryCanceledError, OSError, TimeoutError) as exc:
        raise DependencyUnavailable(f"database unavailable: {type(exc).__name__}") from exc


class LoopBridge:
    """Lets synchronous code running in a worker thread (S8 checks, R-C) call coroutines
    on the event loop that owns the connection pool. Must not be used from the loop's own
    thread: that would deadlock, so it fails loudly instead."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @classmethod
    def current(cls) -> LoopBridge:
        return cls(asyncio.get_running_loop())

    def call(self, awaitable: Awaitable[T]) -> T:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()
            raise RuntimeError("LoopBridge.call from the event loop thread would deadlock")
        return asyncio.run_coroutine_threadsafe(_as_coro(awaitable), self._loop).result(
            timeout=SYNC_CALL_TIMEOUT_SECONDS)


async def _as_coro(awaitable: Awaitable[T]) -> T:
    return await awaitable
