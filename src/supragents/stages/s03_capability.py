"""S3 Capability Discovery: map the intent to one production-enabled capability.

Candidates come from the registry only; nothing in the request or the LLM output can
supply a capability or its risk metadata.
"""
from __future__ import annotations

from supragents.contracts.outputs import CapabilityMatch
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus, TruthState
from supragents.pipeline.deps import PipelineDeps

STAGE = "S3"


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    candidates = await deps.registry.capabilities_for_intent(
        state.execution_context.tenant_id, state.intent_result.intent
    )
    if not candidates:
        return state.halted(STAGE, StageStatus.CLARIFY, "no_capability")
    enabled = [c for c in candidates if c.truth_state is TruthState.PRODUCTION_ENABLED]
    if not enabled:
        return state.halted(STAGE, StageStatus.CLARIFY, "capability_not_enabled")
    if len(enabled) > 1:
        return state.halted(STAGE, StageStatus.CLARIFY, "ambiguous_capability")
    return state.with_output(STAGE, capability_match=CapabilityMatch(capability=enabled[0]))
