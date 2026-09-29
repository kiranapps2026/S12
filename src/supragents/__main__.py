"""Command line (reads DATABASE_URL and DEEPSEEK_API_KEY from the environment or ``.env``).

    python -m supragents migrate     create or update the tables
    python -m supragents check       database reachable, migrated, registry versions present
    python -m supragents llm-check   one small DeepSeek call with the built-in request
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from supragents.adapters.postgres.database import Database
from supragents.adapters.postgres.migrate import apply_migrations, migration_files
from supragents.adapters.postgres.registry import PostgresCapabilityRegistry
from supragents.bootstrap import build_intent_model
from supragents.contracts.errors import DependencyUnavailable
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


async def _database_command(settings: Settings, command: str) -> str:
    database = await Database.connect(settings.require("database_url").database_url)
    try:
        return await (_migrate if command == "migrate" else _check)(database)
    finally:
        await database.close()


async def _llm_check(settings: Settings) -> str:
    completion = await build_intent_model(settings).complete(
        "list my contacts", ("contact.list", "contact.create"), None)
    return f"DeepSeek OK: model={completion.model} tokens={completion.total_tokens} answer={completion.text}"


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m supragents")
    parser.add_argument("command", choices=["migrate", "check", "llm-check"])
    command = parser.parse_args().command
    try:
        settings = Settings.load()
        task = _llm_check(settings) if command == "llm-check" else _database_command(settings, command)
        print(asyncio.run(task))
    except (SettingsError, RuntimeError, OSError, DependencyUnavailable) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
