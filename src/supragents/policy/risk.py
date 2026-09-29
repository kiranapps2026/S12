"""Effective risk and mutation, computed once at S5 (PIPELINE_STAGES §7)."""
from __future__ import annotations

from supragents.contracts.registry import CapabilityMetadata, KernelOperation
from supragents.contracts.vocabulary import Mutation


def effective_risk(capability: CapabilityMetadata, kernel_op: KernelOperation) -> float:
    """Risk only goes up: the maximum of every registry-defined risk input."""
    risk = max(
        capability.risk_floor,
        capability.risk_rule,
        capability.risk_implied,
        kernel_op.risk_floor,
    )
    if not 0.0 <= risk <= 1.0:
        raise ValueError(f"registry risk out of range for {capability.capability_id}: {risk}")
    return risk


def effective_mutation(capability: CapabilityMetadata, kernel_op: KernelOperation) -> Mutation:
    """The more dangerous of the capability's and the operation's mutation class."""
    return max(capability.mutation, kernel_op.mutation, key=lambda mutation: mutation.severity)
