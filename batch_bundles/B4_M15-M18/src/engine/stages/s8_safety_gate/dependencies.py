"""
S8 dependency interfaces for the composition root.

These Protocols and dataclasses define what S8 needs.
Implementations live in tests/fixtures/deps.py (not here).
Source: RUNBOOK R-C
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from contracts.kernel_policy import KernelPolicy
from contracts.authorization_state_provider import AuthorizationStateProvider


class CircuitBreaker(ABC):
    """Interface for circuit breaker state."""

    @abstractmethod
    def state(self, provider_id: str) -> str:
        """Return 'CLOSED', 'OPEN', or 'HALF_OPEN'."""


class MutationPolicy(ABC):
    """Interface for mutation policy."""

    @abstractmethod
    def permits(self, mutation: str, risk: float) -> bool:
        """Return True if the mutation/risk combination is permitted."""


@dataclass(frozen=True)
class S8Dependencies:
    policy: KernelPolicy | None
    auth_state: AuthorizationStateProvider | None
    circuit_breaker: CircuitBreaker | None = None
    mutation_policy: MutationPolicy | None = None
