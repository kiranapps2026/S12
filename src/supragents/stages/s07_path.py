"""S7 Path Routing: first matching row of the routing table wins (PIPELINE_STAGES §9).

The deny threshold comes from the live kernel policy, never from the request.
AGENTIC is reserved for M2: complex graphs are routed to CLARIFY.
"""
from __future__ import annotations

from types import MappingProxyType

from supragents.contracts.outputs import PathRouting, TaskProfile
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import GraphType, PathDecision, StageStatus
from supragents.pipeline.deps import PipelineDeps

STAGE = "S7"
MIN_CONFIDENCE = 0.5
FAST_CONFIDENCE = 0.9
FAST_MAX_RISK = 0.3
WORKFLOW_CONFIDENCE = 0.7
_STOP_STATUS = MappingProxyType({
    PathDecision.CLARIFY: StageStatus.CLARIFY,
    PathDecision.DENY: StageStatus.DENY,
})


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    try:
        policy = await deps.policy.current(state.execution_context.tenant_id)
        threshold = policy.risk_deny_threshold
    except Exception:
        return state.halted(STAGE, StageStatus.DENY, "policy_unavailable")
    decision, reason = route(state.task_profile, state.intent_result.confidence, threshold)
    state = state.with_output(STAGE, path_routing=PathRouting(decision=decision, reason=reason))
    stop = _STOP_STATUS.get(decision)
    return state if stop is None else state.halted(STAGE, stop, reason)


def route(profile: TaskProfile, confidence: float, threshold: float) -> tuple[PathDecision, str | None]:
    if not 0.0 < threshold <= 1.0:
        return PathDecision.DENY, "risk_threshold_invalid"
    if profile.risk >= threshold:
        return PathDecision.DENY, "risk_above_threshold"
    if confidence < MIN_CONFIDENCE:
        return PathDecision.CLARIFY, "low_confidence"
    if profile.graph_type is GraphType.COMPLEX:
        return PathDecision.CLARIFY, "complex_not_supported"
    if (profile.graph_type is GraphType.SIMPLE and confidence >= FAST_CONFIDENCE
            and profile.risk <= FAST_MAX_RISK):
        return PathDecision.FAST, None
    if confidence >= WORKFLOW_CONFIDENCE:
        return PathDecision.WORKFLOW, None
    return PathDecision.CLARIFY, "uncertain_intent"
