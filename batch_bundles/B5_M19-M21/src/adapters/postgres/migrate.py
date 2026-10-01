"""Apply the numbered SQL files in ``migrations/`` once each, in order."""
from __future__ import annotations

from importlib import resources

from adapters.postgres.database import Database

_PACKAGE = "adapters.postgres.migrations"


def migration_files() -> list[tuple[str, str]]:
    files = sorted((f for f in resources.files(_PACKAGE).iterdir() if f.name.endswith(".sql")),
                   key=lambda f: f.name)
    return [(f.name, f.read_text(encoding="utf-8")) for f in files]


async def apply_migrations(database: Database) -> list[str]:
    """Return the names of the migrations applied by this call."""
    applied: list[str] = []
    async with database.transaction() as connection:
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        await connection.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
        done = {row["name"] for row in await connection.fetch("SELECT name FROM schema_migrations")}
        for name, sql in migration_files():
            if name not in done:
                await connection.execute(sql)
                await connection.execute("INSERT INTO schema_migrations (name) VALUES ($1)", name)
                applied.append(name)
    return applied
