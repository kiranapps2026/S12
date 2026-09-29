"""
Capability model — capability contracts, metadata, and registry interface.

Source: FINAL_ARCHITECTURE.md §14, DATA_CONTRACTS.md §5
"""

from __future__ import annotations

from constants import MUTATION_READ

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilityMetadata:
    """
    Metadata for a registered capability.

    Source: DATA_CONTRACTS.md §5
    """
    capability_id: str                   # UUID v4
    name: str
    description: str
    namespace: str                       # Capability namespace

    # === Contract ===
    input_schema: dict[str, Any]         # JSON Schema for inputs
    output_schema: dict[str, Any]        # JSON Schema for outputs
    parameters: dict[str, Any] = field(default_factory=dict)

    # === Risk ===
    risk_floor: float = 0.0              # Minimum risk (0.0-1.0)
    mutation_type: str = MUTATION_READ          # READ, IDEMPOTENT_WRITE, DELETE, IRREVERSIBLE

    # === Provider Requirements ===
    requires_auth: bool = False
    required_provider_types: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)

    # === Cost ===
    estimated_cost_units: int = 1
    estimated_duration_seconds: int = 30

    # === Risk components (S5 uses these for effective_risk formula) ===
    risk_rule: float = 0.0  # Policy-derived risk
    risk_implied: float = 0.0  # Context-implied risk

    # === State ===
    is_active: bool = True
    version: str = "1.0.0"
    certification_status: str = "DESIGNED"  # Capability lifecycle

    # === Metadata ===
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BindingRow:
    """
    A binding between a capability and a specific provider adapter.

    Source: DATA_CONTRACTS.md §6, RESOLVE_LAYER.md
    """
    binding_id: str                      # UUID v4
    capability_id: str
    provider: str
    adapter_class: str
    capability_version: str
    binding_version: str
    policy_version: str
    risk_policy_version: str
    authorization_version: str
    effective_risk: float                # 0.0-1.0, frozen at S5
    selection_rank: int = 0
    is_active: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


class CapabilityRegistry:
    """
    Interface for the capability registry.

    Canonical owner: S3 / Capability Discovery
    """

    async def discover(self, intent: dict[str, Any], tenant_id: str) -> list[CapabilityMetadata]:
        """Discover capabilities matching an intent for a tenant."""
        raise NotImplementedError

    async def get_capability(self, capability_id: str) -> CapabilityMetadata | None:
        """Get a specific capability by ID."""
        raise NotImplementedError

    async def list_bindings(self, capability_id: str) -> list[BindingRow]:
        """List all bindings for a capability."""
        raise NotImplementedError
