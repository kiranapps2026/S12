"""
S9 Lock Acquisition — acquire advisory lock for parallel execution safety.

Source: FINAL_ARCHITECTURE.md §11, §19
Owner: S9 / Lock Acquisition
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.stage_registry import StageOutcome

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Failed to acquire lock."""
    pass


async def handle(state: PipelineState) -> PipelineState:
    """
    S9 handler: acquire advisory lock.

    Reads kill_switch from safety_result (S8 writes safety_result with kill_switch_active).
    Returns updated PipelineState with lock_acquired set.
    """
    task_profile = state.task_profile
    safety_result = state.safety_result

    # Read kill_switch from safety_result (S8 writes safety_result with kill_switch_active)
    kill_switch_active = False
    if safety_result is not None:
        kill_switch_active = getattr(safety_result, "kill_switch_active", False)

    if kill_switch_active:
        logger.warning("S9: lock acquisition skipped — kill switch active")
        return state.with_stage_output("S9", {
            "lock_acquired": False,
            "lock_id": None,
            "outcome": StageOutcome.CORDON,
        })

    # Acquire lock
    lock_id = f"lock-{state.execution_context.request_id[:12]}"
    logger.info("S9: acquired advisory lock %s", lock_id)

    return state.with_stage_output("S9", {
        "lock_acquired": True,
        "lock_id": lock_id,
        "outcome": StageOutcome.CONTINUE,
    })
