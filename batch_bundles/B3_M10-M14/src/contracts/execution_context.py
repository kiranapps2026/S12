"""
Frozen Execution Context — the immutable request envelope.

Source: DATA_CONTRACTS.md §2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExecutionMode(StrEnum):
    """Execution authorization modes."""
    STANDARD = "standard"
    WORKFLOW = "workflow"
    ADAPTIVE = "adaptive"


class ActorType(StrEnum):
    """Who initiated this execution."""
    USER = "user"
    WORKER = "worker"
    SYSTEM = "system"


@dataclass(frozen=True)
class ExecutionContext:
    """Frozen request state — all fields from non-LLM sources only."""
    # Required fields first
    trace_id: str                    # UUID v4
    request_id: str                  # UUID v4
    tenant_id: str                   # UUID v4
    workspace_id: str                # UUID v4
    user_id: str                     # UUID v4
    membership_id: str = ""          # User -> workspace -> role binding

    # Actor
    actor_type: ActorType = ActorType.USER
    actor_id: str | None = None

    # Request identity
    conversation_id: str | None = None
    connection_id: str | None = None
    idempotency_key: str = ""
    resource_scope: str = ""
    tags: frozenset = field(default_factory=frozenset)

    # Task identity (S2)
    task_id: str | None = None

    # Authorization (S8)
    auth_passed: bool = False
    auth_result_id: str | None = None

    # Policy version whitelist
    tenant_policy_version_id: str | None = None
    workspace_policy_version_id: str | None = None
    policy_version_id: str | None = None
