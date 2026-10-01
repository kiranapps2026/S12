"""
Worker identity and lifecycle contracts.

Source: DATA_CONTRACTS.md §29-33, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class WorkerStatus(StrEnum):
    """WorkerIdentity lifecycle states."""
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    TERMINATED = "TERMINATED"


class WorkerVersionStatus(StrEnum):
    """WorkerVersion lifecycle states."""
    REGISTERED = "REGISTERED"
    INACTIVE = "INACTIVE"
    CANARY = "CANARY"
    RAMPING = "RAMPING"
    CURRENT = "CURRENT"
    DEPRECATED = "DEPRECATED"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    RETIRED = "RETIRED"


class WorkerSubscriptionState(StrEnum):
    """Worker subscription states for execution polling."""
    IDLE = "IDLE"
    POLLING = "POLLING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class WorkerIdentity:
    """
    Worker identity — separate from Worker Runtime and Model.

    Source: DATA_CONTRACTS.md §29, IDENTITY_AND_TENANCY.md §14
    """
    worker_id: str                        # UUID v4
    name: str
    description: str
    tenant_id: str                         # Owning tenant
    endpoint_url: str                      # Worker's API endpoint
    capabilities: list[str] = field(default_factory=list)
    max_concurrent: int = 10               # Max concurrent executions
    current_load: int = 0                  # Current execution count
    locality_score: float = 0.0            # 0.0-1.0, advisory only
    metadata: dict[str, str] = field(default_factory=dict)
    status: str = WorkerStatus.REGISTERED.value
    created_at: float = field(default_factory=lambda: 0.0)
    updated_at: float = field(default_factory=lambda: 0.0)
    last_heartbeat: float | None = None


@dataclass(frozen=True)
class WorkerVersion:
    """
    Worker code version with rollout lifecycle.

    Source: DATA_CONTRACTS.md §30, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §4
    """
    version_id: str                        # UUID v4
    worker_id: str                         # Parent worker
    version: str                           # Semantic version
    runtime_image: str                     # Container image
    model_id: str                          # LLM model identifier
    canary_percentage: int = 0             # 0-100
    rollout_status: str = WorkerVersionStatus.REGISTERED.value
    contract_hash: str = ""                # Hash of worker contract
    is_production_enabled: bool = False
    created_at: float = field(default_factory=lambda: 0.0)


@dataclass(frozen=True)
class WorkerDeployment:
    """
    Worker deployment tracking.

    Source: DATA_CONTRACTS.md §31, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §5
    """
    deployment_id: str                     # UUID v4
    worker_id: str
    version_id: str
    deployment_status: str                 # PENDING, DEPLOYING, ACTIVE, FAILED, ROLLED_BACK
    target_replicas: int = 1
    current_replicas: int = 0
    healthy_replicas: int = 0
    error_message: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    created_at: float = field(default_factory=lambda: 0.0)


@dataclass(frozen=True)
class ExecutionOwnership:
    """
    Execution ownership record — who owns what in an execution.

    Source: DATA_CONTRACTS.md §37, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §14
    """
    ownership_id: str                      # UUID v4
    execution_id: str
    worker_id: str | None                  # Executing worker
    tenant_id: str
    user_id: str
    plan_hash: str                         # Plan integrity
    lock_token: str | None = None          # For atomic ownership claims
    acquired_at: float = field(default_factory=lambda: 0.0)
    released_at: float | None = None


@dataclass(frozen=True)
class AdmissionDecision:
    """
    Admission control decision from S12.

    Source: DATA_CONTRACTS.md §38, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §11
    """
    decision_id: str                       # UUID v4
    execution_id: str
    decision: str                          # ACCEPT, DELAY, REJECT
    gate_results: dict[str, bool] = field(default_factory=dict
    )
    delay_reason: str | None = None
    rejection_reason: str | None = None
    created_at: float = field(default_factory=lambda: 0.0)


@dataclass(frozen=True)
class VerificationResult:
    """
    Verification result from S13.

    Source: DATA_CONTRACTS.md §14, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md §8
    """
    verification_id: str                   # UUID v4
    execution_id: str
    overall_result: str                    # PASS, FAIL, UNKNOWN
    layer_results: list[dict[str, Any]] = field(default_factory=list)
    observation_method: str = ""           # How provider state was observed
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: 0.0)


@dataclass(frozen=True)
class BudgetTracker:
    """
    Budget tracking for a tenant.

    Source: DATA_CONTRACTS.md §16, RELIABILITY.md §4
    """
    tenant_id: str
    total_budget: float                    # Total budget
    reserved: float = 0.0                  # Currently reserved
    committed: float = 0.0                 # Already spent
    available: float = 0.0                 # Available = total - reserved - committed
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.available == 0.0:
            object.__setattr__(self, "available", self.total_budget - self.reserved - self.committed)
