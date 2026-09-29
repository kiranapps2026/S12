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


class CircuitBreaker(Protocol):
    async def state(self, provider: str) -> CircuitState: ...


class MutationPolicy(Protocol):
    async def permits(self, tenant_id: str, mutation: Mutation, risk: float) -> bool: ...
