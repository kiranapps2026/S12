"""Database-backed pre-flight source (CONF-027 as amended, M21).

``PostgresPreflight`` is an awaitable callable::

    problem = await PostgresPreflight(database)(step, binding)

Returns ``None`` when the step's inputs are valid, or a ``str`` describing the problem.

The database has no kernel input schema; this adapter currently always returns ``None`` (valid).
The input-schema check is deferred to a later milestone.
"""
from __future__ import annotations


class PostgresPreflight:
    """Database-backed pre-flight checks."""

    def __init__(self, database) -> None:
        self._db = database

    async def __call__(self, step, binding) -> str | None:
        return None
