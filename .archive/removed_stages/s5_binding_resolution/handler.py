"""
S5 Binding Resolution — resolve task to capability binding, compute risk.

Source: FINAL_ARCHITECTURE.md §11, §22
Owner: S5 / Binding Resolution
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.stage_registry import StageOutcome

logger = logging.getLogger(__name__)


class BindingResolutionError(Exception):
    """Failed to resolve capability binding."""
    pass


async def handle(state: PipelineState) -> PipelineState:
    """
    S5 handler: resolve task to capability binding.

    Reads PipelineState (intent, context from S4).
    Produces FrozenBindingIdentity — the authoritative risk/mutation classification.
    THIS IS THE ONE AND ONLY SOURCE OF effective_risk AND mutation_type.
    Returns updated PipelineState with frozen_binding_identity set.
    """
    # In real implementation, resolve from capability registry
    frozen = FrozenBindingIdentity(
        binding_id=f"binding-{state.execution_context.request_id[:12]}",
        capability_id="default-capability",
        kernel_op_id="default-kernel-op",
        provider="local",
        adapter_class="DefaultAdapter",
        effective_risk=0.1,
        mutation_type="READ",
        capability_version="1.0.0",
        binding_version="1.0.0",
        policy_version="1.0.0",
        requires_confirmation=False,
        immutable=True,
    )

    logger.info(
        "S5: resolved binding %s: risk=%.4f, mutation=%s",
        frozen.binding_id,
        frozen.effective_risk,
        frozen.mutation_type,
    )

    return state.with_stage_output("S5", frozen)
