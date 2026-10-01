"""Dead-letter operator service (C21, D4, D5, IMP-M17-2; PHASE_5B §13).

Wraps ``PostgresDeadLetters`` to expose the operator-facing dead-letter lifecycle that the truth model defines
(PENDING → RETRYING → RESOLVED / ABANDONED). The adapter already implements each transition; this module provides
the query surface (list, get) and the lifecycle methods with tenant-isolated access.

This service lives in ``s15_final_state`` because it runs after the pipeline is terminal: an operator inspects or
resolves dead letters on a run that has finished, not while it is still executing. The engine path in ``loop.py``
continues to call ``PostgresDeadLetters.create`` directly; no durable write bypasses the adapter.

State transitions:
    PENDING  → start_retry() → RETRYING → resolve(outcome) / abandon() → RESOLVED / ABANDONED
    PENDING  → resolve(outcome) → RESOLVED
    PENDING  → abandon() → ABANDONED
    RETRYING → retry_inconclusive() → PENDING (after an inconclusive answer)
    RETRYING → resolve(outcome) → RESOLVED
    RETRYING → abandon() → ABANDONED

``start_retry`` raises ``ValueError`` for ``retry_mode == NONE`` (D5). The caller must catch it and report the
reason to the operator.
"""
from __future__ import annotations

import json

from adapters.postgres.dead_letters import DeadLetterRecord, PostgresDeadLetters
from contracts.execution_states import DeadLetterStatus, ResolutionOutcome, RetryMode

__all__ = ["DeadLetterOperatorService"]

_SELECT_BASE = (
    "SELECT * FROM dead_letters WHERE tenant_id = $1"
)
_SELECT_STATUS = " AND status = $2"
_SELECT_STEP = " AND step_id = $2"
_SELECT_BOTH = " AND status = $2 AND step_id = $3"
_ORDER_LIMIT = " ORDER BY created_at DESC LIMIT $%d"


class DeadLetterOperatorService:
    """Operator-facing dead-letter lifecycle service."""

    def __init__(self, dead_letters: PostgresDeadLetters) -> None:
        self._dl = dead_letters

    async def list_(self, tenant_id: str, *, status: str | None = None,
                    step_id: str | None = None, limit: int = 50) -> list[DeadLetterRecord]:
        """List dead letters for a tenant, optionally filtered by status and/or step_id.

        ``limit`` caps the result; the caller should paginate for large sets.
        """
        has_status = status is not None
        has_step = step_id is not None
        if has_status and has_step:
            where = _SELECT_BASE + _SELECT_BOTH
            pn = 3
        elif has_status:
            where = _SELECT_BASE + _SELECT_STATUS
            pn = 2
        elif has_step:
            where = _SELECT_BASE + _SELECT_STEP
            pn = 2
        else:
            where = _SELECT_BASE
            pn = 1
        params: list = [tenant_id]
        if has_status:
            params.append(status)
        if has_step:
            params.append(step_id)
        params.append(min(limit, 200))
        sql = where + " " + (_ORDER_LIMIT % (pn + 1))
        async with self._dl._db.tenant_transaction(tenant_id) as c:
            rows = await c.fetch(sql, *params)
        return [_to_record(r) for r in rows]

    async def get(self, tenant_id: str, dead_letter_id: str) -> DeadLetterRecord | None:
        """Inspect one dead letter by id."""
        return await self._dl.get(tenant_id, dead_letter_id)

    async def start_retry(self, tenant_id: str, dead_letter_id: str) -> DeadLetterRecord:
        """Move a dead letter from PENDING to RETRYING (D5).

        Raises ``ValueError`` if the record's ``retry_mode`` is NONE — NONE dead letters can only be resolved
        or abandoned by an operator, not retried.
        """
        return await self._dl.start_retry(tenant_id, dead_letter_id)

    async def resolve(self, tenant_id: str, dead_letter_id: str, outcome: str) -> None:
        """Operator resolution: moves the record to RESOLVED with the given outcome (C21).

        ``outcome`` must be one of ``EXECUTED``, ``NOT_EXECUTED``, ``UNDETERMINED``.
        """
        await self._dl.resolve(tenant_id, dead_letter_id, outcome)

    async def abandon(self, tenant_id: str, dead_letter_id: str,
                      outcome: str = ResolutionOutcome.UNDETERMINED) -> None:
        """Operator abandonment: moves the record to ABANDONED (C21)."""
        await self._dl.abandon(tenant_id, dead_letter_id, outcome)

    async def retry_inconclusive(self, tenant_id: str, dead_letter_id: str) -> None:
        """Return a RETRYING record to PENDING after an inconclusive retry (D5)."""
        await self._dl.retry_inconclusive(tenant_id, dead_letter_id)

    async def retryable(self, tenant_id: str, dead_letter_id: str) -> bool:
        """True if the record is PENDING and its retry_mode allows a retry (D5)."""
        record = await self._dl.get(tenant_id, dead_letter_id)
        if record is None or record.status != DeadLetterStatus.PENDING:
            return False
        return record.retry_mode in (RetryMode.PROBE, RetryMode.VERIFY)


def _to_record(row) -> DeadLetterRecord:
    """Convert a raw asyncpg row to DeadLetterRecord without the FOR UPDATE lock."""
    context = row["context"]
    return DeadLetterRecord(
        row["dead_letter_id"], row["tenant_id"], row["execution_id"], row["step_id"],
        row["kernel_op_id"], row["reservation_id"], row["attempt_id"], row["episode_id"],
        row["error_type"], row["retry_mode"], row["origin"], row["status"],
        row["resolution_outcome"], row["retry_count"], row["max_retries"],
        json.loads(context) if isinstance(context, str) else dict(context))
