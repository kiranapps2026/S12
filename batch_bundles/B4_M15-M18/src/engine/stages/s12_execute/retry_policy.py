"""Retry ceilings (MUTATION_SAFETY §3) and backoff."""
from __future__ import annotations

import types

_CEILING = types.MappingProxyType({"R": 3, "W": 2, "D": 2, "IRREVERSIBLE": 1})


def ceiling(mutation: str, retry_safety: str) -> int:
    if retry_safety == "never":
        return 1
    return _CEILING.get(mutation, 1)


def max_attempts(mutation: str, retry_safety: str, step_max: int | None = None) -> int:
    top = ceiling(mutation, retry_safety)
    return top if step_max is None else max(1, min(top, step_max))


def backoff_s(mutation: str, attempt: int, base_s: float) -> float:
    return base_s if mutation == "D" else base_s * 2 ** (attempt - 1)
