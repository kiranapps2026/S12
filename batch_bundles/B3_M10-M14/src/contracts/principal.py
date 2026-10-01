"""Who is calling: the authenticated identity the entry point turns into an EntryRequest."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    workspace_id: str
    user_id: str
    membership_id: str
    connection_id: str
    resource_scope: str


class Authenticator(Protocol):
    async def authenticate(self, credential: str) -> Principal | None:
        """The identity for ``credential``, or None if it is unknown or revoked.

        Raise DependencyUnavailable if the identity store cannot be read.
        """
