"""
S10 Kill Switch — set kill switch flag based on safety assessment.

Source: FINAL_ARCHITECTURE.md §11, §17
Owner: S10 / Kill Switch
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.stage_registry import StageOutcome

logger = logging.getLogger(__name__)


async def handle(state: PipelineState) -> PipelineState:
    """
    S10 handler: set kill switch flag.

    Reads safety_result from PipelineState.safety_result (written by S8).
    Returns updated PipelineState with kill_switch set.
    """
    safety_result = state.safety_result

    kill_switch_active = False
    if safety_result is not None:
        kill_switch_active = getattr(safety_result, "kill_switch_active", False)

    if kill_switch_active:
        logger.warning("S10: kill switch is ACTIVE — execution cordoned")
    else:
        logger.info("S10: kill switch is inactive")

    return state.with_stage_output("S10", {
        "kill_switch": kill_switch_active,
        "outcome": StageOutcome.CORDON if kill_switch_active else StageOutcome.CONTINUE,
    })
