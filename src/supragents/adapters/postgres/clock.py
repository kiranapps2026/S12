"""Authoritative time from the database clock (I-019)."""
from __future__ import annotations

from supragents.adapters.postgres.database import Database


class DatabaseClock:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def now(self) -> float:
        async with self._db.transaction() as connection:
            return await connection.fetchval("SELECT EXTRACT(EPOCH FROM clock_timestamp())::float8")
