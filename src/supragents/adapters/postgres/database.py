"""Connection pool and tenant-scoped transactions for every PostgreSQL adapter."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

_DRIVER_PREFIXES = ("postgresql+asyncpg://", "postgres+asyncpg://")


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
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT set_config('app.current_tenant', $1, true)", tenant_id or ""
            )
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """A transaction for global (non-tenant) tables such as the registry."""
        async with self._pool.acquire() as connection, connection.transaction():
            yield connection
