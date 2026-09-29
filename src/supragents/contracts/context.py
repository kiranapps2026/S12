"""ExecutionContext — the frozen request identity (DATA_CONTRACTS §2).

Created once by S0. Only S2 (``task_id``), S5 (the policy version ids) and S8
(``auth_passed``, ``auth_result_id``) may produce a replacement instance, through
``PipelineState.with_context`` (ruling R-M).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from supragents.contracts.vocabulary import ActivationMode, ActorType


@dataclass(frozen=True)
class ExecutionContext:
    trace_id: str
    request_id: str
    tenant_id: str
    workspace_id: str
    user_id: str
    membership_id: str
    actor_type: ActorType
    activation_mode: ActivationMode
    conversation_id: str
    connection_id: str
    resource_scope: str
    actor_id: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    task_id: str | None = None
    auth_passed: bool = False
    auth_result_id: str | None = None
    tenant_policy_version_id: str | None = None
    workspace_policy_version_id: str | None = None
    policy_version_id: str | None = None

    @property
    def idempotency_key(self) -> str:
        """Canonical idempotency key: the request id (DATA_CONTRACTS §2)."""
        return self.request_id


CONTEXT_REPLACEMENT_WHITELIST = MappingProxyType({
    "S2": frozenset({"task_id"}),
    "S5": frozenset({"tenant_policy_version_id", "workspace_policy_version_id", "policy_version_id"}),
    "S8": frozenset({"auth_passed", "auth_result_id"}),
})
