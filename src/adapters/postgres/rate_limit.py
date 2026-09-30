"""Fixed-window rate limiter shared by every process (the counters live in PostgreSQL, one row per bucket).

`hit` is one atomic statement: it starts a new window when the old one has ended, otherwise counts. Over the limit it
answers not-allowed with the seconds until the window resets. If the database cannot be read the caller gets
DependencyUnavailable (fail closed: no limiter, no request)."""
from __future__ import annotations

from dataclasses import dataclass

from adapters.postgres.database import Database


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: int          # seconds until the window resets (0 when allowed)


class PostgresRateLimiter:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def hit(self, bucket: str, limit: int, window_seconds: int = 60) -> RateDecision:
        if limit <= 0 or window_seconds <= 0:
            return RateDecision(False, 0, window_seconds)
        async with self._db.transaction() as c:
            row = await c.fetchrow(
                "INSERT INTO rate_limit_counters AS r (bucket, window_start, hits) VALUES ($1, now(), 1)"
                " ON CONFLICT (bucket) DO UPDATE SET"
                "   window_start = CASE WHEN r.window_start + make_interval(secs => $2) <= now() THEN now() ELSE r.window_start END,"
                "   hits = CASE WHEN r.window_start + make_interval(secs => $2) <= now() THEN 1 ELSE r.hits + 1 END"
                " RETURNING hits, GREATEST(0, CEIL(EXTRACT(EPOCH FROM (window_start + make_interval(secs => $2) - now()))))::int AS reset",
                bucket, float(window_seconds))
        hits, reset = row["hits"], row["reset"]
        if hits > limit:
            return RateDecision(False, 0, max(1, reset))
        return RateDecision(True, limit - hits, 0)
