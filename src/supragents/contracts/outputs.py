"""Stage outputs S1–S11. Each is written once, by its owning stage (see state.py)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from supragents.contracts.frozen_json import FrozenJson
from supragents.contracts.registry import CapabilityMetadata
from supragents.contracts.vocabulary import (
    ConfirmationStatus,
    GraphType,
    Mutation,
    PathDecision,
    RetrySafety,
)


@dataclass(frozen=True)
class NormalizedInput:
    """S1."""

    text: str
    injection_detected: bool
    injection_patterns: tuple[str, ...]
    high_severity: bool


@dataclass(frozen=True)
class IntentResult:
    """S2. ``parameters`` are LLM output: data for the operation, never policy."""

    intent: str
    parameters: Mapping[str, FrozenJson]
    confidence: float
    raw_response: str
    task_id: str
    attempt: int


@dataclass(frozen=True)
class CapabilityMatch:
    """S3. Exactly one production-enabled capability (multi-capability is M2)."""

    capability: CapabilityMetadata


@dataclass(frozen=True)
class GraphAnalysis:
    """S4. One entry of ``step_params`` per step; each step depends on the previous one."""

    graph_type: GraphType
    step_params: tuple[Mapping[str, FrozenJson], ...]

    @property
    def step_count(self) -> int:
        return len(self.step_params)


@dataclass(frozen=True)
class FrozenBindingIdentity:
    """S5. The only binding S12 ever receives; never re-resolved (DATA_CONTRACTS §6)."""

    binding_id: str
    capability_id: str
    kernel_op_id: str
    provider: str
    engine_module: str
    adapter_class: str
    effective_risk: float
    effective_mutation: Mutation
    cost_per_step: int
    timeout_seconds: int
    retry_safety: RetrySafety
    inverse: str | None
    selection_rank: int
    resolved_at_stage: str = "S5"


@dataclass(frozen=True)
class TaskProfile:
    """S6 (DATA_CONTRACTS §7). Risk and mutation are copied from S5, never recomputed."""

    intent: str
    capability_ids: tuple[str, ...]
    graph_type: GraphType
    steps_estimated: int
    mutations: tuple[Mutation, ...]
    risk: float
    cost: int
    requires_confirmation: bool
    resource_scope: str
    providers: tuple[str, ...]


@dataclass(frozen=True)
class PathRouting:
    """S7."""

    decision: PathDecision
    reason: str | None


@dataclass(frozen=True)
class SafetyResult:
    """S8 (DATA_CONTRACTS §8). ``result_id`` is recorded as ``auth_result_id``."""

    allowed: bool
    result_id: str
    reason: str | None = None
    failed_check: str | None = None


@dataclass(frozen=True)
class Step:
    """DATA_CONTRACTS §4."""

    id: str
    kernel_op_id: str
    params: Mapping[str, FrozenJson]
    depends_on: tuple[str, ...]
    mutation: Mutation
    risk: float
    cost: int
    timeout_seconds: int
    retry_safety: RetrySafety
    inverse: str | None


@dataclass(frozen=True)
class Plan:
    """DATA_CONTRACTS §4. ``budget_required`` is an estimate; S12 reserves."""

    id: str
    execution_id: str
    steps: tuple[Step, ...]
    join_mode: str
    budget_required: int
    created_at: float


@dataclass(frozen=True)
class PlanCreationResult:
    """S9: the plan and the SHA-256 digest that confirmation binds to."""

    plan: Plan
    plan_hash: str


@dataclass(frozen=True)
class Confirmation:
    """DATA_CONTRACTS §13 — unchanged (ruling R-Z)."""

    confirmation_id: str
    user_id: str
    conversation_id: str
    plan_id: str
    plan_hash: str
    operations: tuple[Mapping[str, FrozenJson], ...]
    expires_at: float
    consumed_at: float | None = None


@dataclass(frozen=True)
class ConfirmationCheck:
    """S10. ``confirmation`` is None only when no confirmation is required."""

    status: ConfirmationStatus
    confirmation: Confirmation | None


@dataclass(frozen=True)
class ValidationResult:
    """S11 (secondary output)."""

    is_valid: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionManifest:
    """S11 (DATA_CONTRACTS §27). S12 executes exactly this manifest."""

    execution_id: str
    trace_id: str
    tenant_id: str
    workspace_id: str
    plan_hash: str
    binding_id: str
    auth_result_id: str
    capability_version: str
    binding_version: str
    policy_version: str
    risk_policy_version: str
    authorization_version: str
    worker_runtime_version: str
    model_version: str
    created_at: float
