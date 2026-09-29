"""
S7 Path Decision — decide execution path from safety assessment.

Source: FINAL_ARCHITECTURE.md §11
Owner: S7 / Path Decision
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.safety import SafetyResult, PathDecision
from contracts.stage_registry import StageOutcome

logger = logging.getLogger(__name__)


class PathDecisionError(Exception):
    """Failed to determine path decision."""
    pass


async def handle(state: PipelineState) -> PipelineState:
    """
    S7 handler: determine execution path.

    Reads task_profile and safety_result from PipelineState.
    If safety_result is not safe, cordon execution.
    Returns updated PipelineState with path_decision set.
    """
    task_profile = state.task_profile
    safety_result = state.safety_result

    if task_profile is None:
        raise PathDecisionError("No TaskProfile from S6")
    if safety_result is None:
        raise PathDecisionError("No SafetyResult from S6")

    # Cordon if safety check failed
    if not safety_result.is_safe:
        pd = PathDecision(
            decision="HALT",
            reason="Safety check failed",
            can_proceed=False,
        )
        logger.warning("S7: cordoned - safety check failed")
        return state.with_stage_output("S7", pd)

    # Standard path for safe tasks
    pd = PathDecision(
        decision="STANDARD",
        reason="Safe to proceed",
        can_proceed=True,
    )

    logger.info("S7: path decision = %s", pd.decision)
    return state.with_stage_output("S7", pd)
