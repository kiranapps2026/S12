"""Normalized inbound request received by S0 (PIPELINE_STAGES §2 "Cautions").

Transport code authenticates the caller and fills the identity fields before S0.
Nothing here comes from the request body or from an LLM, except ``text``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from supragents.contracts.vocabulary import ActivationMode, ActorType


@dataclass(frozen=True)
class EntryRequest:
    text: str
    activation_mode: ActivationMode
    tenant_id: str
    workspace_id: str
    user_id: str
    membership_id: str
    actor_type: ActorType
    connection_id: str
    conversation_id: str
    resource_scope: str
    actor_id: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
