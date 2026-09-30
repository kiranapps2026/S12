"""Golden database harness (owner-pinned, gate §15.1).

Every golden module gets its own PostgreSQL schema in the database named by ``TEST_DATABASE_URL`` (environment, else the
repository ``.env``; name must end in
``_test``). The schema is created empty, the project's migrations are applied into it through
``adapters.postgres.migrate.apply_migrations``, and it is dropped when the module finishes.

Interface used by golden tests:

    schema = GoldenSchema(...)            # built by the ``db_schema`` fixture in tests_golden/conftest.py
    await schema.fetch(sql, *args)        # as the connecting role, search_path = the module schema
    await schema.fetchval(...)
    await schema.execute(sql, *args, tenant="t1")   # app.current_tenant set for forced RLS
    await schema.migrate()                # apply_migrations again, returns the names it applied
    schema.database()                     # Database for code under test: role golden_app, RLS enforced
    schema.name                           # the schema name, for catalog queries
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

from adapters.postgres.database import Database, normalize_url
from adapters.postgres.migrate import apply_migrations


def _from_dotenv() -> str | None:
    """TEST_DATABASE_URL from the repository .env (only that key is read; nothing is printed)."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            key, _, value = line.strip().removeprefix("export ").partition("=")
            if key.strip() == "TEST_DATABASE_URL" and value.strip():
                return value.strip().strip("\"'")
    return None


def golden_database_url() -> str:
    raw = os.environ.get("TEST_DATABASE_URL") or _from_dotenv()
    if not raw:
        raise RuntimeError("TEST_DATABASE_URL is not set: golden tests need real PostgreSQL (gate §15.1)")
    url = normalize_url(raw)
    if not urlparse(url).path.lstrip("/").endswith("_test"):
        raise RuntimeError("refusing to use a database whose name does not end in _test")
    return url


APP_ROLE = "golden_app"


class GoldenSchema:
    """``fetch``/``execute`` run as the connecting role, which must be a superuser (test setup, catalog checks, and the
    invariant checker, which must see every tenant). ``database()`` — the code under test — runs as the non-superuser
    role ``golden_app``, so row-level security is always enforced on it (as in tests_postgres)."""

    def __init__(self, url: str, name: str) -> None:
        self.url = url
        self.name = name
        self._pool: asyncpg.Pool | None = None
        self._app_pool: asyncpg.Pool | None = None
        self._superuser = False

    async def create(self) -> None:
        admin = await asyncpg.connect(self.url)
        try:
            self._superuser = bool(await admin.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
            if not self._superuser:
                raise RuntimeError(
                    "golden tests need TEST_DATABASE_URL to connect as a superuser: the invariant checker must see every"
                    " tenant's rows, and code under test is then run as the non-superuser role golden_app")
            await admin.execute(f'CREATE SCHEMA "{self.name}"')
            if not await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", APP_ROLE):
                await admin.execute(f"CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS")
        finally:
            await admin.close()
        self._pool = await asyncpg.create_pool(self.url, min_size=1, max_size=4,
                                               server_settings={"search_path": self.name})
        app_settings = {"search_path": self.name, "role": APP_ROLE}
        self._app_pool = await asyncpg.create_pool(self.url, min_size=1, max_size=8, server_settings=app_settings)

    async def grant(self) -> None:
        await self.execute(f'GRANT USAGE ON SCHEMA "{self.name}" TO {APP_ROLE};'
                           f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{self.name}" TO {APP_ROLE};'
                           f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{self.name}" TO {APP_ROLE}')

    async def drop(self) -> None:
        for pool in (self._app_pool, self._pool):
            if pool is not None:
                await pool.close()
        admin = await asyncpg.connect(self.url)
        try:
            await admin.execute(f'DROP SCHEMA IF EXISTS "{self.name}" CASCADE')
        finally:
            await admin.close()

    def database(self) -> Database:
        """The project's Database wrapper for code under test (non-superuser role, RLS enforced)."""
        assert self._app_pool is not None
        return Database(self._app_pool)

    async def migrate(self) -> list[str]:
        assert self._pool is not None
        applied = await apply_migrations(Database(self._pool))
        await self.grant()
        return applied

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
