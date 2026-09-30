"""Golden database harness (owner-pinned, gate §15.1).

Every golden module gets its own PostgreSQL schema in the database named by ``TEST_DATABASE_URL`` (name must end in
``_test``). The schema is created empty, the project's migrations are applied into it through
``adapters.postgres.migrate.apply_migrations``, and it is dropped when the module finishes.

Interface used by golden tests:

    schema = GoldenSchema(...)            # built by the ``db_schema`` fixture in tests_golden/conftest.py
    await schema.fetch(sql, *args)        # as the connecting role, search_path = the module schema
    await schema.fetchval(...)
    await schema.execute(sql, *args, tenant="t1")   # app.current_tenant set for forced RLS
    await schema.migrate()                # apply_migrations again, returns the names it applied
    schema.name                           # the schema name, for catalog queries
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse

import asyncpg

from adapters.postgres.database import Database, normalize_url
from adapters.postgres.migrate import apply_migrations


def golden_database_url() -> str:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        raise RuntimeError("TEST_DATABASE_URL is not set: golden tests need real PostgreSQL (gate §15.1)")
    url = normalize_url(raw)
    if not urlparse(url).path.lstrip("/").endswith("_test"):
        raise RuntimeError("refusing to use a database whose name does not end in _test")
    return url


class GoldenSchema:
    def __init__(self, url: str, name: str) -> None:
        self.url = url
        self.name = name
        self._pool: asyncpg.Pool | None = None

    async def create(self) -> None:
        admin = await asyncpg.connect(self.url)
        try:
            await admin.execute(f'CREATE SCHEMA "{self.name}"')
        finally:
            await admin.close()
        self._pool = await asyncpg.create_pool(self.url, min_size=1, max_size=4,
                                               server_settings={"search_path": self.name})

    async def drop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
        admin = await asyncpg.connect(self.url)
        try:
            await admin.execute(f'DROP SCHEMA IF EXISTS "{self.name}" CASCADE')
        finally:
            await admin.close()

    async def migrate(self) -> list[str]:
        assert self._pool is not None
        return await apply_migrations(Database(self._pool))

    async def _run(self, method: str, sql: str, *args, tenant: str | None = None):
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if tenant is not None:
                    await connection.execute("SELECT set_config('app.current_tenant', $1, true)", tenant)
                return await getattr(connection, method)(sql, *args)

    async def fetch(self, sql: str, *args, tenant: str | None = None):
        return await self._run("fetch", sql, *args, tenant=tenant)

    async def fetchval(self, sql: str, *args, tenant: str | None = None):
        return await self._run("fetchval", sql, *args, tenant=tenant)

    async def execute(self, sql: str, *args, tenant: str | None = None):
        return await self._run("execute", sql, *args, tenant=tenant)


def new_schema_name(module: str) -> str:
    return f"golden_{module.rsplit('.', 1)[-1].lower()}_{uuid.uuid4().hex[:8]}"
