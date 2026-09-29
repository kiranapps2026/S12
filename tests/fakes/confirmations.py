"""In-memory ConfirmationStore implementing the R-Z contract (test double only)."""
from __future__ import annotations

from dataclasses import replace

from supragents.contracts.outputs import Confirmation
from supragents.contracts.vocabulary import ConfirmationStatus
from supragents.ports.confirmations import StoredConfirmation


class InMemoryConfirmationStore:
    def __init__(self, clock) -> None:
        self._clock = clock
        self._records: dict[str, StoredConfirmation] = {}
        self.saved: list[tuple[Confirmation, str, str]] = []

    async def save(self, confirmation: Confirmation, *, tenant_id: str, execution_id: str) -> None:
        if not tenant_id or not execution_id:
            raise ValueError("tenant_id and execution_id are required")
        self.saved.append((confirmation, tenant_id, execution_id))
        self._records[confirmation.confirmation_id] = StoredConfirmation(
            confirmation, tenant_id, execution_id, ConfirmationStatus.PENDING
        )

    async def find(self, *, tenant_id: str, execution_id: str) -> StoredConfirmation | None:
        return next((r for r in self._records.values()
                     if r.tenant_id == tenant_id and r.execution_id == execution_id), None)

    async def consume(self, confirmation_id: str, *, tenant_id: str, user_id: str, plan_hash: str) -> bool:
        record = self._pending(confirmation_id, tenant_id, user_id)
        if record is None or record.confirmation.plan_hash != plan_hash:
            return False
        if record.confirmation.expires_at <= self._clock.now():
            self._records[confirmation_id] = replace(record, status=ConfirmationStatus.EXPIRED)
            return False
        self._records[confirmation_id] = replace(record, status=ConfirmationStatus.CONSUMED)
        return True

    async def reject(self, confirmation_id: str, *, tenant_id: str, user_id: str) -> bool:
        record = self._pending(confirmation_id, tenant_id, user_id)
        if record is None:
            return False
        self._records[confirmation_id] = replace(record, status=ConfirmationStatus.REJECTED)
        return True

    def status(self, confirmation_id: str) -> ConfirmationStatus:
        return self._records[confirmation_id].status

    def _pending(self, confirmation_id: str, tenant_id: str, user_id: str) -> StoredConfirmation | None:
        record = self._records.get(confirmation_id)
        if (record is None or record.status is not ConfirmationStatus.PENDING
                or record.tenant_id != tenant_id or record.confirmation.user_id != user_id):
            return None
        return record
