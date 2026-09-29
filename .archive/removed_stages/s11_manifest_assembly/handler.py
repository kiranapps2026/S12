"""
S11 Execution Manifest Assembly — freeze execution plan into immutable manifest.

CRITICAL: S11 assembles the ExecutionManifest from all prior Frozen artifacts.
This manifest is the authoritative execution specification consumed by S12.

Source: FINAL_ARCHITECTURE.md §13, §38
Owner: S11 / Execution Manifest
"""

from __future__ import annotations

import hashlib
import logging

from contracts.pipeline_state import PipelineState
from contracts.execution_manifest import ExecutionManifest
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.stage_registry import StageOutcome

logger = logging.getLogger(__name__)


class ManifestAssemblyError(Exception):
    """Failed to assemble execution manifest."""
    pass


def _compute_plan_hash(state: PipelineState) -> str:
    """Compute SHA-256 hash of the execution plan for manifest anchoring."""
    import json

    plan_data = {
        "capability_id": state.frozen_binding_identity.capability_id
        if state.frozen_binding_identity else None,
        "effective_risk": state.frozen_binding_identity.effective_risk
        if state.frozen_binding_identity else 0.0,
        "mutation_type": state.frozen_binding_identity.mutation_type
        if state.frozen_binding_identity else "READ",
        "intent": state.execution_context.intent,
        "path_plan": getattr(state, "path_plan", None),
    }
    return hashlib.sha256(
        json.dumps(plan_data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


async def handle(state: PipelineState) -> PipelineState:
    """
    S11 handler: assemble ExecutionManifest from all prior Frozen artifacts.

    Reads FrozenBindingIdentity from PipelineState (S5 output).
    Assembles ExecutionManifest — frozen, immutable, consumed by S12.
    Returns updated PipelineState with execution_manifest set.
    """
    frozen = state.frozen_binding_identity
    if frozen is None:
        raise ManifestAssemblyError("No FrozenBindingIdentity from S5")

    context = state.execution_context
    task_profile = state.task_profile

    plan_hash = _compute_plan_hash(state)

    manifest = ExecutionManifest(
        execution_id=context.request_id,
        trace_id=context.trace_id,
        plan_hash=plan_hash,
        capability_version=frozen.capability_version,
        binding_version=frozen.binding_version,
        policy_version=frozen.policy_version,
        risk_policy_version="1.0.0",
        authorization_version="1.0.0",
        worker_runtime_version="1.0.0",
        model_version="1.0.0",
        created_at=context.created_at,
    )

    logger.info(
        "S11 assembled manifest: plan_hash=%s, risk=%.4f, mutation=%s",
        manifest.plan_hash,
        frozen.effective_risk,
        frozen.mutation_type,
    )

    return state.with_stage_output("S11", manifest)
