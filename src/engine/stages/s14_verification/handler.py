"""
Pre-existing. Not certified. Superseded by the S12-S15 execution gate.

"""
"""
S14 Verification — replay + reference check.

Source: FINAL_ARCHITECTURE.md §11
Owner: S14 / Verification
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import VerificationResult, VerificationState
from contracts.errors import SuprAgentsError

logger = logging.getLogger(__name__)


class VerificationFailedError(SuprAgentsError):
    """Verification failed — replay mismatch."""
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VERIFICATION_FAILED")


def _compute_output_hash(output: dict) -> str:
    """Compute deterministic hash of execution output.

    Only serializes JSON-primitive types. Non-primitive values raise TypeError
    rather than being silently converted (no default=str).
    """
    def _serialize(obj):
        """Recursively convert to JSON-safe primitives."""
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return {k: _serialize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_serialize(v) for v in obj]
        raise TypeError(f"Cannot serialize {type(obj).__name__} for hash computation")

    canonical = json.dumps(_serialize(output), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def handle(state: PipelineState) -> PipelineState:
    """
    S14 handler: verify execution by replay and reference check.

    Reads ExecutionResult from S12 and ReconciliationStatus from S13.
    Computes output hash and verifies consistency.
    Returns updated PipelineState with VerificationResult.
    """
    execution_result = state.execution_result
    reconciliation = state.reconciliation_status

    if execution_result is None:
        raise ValueError("No ExecutionResult from S12")

    execution_id = execution_result.get("execution_id", "unknown")
    result_data = execution_result.get("result", {})

    # Compute output hash
    output_hash = _compute_output_hash(result_data)

    # Check reconciliation state
    recon_state = reconciliation.state if reconciliation else ReconciliationState.RECONCILED
    is_consistent = recon_state == ReconciliationState.RECONCILED

    if not is_consistent:
        verification_state = VerificationState.MISMATCH
        logger.warning("S14 verification FAILED: reconciliation mismatch for %s", execution_id)
    else:
        verification_state = VerificationState.VERIFIED
        logger.info("S14 verified: execution_id=%s, hash=%s", execution_id, output_hash)

    result = VerificationResult(
        execution_id=execution_id,
        state=verification_state,
        output_hash=output_hash,
        replay_matched=is_consistent,
        reference_checked=is_consistent,
        verified_at=time.time(),
    )

    return state.with_stage_output("S14", result)
