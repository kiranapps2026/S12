"""Durable pending-confirmation store (PIPELINE_STAGES §12, ruling R-Z).

Implementations own the clock used for expiry (database time in production), and
reject empty ``tenant_id`` / ``execution_id`` with ValueError.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from supragents.contracts.outputs import Confirmation
from supragents.contracts.vocabulary import ConfirmationStatus


@dataclass(frozen=True)
class StoredConfirmation:
    confirmation: Confirmation
    tenant_id: str
    execution_id: str
    status: ConfirmationStatus


class ConfirmationStore(Protocol):
    async def save(self, confirmation: Confirmation, *, tenant_id: str, execution_id: str) -> None: ...

    async def find(self, *, tenant_id: str, execution_id: str) -> StoredConfirmation | None: ...

    async def consume(
        self, confirmation_id: str, *, tenant_id: str, user_id: str, plan_hash: str
    ) -> bool:
        """Atomically PENDING -> CONSUMED if tenant, user and plan hash match and not expired."""

    async def reject(self, confirmation_id: str, *, tenant_id: str, user_id: str) -> bool:
        """Atomically PENDING -> REJECTED if tenant and user match."""
