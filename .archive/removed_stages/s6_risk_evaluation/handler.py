"""
S6 Risk Evaluation — assemble TaskProfile from FrozenBindingIdentity.

CRITICAL: S6 reads effective_risk and mutation_type from FrozenBindingIdentity.
It does NOT recompute risk. Risk was computed ONCE at S5 and frozen there.

Source: FINAL_ARCHITECTURE.md §11
Owner: S6 / Task Profile Assembly
"""

from __future__ import annotations

import logging
from dataclasses import replace

from contracts.pipeline_state import PipelineState
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.safety import TaskProfile
from contracts.stage_outputs import NormalizedInput
from contracts.errors import ResolutionError

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
    Also builds a SafetyResult (mutation classification).
    Returns updated PipelineState with task_profile set.
    """
    frozen = state.frozen_binding_identity
    if frozen is None:
        raise TaskProfileAssemblyError("No FrozenBindingIdentity from S5")

    context = state.execution_context
    if context is None:
        raise TaskProfileAssemblyError("No ExecutionContext from S0")

    # Determine requires_confirmation from mutation type
    requires_confirmation = frozen.mutation_type in ("DELETE", "IRREVERSIBLE")

    # Get sanitized input for metadata
    norm_input = state.normalized_input
    if norm_input:
        clean = norm_input.sanitized_input
    else:
        clean = context.raw_input

    # Assemble TaskProfile from FrozenBindingIdentity (risk is READ from frozen, NOT recomputed)
    task_profile = TaskProfile(
        execution_id=context.request_id,
        trace_id=context.trace_id,
        binding_id=frozen.binding_id,
        capability_id=frozen.capability_id,
        kernel_op_id=frozen.kernel_op_id,
        provider=frozen.provider,
        adapter_class=frozen.adapter_class,
        effective_risk=frozen.effective_risk,
        mutation_type=frozen.mutation_type,
        estimated_cost=1,
        estimated_duration_ms=30000,
        timeout_seconds=300.0,
        retry_policy={},
        requires_confirmation=requires_confirmation,
        metadata={
            "capability_version": frozen.capability_version,
            "binding_version": frozen.binding_version,
            "policy_version": frozen.policy_version,
            "risk_policy_version": frozen.risk_policy_version,
            "authorization_version": frozen.authorization_version,
            "input_keys": list(clean.keys()) if isinstance(clean, dict) else [],
        },
    )

    logger.info(
        "S6: assembled task profile: risk=%.4f, mutation=%s, requires_confirmation=%s",
        task_profile.effective_risk,
        task_profile.mutation_type,
        task_profile.requires_confirmation,
    )

    return state.with_stage_output("S6", task_profile)
