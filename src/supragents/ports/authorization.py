"""Live authorization state read by the S8 safety checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from supragents.contracts.vocabulary import RecordStatus


@dataclass(frozen=True)
class ConnectionState:
    status: RecordStatus
    expires_at: float | None


class AuthorizationState(Protocol):
    """Every method raises DependencyUnavailable when it cannot answer."""

    async def user_status(self, user_id: str) -> RecordStatus: ...

    async def tenant_status(self, tenant_id: str) -> RecordStatus: ...

    async def connection_state(self, connection_id: str) -> ConnectionState: ...

    async def has_grant(self, tenant_id: str, user_id: str, capability_id: str) -> bool: ...

    async def workspace_in_scope(
        self, tenant_id: str, user_id: str, workspace_id: str, membership_id: str
    ) -> bool: ...

    async def budget_available(self, tenant_id: str, amount: int) -> bool: ...
