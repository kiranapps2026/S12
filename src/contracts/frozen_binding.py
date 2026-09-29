"""
Frozen Binding Identity — the immutable resolution artifact.

Created at S5. Immutable after creation. Sole downstream resolution artifact.
Never changes during failover. S6 reads this; does NOT recompute risk.

Per DATA_CONTRACTS §6: binding_id, capability_id, kernel_op_id, provider,
engine_module, adapter_class, effective_risk, effective_mutation,
resolved_at_stage, selection_rank.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FrozenBindingIdentity:
    """Immutable binding selected at S5, used for entire execution.

    Risk is computed ONCE at S5 and frozen here:
        effective_risk = max(capability.risk_floor, kernel_op.risk_floor, tag_implied_risk)

    S6 reads from this — does NOT derive risk independently.
    """
    binding_id: str                          # UUID v4
    capability_id: str                       # Resolved capability
    kernel_op_id: str                        # Resolved kernel operation
    provider: str                            # Selected provider
    engine_module: str                       # Python module path (e.g. "supr.kernel.engines.ghl")
    adapter_class: str                       # Adapter implementation class

    # === Risk (computed ONCE at S5) ===
    effective_risk: float                    # 0.0-1.0, frozen at S5
    effective_mutation: str                  # "R" | "W" | "D" | "IRREVERSIBLE"
    resolved_at_stage: str                   # Always "S5"

    # === Selection ===
    selection_rank: int = 0                  # Tie-break rank (lower = preferred)

    # === Version tracking (R-O approved extensions) ===
    capability_version: str = "1.0.0"       # Capability schema version
    binding_version: str = "1.0.0"          # Binding version
    risk_policy_version: str = "1.0.0"      # Risk policy version
    authorization_version: str = "1.0.0"    # Authorization version
