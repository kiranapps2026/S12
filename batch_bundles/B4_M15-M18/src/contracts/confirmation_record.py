"""The stored confirmation row as S12 entry sees it (gate C20), and the reader S12 entry uses to fetch it.

S10 saves the confirmation before the run exists; S12 entry reads the row back to check that the confirmation was
consumed for the run being admitted. ``status`` is a ``ConfirmationStatus`` value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConsumedConfirmation:
    status: str
    execution_id: str
    plan_hash: str
    user_id: str


class ConsumedConfirmationReader(Protocol):
    async def read(self, confirmation_id: str, *, tenant_id: str) -> ConsumedConfirmation | None:
        """The row for ``confirmation_id`` as visible to ``tenant_id`` (None when absent or another tenant's).
        Raise DependencyUnavailable if the store cannot be read."""
