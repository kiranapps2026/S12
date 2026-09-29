"""
S5 Provider Resolution — resolve capabilities to a specific provider adapter, freeze binding.

THIS IS THE ONE AND ONLY SOURCE OF effective_risk AND mutation_type.
After S5, these values are immutable in FrozenBindingIdentity.

Source: FINAL_ARCHITECTURE.md §11, §22
Owner: S5 / Provider Resolution
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.capability import CapabilityMetadata
from contracts.stage_outputs import CapabilityMatch
from contracts.stage_registry import StageOutcome
from contracts.errors import ResolutionError

logger = logging.getLogger(__name__)


def _build_capability_metadata(meta: dict[str, any]) -> CapabilityMetadata:
    """Reconstruct CapabilityMetadata from a metadata dict."""
    return CapabilityMetadata(
        capability_id=meta["capability_id"],
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        namespace=meta.get("namespace", ""),
        input_schema=meta.get("input_schema", {}),
        output_schema=meta.get("output_schema", {}),
        risk_floor=meta.get("risk_floor", 0.0),
        mutation_type=meta.get("mutation_type", MUTATION_READ),
        tags=meta.get("tags", []),
    )


async def handle(state: PipelineState) -> PipelineState:
    """
    S5 handler: resolve task to capability binding.

    Reads CapabilityMatch from PipelineState.capability_match (S3 output).
    Produces FrozenBindingIdentity — the authoritative risk/mutation classification.
    THIS IS THE ONE AND ONLY SOURCE OF effective_risk AND mutation_type.

    ExecutionContext does NOT receive binding/capability/provider fields.
    S5 policy version whitelist: tenant_policy_version_id,
    workspace_policy_version_id, policy_version_id only.

    Returns updated PipelineState with frozen_binding_identity set.
    """
    capability_match = state.capability_match
    if capability_match is None:
        raise ResolutionError("No CapabilityMatch from S3")

    # Handle both CapabilityMatch objects and list inputs (for tests)
    if isinstance(capability_match, list):
        # List input from tests — build CapabilityMatch from first item
        if not capability_match:
            raise ResolutionError("Empty capability candidates")
        first = capability_match[0]
        if isinstance(first, dict):
            cap_match = CapabilityMatch(
                capability_id=first["capability_id"],
                name=first.get("name", ""),
                score=first.get("score", 0.0),
                risk_floor=first.get("risk_floor", 0.0),
                mutation_type=first.get("mutation_type", MUTATION_READ),
                tags=first.get("tags", []),
                match_reasons=first.get("match_reasons", []),
            )
        else:
            cap_match = first
    else:
        cap_match = capability_match

    context = state.execution_context
    if context is None:
        raise ResolutionError("No ExecutionContext from S0")

    # Resolve from capability match — deterministic selection
    provider = "local"  # Default provider
    adapter_class = "DefaultAdapter"
    kernel_op_id = f"kernel-op-{cap_match.capability_id}"

    # S5 is the sole source of effective_risk and mutation_type
    # Risk formula: effective_risk = max(risk_floor, risk_rule, risk_implied)
    effective_risk = max(
        cap_match.risk_floor,
        cap_match.risk_rule,
        cap_match.risk_implied,
    )
    mutation_type = cap_match.mutation_type

    frozen = FrozenBindingIdentity(
        binding_id=f"binding-{context.request_id[:12]}",
        capability_id=cap_match.capability_id,
        kernel_op_id=kernel_op_id,
        provider=provider,
        engine_module=adapter_class,
        adapter_class=adapter_class,
        effective_risk=effective_risk,
        effective_mutation=mutation_type,
        resolved_at_stage="S5",
        selection_rank=0,
    )

    logger.info(
        "S5: resolved binding %s: risk=%.4f, mutation=%s",
        frozen.binding_id,
        frozen.effective_risk,
        frozen.effective_mutation,
    )

    return state.with_stage_output("S5", frozen)
