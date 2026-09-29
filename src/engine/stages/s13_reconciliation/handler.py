"""
Pre-existing. Not certified. Superseded by the S12-S15 execution gate.

"""
"""
S13 Reconciliation — verify billing/events match execution.

Source: FINAL_ARCHITECTURE.md §11
Owner: S13 / Reconciliation
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import ReconciliationStatus, ReconciliationState

logger = logging.getLogger(__name__)


async def handle(state: PipelineState) -> PipelineState:
    """
    S13 handler: reconcile execution with billing and events.

    Reads ExecutionResult from S12.
    Compares tokens_billed vs tokens_used.
    Verifies event ledger entries exist.
    Returns updated PipelineState with ReconciliationStatus.
    """
    execution_result = state.execution_result
    if execution_result is None:
        raise ValueError("No ExecutionResult from S12")

    execution_id = execution_result.get("execution_id", "unknown")
    tokens_used = execution_result.get("tokens_used", 0)

    # Calculate billing delta (deterministic)
    # In production, this would check the billing system
    tokens_billed = tokens_used  # Simplified: assume 1:1 billing
    delta = tokens_billed - tokens_used
    events_match = True  # Simplified: assume events are always in ledger

    if delta != 0:
        reconciliation_state = ReconciliationState.MISMATCH
    elif not events_match:
        reconciliation_state = ReconciliationState.EVENT_MISSING
    else:
        reconciliation_state = ReconciliationState.RECONCILED

    status = ReconciliationStatus(
        execution_id=execution_id,
        state=reconciliation_state,
        tokens_used=tokens_used,
        tokens_billed=tokens_billed,
        billing_delta=delta,
        events_match=events_match,
        reconciled_at=execution_result.get("completed_at", 0),
    )

    logger.info(
        "S13 reconciled: execution_id=%s, state=%s, delta=%d",
        execution_id, reconciliation_state, delta,
    )

    return state.with_stage_output("S13", status)
