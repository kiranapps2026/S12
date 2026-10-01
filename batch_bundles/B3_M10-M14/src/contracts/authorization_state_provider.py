"""
Authorization state provider interface for S8 safety checks.

Source: DATA_CONTRACTS §8, PIPELINE_STAGES §10, RUNBOOK R-C
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AuthorizationStateProvider(ABC):
    """Read-only authorization state for S8 checks."""

    @abstractmethod
    def user_status(self, user_id: str) -> str | None:
        """Return 'active', 'deactivated', or None if unavailable."""

    @abstractmethod
    def tenant_status(self, tenant_id: str) -> str | None:
        """Return 'active', 'suspended', or None if unavailable."""

    @abstractmethod
    def connection_status(self, connection_id: str) -> tuple[str | None, float | None]:
        """Return (status, expires_at). status: 'active', 'revoked', or None."""

    @abstractmethod
    def has_grant(self, tenant_id: str, user_id: str, capability_id: str) -> bool | None:
        """Return True if the capability grant is valid."""

    @abstractmethod
    def in_scope(self, tenant_id: str, user_id: str, workspace_id: str) -> bool | None:
        """Return True if the workspace is within the tenant/user scope."""

    @abstractmethod
    def budget_available(self, tenant_id: str, amount: float) -> bool | None:
        """Return True if the tenant has sufficient budget."""
