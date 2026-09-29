"""The authenticated request S0 turns into an ExecutionContext."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryRequest:
    """Incoming request at the entry point.

    Identity fields (tenant_id, workspace_id, user_id) come from the authenticated
    transport (API key / session), never from the payload.
    """
    raw_payload: dict
    entry_channel: str
    tenant_id: str
    conversation_id: str | None = None
    connection_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    workspace_id: str | None = None
    membership_id: str = ""
    idempotency_key: str = ""
    resource_scope: str = ""
    tags: frozenset = frozenset()
