"""Where the gateway gets signing secrets and the identity a webhook endpoint acts as."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.principal import Principal


@dataclass(frozen=True)
class SigningSecret:
    """One usable secret of an endpoint. `value` is a bytearray the caller overwrites after use."""
    credential_id: str
    status: str                      # "active" | "retiring"
    value: bytearray


@dataclass(frozen=True)
class WebhookEndpoint:
    """What an endpoint id resolves to: the fixed identity events run as, and the usable
    secrets (the active one first, then a retiring one still inside its grace period)."""
    principal: Principal
    secrets: tuple[SigningSecret, ...]


class WebhookCredentialStore(Protocol):
    async def endpoint(self, endpoint_id: str, source_system: str) -> WebhookEndpoint | None:
        """None if the endpoint is unknown, not for `source_system`, or has no usable secret.
        Raise DependencyUnavailable if the store cannot be read."""

    async def mark_verified(self, credential_id: str) -> None:
        """Record a successful verification (best effort)."""


@dataclass(frozen=True)
class StoredEvent:
    """Result of durably recording an event."""
    duplicate: bool


class EventLog(Protocol):
    async def record(self, *, envelope, principal: Principal, idempotency_key: str,
                     raw_body: bytes, auth_method: str, auth_principal: str) -> StoredEvent:
        """Store the raw payload once per (tenant, idempotency_key). A repeat is `duplicate`."""

    async def finish(self, tenant_id: str, event_id: str, status: str) -> None:
        """Set the processing status: 'processed' or 'failed'."""
