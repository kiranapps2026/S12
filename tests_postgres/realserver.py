"""Helpers: prepare the database with a plain LOGIN role, run the app as a real subprocess."""
from __future__ import annotations

import asyncio
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import asyncpg
import httpx

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.database import Database
from contracts.principal import Principal
from tests_postgres.conftest import APP_ROLE
from tests_postgres.fake_deepseek import FakeDeepSeek
from tests_postgres.seed import reset_and_seed

ROOT = Path(__file__).resolve().parent.parent
LOGIN = "supragents_test_login"
PASSWORD = "login-pw"
OTHER_USER_SQL = (
    "INSERT INTO users (user_id, tenant_id) VALUES ('tenant-a.other', 'tenant-a')",
    "INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id)"
    " VALUES ('tenant-a.other.m', 'tenant-a', 'tenant-a.other', 'tenant-a.ws')",
    "INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id)"
    " VALUES ('tenant-a.other.c', 'tenant-a', 'tenant-a.other', 'tenant-a.ws')",
)


def login_url(database_url: str) -> str:
    return re.sub(r"//[^@]*@", f"//{LOGIN}:{PASSWORD}@", database_url, count=1)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def prepare(database_url: str, *extra_sql: str) -> dict[str, str]:
    """Reseed, create the plain login role, issue API keys. Returns {name: key}."""
    owner = await asyncpg.connect(database_url)
    try:
        await reset_and_seed(owner)
        if not await owner.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", LOGIN):
            await owner.execute(
                f"CREATE ROLE {LOGIN} LOGIN PASSWORD '{PASSWORD}' NOSUPERUSER NOBYPASSRLS IN ROLE {APP_ROLE}")
        db_name = await owner.fetchval("SELECT current_database()")
        await owner.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {LOGIN}")
        for sql in (*OTHER_USER_SQL, *extra_sql):
            await owner.execute(sql)
    finally:
        await owner.close()
    db = await Database.connect(database_url)
    try:
        auth = PostgresApiKeyAuthenticator(db)
        keys = {t: await auth.issue(Principal(t, f"{t}.ws", f"{t}.user", f"{t}.member", f"{t}.conn", ""))
                for t in ("tenant-a", "tenant-b")}
        keys["other"] = await auth.issue(Principal("tenant-a", "tenant-a.ws", "tenant-a.other",
                                                   "tenant-a.other.m", "tenant-a.other.c", ""))
    finally:
        await db.close()
    return keys


class Server:
    """The app as a separate OS process (a real restart is a real process restart)."""

    def __init__(self, database_url: str, fake_url: str, model_timeout: float = 2.0) -> None:
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._env = {**os.environ, "APP_DATABASE_URL": login_url(database_url), "APP_PORT": str(self.port),
                     "FAKE_DEEPSEEK_URL": fake_url, "MODEL_TIMEOUT": str(model_timeout),
                     "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}", "DEEPSEEK_API_KEY": ""}
        self._log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        self.proc: subprocess.Popen | None = None

    def start(self) -> "Server":
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "tests_postgres" / "server_launcher.py")],
                                     env=self._env, stdout=self._log, stderr=subprocess.STDOUT, cwd=ROOT)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early:\n{self.log()}")
            try:
                if httpx.get(f"{self.url}/ready", timeout=1).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"server did not become ready:\n{self.log()}")

    def stop(self, kill: bool = False) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill() if kill else self.proc.terminate()
            self.proc.wait(timeout=15)

    def log(self) -> str:
        self._log.flush()
        return Path(self._log.name).read_text(errors="replace")


def headers(key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}


def run(coro):
    return asyncio.run(coro)


async def _rows(database_url: str, tenant: str, sql: str, *args):
    """Run a query as the plain login role with the tenant's RLS context (what the app sees)."""
    conn = await asyncpg.connect(login_url(database_url))
    try:
        await conn.execute("SELECT set_config('app.current_tenant', $1, false)", tenant)
        return [dict(r) for r in await conn.fetch(sql, *args)]
    finally:
        await conn.close()


class Stack:
    """A prepared database + fake provider + the app running as its own process."""

    def __init__(self, database_url, keys, fake, server):
        self.database_url, self.keys, self.fake, self.server = database_url, keys, fake, server

    def client(self, timeout: float = 30.0) -> httpx.Client:
        return httpx.Client(base_url=self.server.url, timeout=timeout)

    def async_client(self, timeout: float = 60.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.server.url, timeout=timeout,
                                 limits=httpx.Limits(max_connections=300))

    def ask(self, message, who="tenant-a", client=None, **extra):
        c = client or self.client()
        return c.post("/api/v1/execute", json={"input_data": {"message": message, **extra}},
                      headers=headers(self.keys[who]))

    def reply(self, cid, approved=True, who="tenant-a", client=None):
        c = client or self.client()
        return c.post(f"/api/v1/confirmations/{cid}", json={"approved": approved}, headers=headers(self.keys[who]))

    def rows(self, tenant, sql, *args):
        return asyncio.run(_rows(self.database_url, tenant, sql, *args))

    def close(self):
        self.server.stop(kill=True)
        self.fake.__exit__(None, None, None)


def make_stack(database_url, delay=0.0, model_timeout=2.0, extra_sql=()):
    keys = asyncio.run(prepare(database_url, *extra_sql))
    fake = FakeDeepSeek(delay).__enter__()
    server = Server(database_url, fake.endpoint, model_timeout).start()
    return Stack(database_url, keys, fake, server)
