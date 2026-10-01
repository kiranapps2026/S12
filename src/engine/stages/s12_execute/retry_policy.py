"""Retry policy for M11 (gate C9, MUTATION_SAFETY §3).

Pure functions: no imports from ``engine.*`` or ``adapters.*``.
The retry ceiling is the maximum number of attempts the step loop may make;
the retry count is ``ceiling - 1``.

  mutation      safe      idempotent    never
  R              3         3            1
  W              2         2            1
  D              2         2            1
  IRREVERSIBLE    1         1            1
"""
from __future__ import annotations

import math

# retry safety profiles
_SAFE = "safe"
_IDEMPOTENT = "idempotent"
_NEVER = "never"

_MUTATION_ORDER = ("R", "W", "D", "IRREVERSIBLE")


class _InvalidRetryPolicy(Exception):
    """Raised when mutation or retry_safety is not recognised."""


def _ceiling(mutation: str, retry_safety: str) -> int:
    if mutation == "R":
        return 3 if retry_safety != "never" else 1
    if mutation == "W":
        return 2 if retry_safety != "never" else 1
    if mutation == "D":
        return 2 if retry_safety != "never" else 1
    if mutation == "IRREVERSIBLE":
        return 1
    raise _InvalidRetryPolicy(f"unknown mutation {mutation!r}")


class InvalidRetryPolicy(Exception):
    """Raised when mutation or retry_safety is not recognised."""


def ceiling(mutation: str, retry_safety: str) -> int:
    """Maximum number of attempts for this mutation × retry_safety pair."""
    if retry_safety not in {"safe", "idempotent", "never"}:
        raise InvalidRetryPolicy(f"unknown retry_safety {retry_safety!r}")
    return _ceiling(mutation, retry_safety)


def max_attempts(mutation: str, retry_safety: str, step_max: int | None = None) -> int:
    """The effective ceiling, clamped by the step's own ``step_max_attempts`` if set."""
    effective = ceiling(mutation, retry_safety)
    if step_max is not None:
        effective = min(effective, step_max)
    return max(effective, 1)


def backoff_s(mutation: str, attempt: int, base_s: float) -> float:
    """Backoff duration in seconds for this attempt (1-indexed).

    Reads are exponential; writes and deletes are constant (fixed).
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if mutation in ("W", "D", "IRREVERSIBLE"):
        return max(base_s, 0.001)
    return max(base_s * (2 ** (attempt - 1)), 0.001)
