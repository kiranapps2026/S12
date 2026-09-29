"""
Confirmation store — single-use, conditional consume (C20 pattern).

The store is the only holder of confirmation status
(pending | consumed | rejected | expired); the Confirmation contract has none.
ConfirmationStoreImpl is the in-process implementation; the PostgreSQL implementation
(adapters/postgres/confirmations.py) satisfies the same protocol and decides expiry by
the database clock (it ignores ``now``).
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Protocol

from contracts.execution_manifest import Confirmation

CONSUMED = "consumed"
EXPIRED = "confirmation_expired"
MISMATCH = "confirmation_mismatch"


class ConfirmationStore(Protocol):
    async def save(self, confirmation: Confirmation, tenant_id: str, execution_id: str) -> None: ...

    async def consume(self, confirmation_id: str, *, tenant_id: str, user_id: str,
                      plan_hash: str, now: float | None = None) -> str:
        """Atomically PENDING -> CONSUMED. Returns exactly one of CONSUMED, EXPIRED, MISMATCH."""


class ConfirmationStoreImpl:
    """Atomic in-process confirmation store."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rows: dict[str, tuple[Confirmation, str, str]] = {}

    async def save(self, confirmation: Confirmation, tenant_id: str, execution_id: str) -> None:
        if not tenant_id or not execution_id:
            raise ValueError("tenant_id and execution_id are required")
        async with self._lock:
            if confirmation.confirmation_id in self._rows:
                raise ValueError("confirmation already saved")
            self._rows[confirmation.confirmation_id] = (confirmation, tenant_id, execution_id)

    async def consume(self, confirmation_id: str, *, tenant_id: str, user_id: str,
                      plan_hash: str, now: float | None = None) -> str:
        """Unknown id, other tenant, consumed already, wrong user or wrong hash -> mismatch
        (the row is untouched, so a genuine consume still works once). Expiry is checked
        only after identity matches."""
        when = time.time() if now is None else now
        async with self._lock:
            row = self._rows.get(confirmation_id)
            if row is None:
                return MISMATCH
            conf, row_tenant, execution_id = row
            if (row_tenant != tenant_id or conf.consumed_at is not None
                    or conf.user_id != user_id or conf.plan_hash != plan_hash):
                return MISMATCH
            if when > conf.expires_at:
                return EXPIRED
            self._rows[confirmation_id] = (dataclasses.replace(conf, consumed_at=when),
                                           row_tenant, execution_id)
            return CONSUMED
