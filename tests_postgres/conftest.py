"""PostgreSQL test database for the adapter tests (not part of the owner certification).

Run:  TEST_DATABASE_URL=postgresql+asyncpg://user:pw@host:5432/<name>_test pytest tests_postgres
Without TEST_DATABASE_URL nothing here is collected. The database name must end in
``_test``: the schema is dropped and rebuilt once per session. Adapters run as the
non-superuser role ``supragents_test_app`` so row-level security is really enforced.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg
import pytest

from adapters.postgres.database import Database, normalize_url
from adapters.postgres.migrate import apply_migrations
from tests_postgres.seed import reset_and_seed

APP_ROLE = "supragents_test_app"


def pytest_ignore_collect(collection_path, config):
    return not os.environ.get("TEST_DATABASE_URL") and collection_path.name.startswith("test_")


def _url() -> str:
    url = normalize_url(os.environ["TEST_DATABASE_URL"])
    if not urlparse(url).path.lstrip("/").endswith("_test"):
        pytest.exit("refusing to reset a database whose name does not end in _test", returncode=2)
    return url


async def _rebuild(url: str) -> None:
    connection = await asyncpg.connect(url)
    try:
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        if not await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", APP_ROLE):
            await connection.execute(f"CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS")
    finally:
        await connection.close()
    owner = await Database.connect(url)
    try:
        await apply_migrations(owner)
    finally:
        await owner.close()
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(
            f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};"
            f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _url()
    asyncio.run(_rebuild(url))
    return url


@pytest.fixture
def pg(database_url):
    """``pg(body, *setup_sql)``: reseed, run setup SQL as owner, then ``await body(database)``
    with a Database whose connections use the non-superuser app role."""
    def run(body, *setup_sql: str):
        async def scenario():
            owner = await asyncpg.connect(database_url)
            try:
                await reset_and_seed(owner)
                for statement in setup_sql:
                    await owner.execute(statement)
            finally:
                await owner.close()
            pool = await asyncpg.create_pool(
                database_url, min_size=1, max_size=4,
                init=lambda connection: connection.execute(f"SET ROLE {APP_ROLE}"))
            database = Database(pool)
            try:
                return await body(database)
            finally:
                await database.close()
        return asyncio.run(scenario())
    return run
