"""Registry records: the only source of capability, risk and mutation data.

Risk and mutation never come from the request or from the LLM (I-007); S3 and S5
read them from these records through ``ports.registry.CapabilityRegistry``.
"""
from __future__ import annotations

from dataclasses import dataclass

from supragents.contracts.vocabulary import Mutation, RetrySafety, TruthState


@dataclass(frozen=True)
class CapabilityMetadata:
    """DATA_CONTRACTS §5."""

    capability_id: str
    name: str
    intent: str
    mutation: Mutation
    risk_floor: float
    risk_rule: float
    risk_implied: float
    truth_state: TruthState


@dataclass(frozen=True)
class KernelOperation:
    """Per-operation policy (DATA_CONTRACTS §12)."""

    kernel_op_id: str
    mutation: Mutation
    risk_floor: float
    cost: int
    timeout_seconds: int
    retry_safety: RetrySafety
    truth_state: TruthState
    inverse: str | None = None


@dataclass(frozen=True)
class BindingRow:
    """Capability-to-adapter mapping (DATA_CONTRACTS §6)."""

    binding_id: str
    capability_id: str
    kernel_op_id: str
    provider: str
    engine_module: str
    adapter_class: str
    priority: int
    created_at: float
    is_active: bool


@dataclass(frozen=True)
class RegistryVersions:
    """Registry versions stamped into the ExecutionManifest (DATA_CONTRACTS §27).

    ``policy_version`` is not here: it comes from ExecutionContext.policy_version_id (S5).
    """

    capability_version: str
    binding_version: str
    risk_policy_version: str
    authorization_version: str
    worker_runtime_version: str
    model_version: str
