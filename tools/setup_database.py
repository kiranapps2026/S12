"""Create the application database and role, apply every migration, and grant the role its limited rights.

    python tools/setup_database.py [--db suprpg] [--role supragents_app] [--reset-password] [--write-env]

Needs an administrator connection (a PostgreSQL superuser such as `postgres`) in ADMIN_DATABASE_URL, in the environment or
in .env, e.g. postgresql://postgres:<password>@localhost:5432/postgres . The application role's password is read from
APP_DB_PASSWORD or asked for without echo; it is never printed or stored. Safe to run again: existing databases and
roles are kept, migrations already applied are skipped, grants are re-applied.

The role is NOSUPERUSER NOBYPASSRLS, so the row-level security of the schema is really enforced for the application.
It may SELECT, INSERT and UPDATE (never DELETE, never UPDATE the append-only event log).
Whenever the password is given in this run, the script logs in as the role to prove it works. With --write-env it also
sets the DATABASE_URL line in .env (password URL-encoded; the password itself is never printed).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys
from urllib.parse import quote, urlparse, urlunparse

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from adapters.postgres.database import Database, normalize_url  # noqa: E402
from adapters.postgres.migrate import apply_migrations  # noqa: E402

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def env_value(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            key, _, value = line.strip().removeprefix("export ").partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip("\"'")
    return None


def with_database(url: str, database: str) -> str:
    parts = urlparse(normalize_url(url))
    return urlunparse(parts._replace(path=f"/{database}"))


def write_env_line(line: str) -> None:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    lines = open(path, encoding="utf-8-sig").read().splitlines() if os.path.exists(path) else []
    kept = [l for l in lines if l.strip().removeprefix("export ").partition("=")[0].strip() != "DATABASE_URL"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(kept + [line]) + "\n")


async def main(database: str, role: str, reset_password: bool, write_env: bool) -> int:
    admin_url = env_value("ADMIN_DATABASE_URL")
    if not admin_url:
        sys.exit("ADMIN_DATABASE_URL is not set (environment or .env): a superuser URL such as postgresql://postgres:<password>@localhost:5432/postgres")
    for name in (database, role):
        if not IDENTIFIER.match(name):
            sys.exit(f"'{name}' is not a plain lowercase identifier")

    password = None
    maintenance = await asyncpg.connect(with_database(admin_url, "postgres"))
    try:
        if not await maintenance.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database):
            await maintenance.execute(f'CREATE DATABASE "{database}"')
            print(f"created database {database}")
        exists = await maintenance.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if not exists or reset_password:
            password = os.environ.get("APP_DB_PASSWORD") or getpass.getpass(f"password for role {role} (not shown): ")
            if not password:
                sys.exit("an empty password is not allowed")
            literal = await maintenance.fetchval("SELECT quote_literal($1)", password)
            verb = "ALTER" if exists else "CREATE"
            await maintenance.execute(f'{verb} ROLE "{role}" WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {literal}')
            print(f"{'updated' if exists else 'created'} role {role}")
        else:
            print(f"role {role} already exists (kept; use --reset-password to change it)")
    finally:
        await maintenance.close()

    target_url = with_database(admin_url, database)
    owner = await Database.connect(target_url)
    try:
        applied = await apply_migrations(owner)
    finally:
        await owner.close()
    print(f"migrations applied now: {len(applied)}" + (f" ({applied[0]} … {applied[-1]})" if applied else " (already up to date)"))

    connection = await asyncpg.connect(target_url)
    try:
        await connection.execute(
            f'GRANT CONNECT ON DATABASE "{database}" TO "{role}";'
            f'GRANT USAGE ON SCHEMA public TO "{role}";'
            f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}";'
            f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO "{role}";'
            f'REVOKE UPDATE ON pipeline_events FROM "{role}";'
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO "{role}";'
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO "{role}"')
        tables = await connection.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    finally:
        await connection.close()
    print(f"database {database}: {tables} tables, rights granted to {role}")
    if password is not None:
        parts = urlparse(normalize_url(admin_url))
        host = f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
        try:
            check = await asyncpg.connect(f"postgresql://{quote(role, safe='')}:{quote(password, safe='')}@{host}/{database}")
            await check.close()
            print(f"login as {role} works")
        except Exception as error:  # noqa: BLE001 - report, never echo the URL
            sys.exit(f"login as {role} with that password FAILED: {type(error).__name__}")
        line = f"DATABASE_URL=postgresql+asyncpg://{quote(role, safe='')}:{quote(password, safe='')}@{host}/{database}"
        if write_env:
            write_env_line(line)
            print("DATABASE_URL in .env updated")
        else:
            print("run again with --write-env to store it in .env, or set DATABASE_URL yourself")
    else:
        print(f"role {role} was kept and no password was given, so its login was not tested; use --reset-password to set one")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="suprpg")
    parser.add_argument("--role", default="supragents_app")
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument("--write-env", action="store_true", help="store DATABASE_URL (password URL-encoded) in .env")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.db, args.role, args.reset_password, args.write_env)))
