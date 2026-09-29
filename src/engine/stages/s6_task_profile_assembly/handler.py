"""
S6 Task Profile Assembly — assemble complete task profile from FrozenBindingIdentity.

CRITICAL: S6 reads effective_risk and mutation_type from FrozenBindingIdentity.
It does NOT recompute risk. Risk was computed ONCE at S5 and frozen there.

Source: DATA_CONTRACTS.md §7, PIPELINE_STAGES.md §8
Owner: S6 / Task Profile Assembly
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.safety import TaskProfile
from contracts.stage_registry import StageStatus

logger = logging.getLogger(__name__)


class TaskProfileAssemblyError(Exception):
    """Failed to assemble task profile."""
    pass


async def handle(state: PipelineState) -> PipelineState:
    """
    S6 handler: assemble TaskProfile from FrozenBindingIdentity.

    Reads FrozenBindingIdentity from PipelineState.frozen_binding_identity (S5 output).
    Reads execution_context for context fields.
    Does NOT recompute risk/mutation — reads from frozen binding.
    Computes requires_confirmation per DATA_CONTRACTS §7 confirmation requirements table.

    Returns updated PipelineState with task_profile set.
    """
    frozen = state.frozen_binding_identity
    if frozen is None:
        raise TaskProfileAssemblyError("No FrozenBindingIdentity from S5")

    context = state.execution_context
    if context is None:
        raise TaskProfileAssemblyError("No ExecutionContext from S0")

    # Confirmation (R-V, amended): D and IRREVERSIBLE are NEVER executed without confirmation
    # (PIPELINE_STAGES §12 wins over the older DATA_CONTRACTS §7 "D only above cost 5").
    #   Rule 1: any D or IRREVERSIBLE mutation -> confirm, whatever the cost or risk
    #   Rule 2: effective_risk > 0.7 -> confirm
    #   Rule 3: total_cost (per_step_cost * steps_estimated) > 20 -> confirm
    # Comparisons are strict. Cross-provider (3+) cannot occur: one binding, one provider (R-U).
    graph_analysis = state.graph_analysis
    capability_match = state.capability_match
    # R-V: the capability metadata for the frozen binding's capability is required; without it
    # the cost is unknown, and an unknown cost is never assumed to be cheap.
    if (capability_match is None or capability_match.capability_id != frozen.capability_id
            or not isinstance(capability_match.estimated_cost_units, int)
            or capability_match.estimated_cost_units < 1):
        return state.with_status(StageStatus.DENY, "capability_metadata_missing")
    per_step_cost = capability_match.estimated_cost_units
    steps_est = len(graph_analysis.execution_steps) if (graph_analysis and graph_analysis.execution_steps) else 1
    total_cost = per_step_cost * steps_est
    requires_confirmation = (
        frozen.effective_mutation in ("D", "IRREVERSIBLE")
        or frozen.effective_risk > 0.7
        or total_cost > 20
    )

    # Get sanitized input for metadata
    norm_input = state.normalized_input

    # Assemble TaskProfile from FrozenBindingIdentity (risk/mutation READ from frozen, NOT recomputed)
    task_profile = TaskProfile(
        intent="unknown",
        capabilities=(frozen.capability_id,),
        graph_type=graph_analysis.complexity if graph_analysis else "simple",
        steps_estimated=steps_est,
        mutations=(frozen.effective_mutation,) * steps_est,
        risk=frozen.effective_risk,
        cost=total_cost,
        requires_confirmation=requires_confirmation,
        resource_scope=context.resource_scope or context.tenant_id,
        providers=(frozen.provider,),
    )

    logger.info(
        "S6: assembled task profile: risk=%.4f, mutation=%s, requires_confirmation=%s",
        task_profile.risk,
        task_profile.mutations[0],
        task_profile.requires_confirmation,
    )

    return state.with_stage_output("S6", task_profile)
