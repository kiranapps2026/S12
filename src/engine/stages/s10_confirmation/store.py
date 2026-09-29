"""
Confirmation store — single-use, conditional consume (C20 pattern).

The store is the only holder of confirmation status
(pending | consumed | rejected | expired); the Confirmation contract has none.
This in-process implementation is the production store for a single process; the
PostgreSQL implementation lives with the persistence adapters and must satisfy the
same protocol.
"""
from __future__ import annotations

import dataclasses
import threading
from typing import Protocol

from contracts.execution_manifest import Confirmation

CONSUMED = "consumed"
EXPIRED = "confirmation_expired"
MISMATCH = "confirmation_mismatch"


class ConfirmationStore(Protocol):
    def save(self, confirmation: Confirmation, tenant_id: str, execution_id: str) -> None: ...

    def consume(self, confirmation_id: str, *, user_id: str, plan_hash: str,
                now: float) -> str: ...


class ConfirmationStoreImpl:
    """Atomic, in-process confirmation store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, tuple[Confirmation, str, str]] = {}

    def save(self, confirmation: Confirmation, tenant_id: str, execution_id: str) -> None:
        with self._lock:
            if confirmation.confirmation_id in self._rows:
                raise ValueError("confirmation already saved")
            self._rows[confirmation.confirmation_id] = (confirmation, tenant_id, execution_id)

    def consume(self, confirmation_id: str, *, user_id: str, plan_hash: str,
                now: float) -> str:
        """Conditional consume: exactly one of consumed / expired / mismatch.

        Unknown id, consumed already, wrong user or wrong hash -> mismatch (the row
        is left untouched, so a genuine consume still works once). Expiry is checked
        only after identity matches.
        """
        with self._lock:
            row = self._rows.get(confirmation_id)
            if row is None:
                return MISMATCH
            conf, tenant_id, execution_id = row
            if (conf.consumed_at is not None or conf.user_id != user_id
                    or conf.plan_hash != plan_hash):
                return MISMATCH
            if now > conf.expires_at:
                return EXPIRED
            consumed = dataclasses.replace(conf, consumed_at=now)
            self._rows[confirmation_id] = (consumed, tenant_id, execution_id)
            return CONSUMED

    def get(self, confirmation_id: str) -> Confirmation | None:
        with self._lock:
            row = self._rows.get(confirmation_id)
            return row[0] if row else None
