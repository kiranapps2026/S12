"""The database and the code agree: every table and column the SQL in src names exists after the migrations, every
tenant-scoped table has forced row-level security, and the tables without it are exactly the documented ones."""
from __future__ import annotations

import re
from pathlib import Path

import asyncpg
import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

# Deliberately without row-level security (DATABASE.md deviations 002, 007, 011; global catalog tables).
NO_RLS = {"api_keys", "webhook_credentials", "event_schedules", "invitations", "rate_limit_counters",                          # tenant-filtered in code
          "capabilities", "bindings", "kernel_ops", "registry_versions",                 # global catalog
          "system_settings", "schema_migrations"}
NO_TENANT_COLUMN = {"rate_limit_counters", "capabilities", "bindings", "kernel_ops", "registry_versions", "system_settings", "schema_migrations"}
NOT_TABLES = {"set", "pg_roles", "pg_class", "information_schema", "__future__", "abc", "adapters", "app", "authentication", "bootstrap", "checks", "clock_timestamp",
              "collections", "contracts", "dataclasses", "datetime", "engine", "typing", "enum", "json", "os", "re",
              "uuid", "asyncio", "fastapi", "pydantic", "config", "constants", "time", "hashlib", "hmac", "base64",
              "math", "logging", "functools", "itertools", "secrets", "unicodedata", "pathlib", "urllib", "sys",
              "httpx", "asyncpg", "cryptography", "decimal", "contextlib", "inspect", "types", "zoneinfo"}


async def _schema(database_url):
    connection = await asyncpg.connect(database_url)
    try:
        columns: dict[str, set[str]] = {}
        for r in await connection.fetch("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"):
            columns.setdefault(r["table_name"], set()).add(r["column_name"])
        rls = {r["relname"]: (r["relrowsecurity"], r["relforcerowsecurity"]) for r in await connection.fetch(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace")}
    finally:
        await connection.close()
    return columns, rls


@pytest.fixture(scope="module")
def schema(database_url):
    import asyncio
    return asyncio.run(_schema(database_url))


def _sources():
    for path in sorted(SRC.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def test_every_tenant_table_forces_row_level_security_and_the_exceptions_are_exactly_the_documented_ones(schema):
    columns, rls = schema
    without = {t for t, (enabled, forced) in rls.items() if not (enabled and forced)}
    assert without == NO_RLS
    assert {t for t, cols in columns.items() if "tenant_id" not in cols} == NO_TENANT_COLUMN
    for table in columns:                                                   # tenant tables without RLS are a leak
        if table not in NO_RLS:
            assert "tenant_id" in columns[table], table


def test_every_table_the_sql_in_src_names_exists(schema):
    columns, _ = schema
    unknown = set()
    for path, text in _sources():
        for m in re.finditer(r"(?is)\b(?:FROM|JOIN|INTO|UPDATE)\s+([a-z_][a-z0-9_]*)\s*(?:\(|\s+(?:SET|WHERE|AS|[a-z]{1,2}\b|ON|JOIN|FOR|ORDER|LIMIT|GROUP|VALUES|SELECT|CROSS|LEFT|RIGHT|INNER|USING)|\s*[\"'])", text):
            name = m.group(1).lower()
            in_sql = re.search(r"(?is)(SELECT|INSERT|UPDATE|DELETE)\b", text[max(0, m.start() - 120):m.end() + 5])
            if in_sql and name not in columns and name not in NOT_TABLES and not name.startswith("_"):
                unknown.add((name, path.name))
    assert not unknown, sorted(unknown)


def test_every_column_that_insert_and_update_statements_in_src_write_exists(schema):
    columns, _ = schema
    problems = []
    clean = lambda x: re.sub(r"[\"'\s]", "", x).lower()
    for path, text in _sources():
        for m in re.finditer(r"(?is)INSERT INTO\s+([a-z_]+)\s*\(([^)]*)\)", text):
            table = m.group(1).lower()
            if table in columns:
                problems += [(table, c, path.name) for c in map(clean, m.group(2).split(",")) if c and re.fullmatch(r"[a-z_]+", c) and c not in columns[table]]
        for m in re.finditer(r"(?is)UPDATE\s+([a-z_]+)\s+SET\s+(.*?)(?:WHERE|RETURNING|\"\s*$|$)", text):
            table = m.group(1).lower()
            if table in columns:
                problems += [(table, c, path.name) for c in re.findall(r"(?:^|,)\s*([a-z_]+)\s*=", m.group(2).lower()) if c not in columns[table]]
    assert not problems, problems


def test_every_migration_is_recorded_and_the_files_have_no_gaps(database_url):
    import asyncio
    files = sorted(p.name for p in (SRC / "adapters" / "postgres" / "migrations").glob("*.sql"))
    numbers = [int(name.split("_")[0]) for name in files]
    assert numbers == list(range(1, len(numbers) + 1))

    async def applied():
        connection = await asyncpg.connect(database_url)
        try:
            return [r[0] for r in await connection.fetch("SELECT * FROM schema_migrations ORDER BY 1")]
        finally:
            await connection.close()
    recorded = asyncio.run(applied())
    assert len(recorded) == len(files)
