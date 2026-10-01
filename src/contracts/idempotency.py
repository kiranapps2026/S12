"""Idempotency key helpers (gate C9, MUTATION_SAFETY §5).

Pure functions: no database, no network, no mutable module state.
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts.step_execution import AdapterResult


class IdempotencyConflict(Exception):
    """Raised when a second result is stored for a key that already has a different result."""


@dataclass(frozen=True)
class LedgerRecord:
    kernel_op_id: str
    kind: str                 # "success" | "failure"
    result: AdapterResult


def step_idempotency_key(request_id: str, step_id: str) -> str:
    """The canonical idempotency key for one step attempt."""
    return f"{request_id}:{step_id}"


def attempt_id(runtime_instance_index: int, attempt: int) -> str:
    """The canonical attempt id: ``att-{runtime_instance_index}-{attempt}``."""
    return f"att-{runtime_instance_index}-{attempt}"
