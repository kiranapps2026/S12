"""The API lifespan opens the database pool, wires the real adapters, and closes the pool."""
from __future__ import annotations

import asyncio
import re

import asyncpg
import httpx
import pytest

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.database import Database
from app import StartupError, create_app
from contracts.principal import Principal
from tests_postgres.conftest import APP_ROLE
from tests_postgres.seed import reset_and_seed
from tests_postgres.test_end_to_end import EchoIntentModel

LOGIN = "supragents_test_login"
PASSWORD = "login-pw"


def _login_url(database_url: str) -> str:
    """The same database, as a plain (RLS-enforced) LOGIN role."""
    return re.sub(r"//[^@]*@", f"//{LOGIN}:{PASSWORD}@", database_url, count=1)


async def _prepare(database_url: str) -> str:
    owner = await asyncpg.connect(database_url)
    try:
        await reset_and_seed(owner)
        if not await owner.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", LOGIN):
            await owner.execute(
                f"CREATE ROLE {LOGIN} LOGIN PASSWORD '{PASSWORD}' NOSUPERUSER NOBYPASSRLS IN ROLE {APP_ROLE}")
        await owner.execute(f"GRANT CONNECT ON DATABASE {(await owner.fetchval('SELECT current_database()'))} TO {LOGIN}")
    finally:
        await owner.close()
    return _login_url(database_url)


async def _issue_key(database_url: str) -> str:
    db = await Database.connect(database_url)
    try:
        return await PostgresApiKeyAuthenticator(db).issue(
            Principal("tenant-a", "tenant-a.ws", "tenant-a.user", "tenant-a.member", "tenant-a.conn", ""))
    finally:
        await db.close()


def _post(client, key, message):
    return client.post("/api/v1/execute", json={"input_data": {"message": message}},
                       headers={"authorization": f"Bearer {key}"})


def test_lifespan_wires_the_pool_and_serves_a_real_run(database_url):
    async def scenario():
        url = await _prepare(database_url)
        key = await _issue_key(database_url)
        app = create_app(database_url=url, intent_model=EchoIntentModel())
        assert app.state.pipeline is None and app.state.database is None      # nothing before startup
        async with app.router.lifespan_context(app):
            database = app.state.database
            assert app.state.pipeline is not None and app.state.authenticator is not None
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                ready = await client.get("/ready")
                run = await _post(client, key, "contact.list")
                bad = await _post(client, "sk_supra_nope", "contact.list")
        after = (app.state.pipeline, app.state.authenticator, app.state.database)
        with pytest.raises(Exception):
            async with database.transaction():
                pass                                                          # pool is closed
        return ready, run, bad, after
    ready, run, bad, after = asyncio.run(scenario())
    assert (ready.status_code, ready.json()) == (200, {"status": "ready"})
    assert run.status_code == 200 and (run.json()["status"], run.json()["final_stage"]) == ("NORMAL", "S11")
    assert bad.status_code == 401
    assert after == (None, None, None)


def test_without_a_model_the_pipeline_is_not_wired_but_auth_is(database_url, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    async def scenario():
        url = await _prepare(database_url)
        key = await _issue_key(database_url)
        app = create_app(database_url=url)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                return (await client.get("/ready"), await _post(client, key, "contact.list"),
                        await _post(client, "sk_supra_nope", "contact.list"), await client.get("/health"))
    ready, run, bad, health = asyncio.run(scenario())
    assert ready.status_code == 503 and ready.json()["problems"] == ["pipeline_unavailable"]
    assert (run.status_code, run.json()["detail"]) == (503, "pipeline_unavailable")
    assert bad.status_code == 401
    assert health.status_code == 200


def test_refuses_to_start_as_a_superuser(database_url):
    async def scenario():
        await _prepare(database_url)
        app = create_app(database_url=database_url, intent_model=EchoIntentModel())   # superuser URL
        async with app.router.lifespan_context(app):
            pass
    with pytest.raises(StartupError, match="BYPASSRLS"):
        asyncio.run(scenario())


def test_refuses_to_start_on_an_unmigrated_database(database_url):
    async def scenario():
        url = await _prepare(database_url)
        admin = await asyncpg.connect(database_url)
        try:
            await admin.execute("DROP DATABASE IF EXISTS suprpg_empty_test")
            await admin.execute("CREATE DATABASE suprpg_empty_test")
            await admin.execute(f"GRANT ALL ON DATABASE suprpg_empty_test TO {LOGIN}")
        finally:
            await admin.close()
        app = create_app(database_url=url.rsplit("/", 1)[0] + "/suprpg_empty_test",
                         intent_model=EchoIntentModel())
        async with app.router.lifespan_context(app):
            pass
    with pytest.raises(StartupError, match="not migrated"):
        asyncio.run(scenario())


def test_unreachable_database_fails_startup_without_leaking_the_password(database_url):
    async def scenario():
        url = _login_url(database_url).rsplit(":", 1)[0] + ":1/x"      # nothing listens on port 1
        app = create_app(database_url=url, intent_model=EchoIntentModel())
        async with app.router.lifespan_context(app):
            pass
    with pytest.raises(StartupError) as raised:
        asyncio.run(scenario())
    assert PASSWORD not in str(raised.value)


def test_injected_and_database_modes_are_exclusive():
    with pytest.raises(ValueError):
        create_app(pipeline=object(), database_url="postgresql://x/y_test")
