"""
S7 Path Decision -- route execution path per R-Q 9-row table.

Source: FINAL_ARCHITECTURE.md section 11, PIPELINE_STAGES.md section 9, R-Q
Owner: S7 / Path Decision
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from contracts.pipeline_state import PipelineState
from contracts.safety import TaskProfile, PathDecision, PathRoutingResult
from contracts.stage_outputs import IntentResult, GraphAnalysis
from contracts.kernel_policy import KernelPolicy
from contracts.stage_registry import StageStatus

logger = logging.getLogger(__name__)


async def handle(state: PipelineState, policy: KernelPolicy | None = None) -> PipelineState:
    """
    S7 handler: route execution path per R-Q 9-row table.

    Evaluates conditions in priority order; first match wins.
    Reads IntentResult (S2), GraphAnalysis (S4), TaskProfile (S6), KernelPolicy.

    Returns updated PipelineState with PathRoutingResult.
    """
    task_profile = state.task_profile
    intent_result = state.intent_result
    graph_analysis = state.graph_analysis
    frozen = state.frozen_binding_identity

    if task_profile is None:
        raise PathDecisionError("No TaskProfile from S6")
    if intent_result is None:
        raise PathDecisionError("No IntentResult from S2")
    if graph_analysis is None:
        raise PathDecisionError("No GraphAnalysis from S4")
    if frozen is None:
        raise PathDecisionError("No FrozenBindingIdentity from S5")

    # Risk threshold comes from KernelPolicy only; no default (R-Q row 1).
    risk_deny_threshold = getattr(policy, "risk_deny_threshold", None)

    risk = frozen.effective_risk
    confidence = intent_result.confidence if isinstance(intent_result, IntentResult) else 1.0
    graph_complexity = graph_analysis.complexity if isinstance(graph_analysis, GraphAnalysis) else "simple"
    steps = max(1, len(graph_analysis.execution_steps)) if isinstance(graph_analysis, GraphAnalysis) and graph_analysis.execution_steps else 1
    distinct_caps = graph_analysis.candidate_count if isinstance(graph_analysis, GraphAnalysis) else (
        len(set(task_profile.capabilities)) if task_profile.capabilities else 0
    )

    # R-Q: 9-row table -- evaluate in priority order, first match wins
    if not isinstance(risk_deny_threshold, (int, float)) or risk_deny_threshold < 0:
        decision = PathDecision.DENY
        reason = "risk_threshold_unavailable"
    elif risk > risk_deny_threshold:
        decision = PathDecision.DENY
        reason = "risk_above_threshold"
    elif distinct_caps == 0:
        decision = PathDecision.CLARIFY
        reason = "no_capability"
    elif distinct_caps > 1:
        decision = PathDecision.CLARIFY
        reason = "multi_capability_not_supported"
    elif confidence is None or confidence < 0.5:
        decision = PathDecision.CLARIFY
        reason = "low_confidence"
    elif graph_complexity == "complex" or steps >= 6:
        decision = PathDecision.CLARIFY
        reason = "complex_not_supported"
    elif (graph_complexity == "simple"
          and steps == 1
          and confidence >= 0.9
          and risk <= 0.3):
        decision = PathDecision.FAST
        reason = None
    elif graph_complexity in ("simple", "chain") and 1 <= steps <= 5 and confidence >= 0.7:
        decision = PathDecision.WORKFLOW
        reason = None
    else:
        decision = PathDecision.CLARIFY
        reason = "unmatched_route"

    if reason:
        logger.info("S7: %s [%s] -- risk=%.4f", decision.value, reason, risk)
    else:
        logger.info("S7: %s -- risk=%.4f", decision.value, risk)

    state = state.with_stage_output("S7", PathRoutingResult(decision=decision, reason=reason))
    if decision is PathDecision.DENY:
        return state.with_status(StageStatus.DENY, reason)
    if decision is PathDecision.CLARIFY:
        return state.with_status(StageStatus.CLARIFY, reason)
    return state


class PathDecisionError(Exception):
    """Failed to determine path decision."""
    pass
