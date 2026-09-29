"""
Pre-existing. Not certified. Superseded by the S12-S15 execution gate.

"""
"""
S15 Final State — write final state to event ledger.

Source: FINAL_ARCHITECTURE.md §11
Owner: S15 / Final State
"""

from __future__ import annotations

import logging
import time

from contracts.pipeline_state import PipelineState
from contracts.stage_registry import StageOutcome
from contracts.stage_outputs import FinalState, FinalStateEnum

logger = logging.getLogger(__name__)


async def handle(state: PipelineState) -> PipelineState:
    """
    S15 handler: determine and write final state.

    Reads VerificationResult from S14.
    Determines final state: SUCCESS, PARTIAL, FAILED.
    Writes final state to event ledger.
    Returns updated PipelineState with FinalState.
    """
    verification = state.verification_result
    reconciliation = state.reconciliation_status
    execution_result = state.execution_result

    if verification is None:
        raise ValueError("No VerificationResult from S14")

    # Determine final state
    if verification.state.value == "verified" and reconciliation and reconciliation.state.value == "reconciled":
        final_state = FinalStateEnum.SUCCESS
    elif verification.state.value == "verified":
        final_state = FinalStateEnum.PARTIAL
    else:
        final_state = FinalStateEnum.FAILED

    execution_id = verification.execution_id

    result = FinalState(
        execution_id=execution_id,
        state=final_state,
        completed_at=time.time(),
        duration_ms=execution_result.get("duration_ms", 0) if execution_result else 0,
        tokens_used=execution_result.get("tokens_used", 0) if execution_result else 0,
    )

    logger.info(
        "S15 final state: execution_id=%s, state=%s",
        execution_id, final_state,
    )

    return state.with_stage_output("S15", result)
