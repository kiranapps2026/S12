"""Command line. Reads DATABASE_URL and DEEPSEEK_API_KEY from the environment or ``.env``.

    python -m supragents migrate          create or update the tables
    python -m supragents check            database reachable, migrated, registry versions present
    python -m supragents llm-check        one small DeepSeek call with the built-in request
    python -m supragents serve            start the HTTP API (default 127.0.0.1:8000)
    python -m supragents create-api-key --tenant T --workspace W --user U --membership M
                                        --connection C --scope S    (prints the key once)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from supragents.adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from supragents.adapters.postgres.database import Database
from supragents.adapters.postgres.migrate import apply_migrations, migration_files
from supragents.adapters.postgres.registry import PostgresCapabilityRegistry
from supragents.bootstrap import build_intent_model
from supragents.contracts.errors import DependencyUnavailable
from supragents.ports.authentication import Principal
from supragents.server import serve
from supragents.settings import Settings, SettingsError

_KEY_FIELDS = ("tenant", "workspace", "user", "membership", "connection", "scope")


async def _migrate(database: Database, args: argparse.Namespace) -> str:
    applied = await apply_migrations(database)
    return f"applied: {', '.join(applied)}" if applied else "already up to date"


async def _check(database: Database, args: argparse.Namespace) -> str:
    async with database.transaction() as connection:
        done = {r["name"] for r in await connection.fetch("SELECT name FROM schema_migrations")}
    missing = [name for name, _ in migration_files() if name not in done]
    if missing:
        raise RuntimeError(f"not migrated: {', '.join(missing)} (run: python -m supragents migrate)")
    versions = await PostgresCapabilityRegistry(database).versions()
    return f"database OK; registry capability_version={versions.capability_version}"


async def _create_api_key(database: Database, args: argparse.Namespace) -> str:
    key = await PostgresApiKeyAuthenticator(database).issue(Principal(
        tenant_id=args.tenant, workspace_id=args.workspace, user_id=args.user,
        membership_id=args.membership, connection_id=args.connection, resource_scope=args.scope))
    return f"API key (shown once, store it safely): {key}"


async def _with_database(settings: Settings, action, args: argparse.Namespace) -> str:
    database = await Database.connect(settings.require("database_url").database_url)
    try:
        return await action(database, args)
    finally:
        await database.close()


async def _llm_check(settings: Settings) -> str:
    completion = await build_intent_model(settings).complete(
        "list my contacts", ("contact.list", "contact.create"), None)
    return f"DeepSeek OK: model={completion.model} tokens={completion.total_tokens} answer={completion.text}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m supragents")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("migrate", "check", "llm-check"):
        commands.add_parser(name)
    server = commands.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    key = commands.add_parser("create-api-key")
    for name in _KEY_FIELDS:
        key.add_argument(f"--{name}", required=True)
    return parser


async def _dispatch(args: argparse.Namespace, settings: Settings) -> str | None:
    database_actions = {"migrate": _migrate, "check": _check, "create-api-key": _create_api_key}
    if args.command in database_actions:
        return await _with_database(settings, database_actions[args.command], args)
    if args.command == "llm-check":
        return await _llm_check(settings)
    await serve(settings, args.host, args.port)
    return None


def main() -> int:
    args = _parser().parse_args()
    try:
        output = asyncio.run(_dispatch(args, Settings.load()))
    except (SettingsError, RuntimeError, OSError, DependencyUnavailable) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
