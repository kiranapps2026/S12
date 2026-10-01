"""Step idempotency (gate C9, C17; MUTATION_SAFETY §5)."""
from __future__ import annotations

from dataclasses import dataclass

from contracts.step_execution import AdapterResult


def step_idempotency_key(request_id: str, plan_step_id: str) -> str:
    return f"{request_id}:{plan_step_id}"


def attempt_id(step_index: int, attempt: int) -> str:
    return f"att-{step_index}-{attempt}"


@dataclass(frozen=True)
class LedgerRecord:
    kernel_op_id: str
    kind: str                 # "success" | "failure"
    result: AdapterResult


class IdempotencyConflict(Exception):  # noqa: N818 (name fixed by golden M11, like FencedOut)
    """A ledger row for the key exists with another tenant, operation or result kind: an invariant violation."""
