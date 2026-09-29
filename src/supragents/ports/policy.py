"""Kernel policy, circuit breaker and mutation policy ports (S7, S8)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from supragents.contracts.vocabulary import CircuitState, Mutation


@dataclass(frozen=True)
class KernelPolicy:
    kill_switch_engaged: bool
    risk_deny_threshold: float


class KernelPolicySource(Protocol):
    async def current(self, tenant_id: str) -> KernelPolicy:
        """Read live on every run: the kill switch must take effect immediately."""


@dataclass(frozen=True)
class PolicyVersions:
    """Policy versions in force for this tenant and workspace; S5 records them."""

    tenant_policy_version_id: str
    workspace_policy_version_id: str
    policy_version_id: str


class PolicyVersionSource(Protocol):
    async def current(self, tenant_id: str, workspace_id: str) -> PolicyVersions: ...


class CircuitBreaker(Protocol):
    async def state(self, provider: str) -> CircuitState: ...


class MutationPolicy(Protocol):
    async def permits(self, tenant_id: str, mutation: Mutation, risk: float) -> bool: ...
