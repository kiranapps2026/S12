"""Command line: ``python -m supragents migrate`` or ``python -m supragents check``.

Reads DATABASE_URL from the environment. ``check`` verifies that the database is reachable,
fully migrated, and that the registry versions row exists.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from supragents.adapters.postgres.database import Database
from supragents.adapters.postgres.migrate import apply_migrations, migration_files
from supragents.adapters.postgres.registry import PostgresCapabilityRegistry
from supragents.settings import Settings, SettingsError


async def _migrate(database: Database) -> str:
    applied = await apply_migrations(database)
    return f"applied: {', '.join(applied)}" if applied else "already up to date"


async def _check(database: Database) -> str:
    async with database.transaction() as connection:
        done = {r["name"] for r in await connection.fetch("SELECT name FROM schema_migrations")}
    missing = [name for name, _ in migration_files() if name not in done]
    if missing:
        raise RuntimeError(f"not migrated: {', '.join(missing)} (run: python -m supragents migrate)")
    versions = await PostgresCapabilityRegistry(database).versions()
    return f"database OK; registry capability_version={versions.capability_version}"


async def _main(command: str) -> str:
    database = await Database.connect(Settings.from_environment().database_url)
    try:
        return await (_migrate if command == "migrate" else _check)(database)
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m supragents")
    parser.add_argument("command", choices=["migrate", "check"])
    command = parser.parse_args().command
    try:
        print(asyncio.run(_main(command)))
    except (SettingsError, RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
