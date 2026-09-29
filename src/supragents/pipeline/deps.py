"""The ports every stage may use, bundled and injected by the caller."""
from __future__ import annotations

from dataclasses import dataclass

from supragents.ports.activation import ActivationStateReader
from supragents.ports.authorization import AuthorizationState
from supragents.ports.confirmations import ConfirmationStore
from supragents.ports.intent import IntentModel
from supragents.ports.policy import (
    CircuitBreaker,
    KernelPolicySource,
    MutationPolicy,
    PolicyVersionSource,
)
from supragents.ports.registry import CapabilityRegistry
from supragents.ports.runtime import Clock
from supragents.ports.usage import UsageRecorder


@dataclass(frozen=True)
class PipelineDeps:
    activation: ActivationStateReader
    intent_model: IntentModel
    registry: CapabilityRegistry
    authorization: AuthorizationState
    policy: KernelPolicySource
    policy_versions: PolicyVersionSource
    circuit_breaker: CircuitBreaker
    mutation_policy: MutationPolicy
    confirmations: ConfirmationStore
    usage: UsageRecorder
    clock: Clock
