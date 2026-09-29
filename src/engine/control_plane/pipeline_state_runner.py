"""
PipelineState-backed pipeline runner for S0–S11.

Each stage receives a PipelineState and returns an updated PipelineState.
ExecutionContext is never mutated after S0 creation — it is read-only
within the PipelineState accumulator.

Source: DATA_CONTRACTS.md §2, PIPELINE_STAGES.md §11
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from contracts.stage_registry import (
    PIPELINE_SEQUENCE, CORDON_STAGES, StageContract,
    get_stage, get_next_stage, StageOutcome, StageStatus,
)
from contracts.execution_context import ExecutionContext
from contracts.pipeline_state import PipelineState, STAGE_OUTPUT_FIELD

logger = logging.getLogger(__name__)

# Type for PipelineState handlers: (PipelineState) -> PipelineState
HandlerFunc = Callable[[PipelineState], PipelineState]


@dataclass
class PipelineRunResult:
    """Result of running the S0–S11 pipeline."""
    final_state: PipelineState
    final_stage: str
    outcome: StageOutcome
    status: StageStatus | None = None
    error: str | None = None
    cordon_stage: str | None = None
    cordon_reason: str | None = None
    failed_check: str | None = None
    duration_ms: float = 0.0


class PipelineRunner:
    """
    Executes the S0–S11 pipeline using PipelineState as the accumulator.

    Each stage receives PipelineState, returns updated PipelineState.
    ExecutionContext is never mutated after S0 creation.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerFunc] = {}
        self._running = False

    def register_handler(self, stage_id: str, handler_func: HandlerFunc) -> None:
        """Register a PipelineState-based stage handler."""
        if stage_id not in STAGE_OUTPUT_FIELD:
            raise KeyError(f"Unknown stage: {stage_id}")
        self._handlers[stage_id] = handler_func
        logger.debug("Registered handler for %s", stage_id)

    async def run(self, entry_request: Any) -> PipelineRunResult:
        """
        Run the S0–S11 pipeline from an entry request.

        Args:
            entry_request: EntryRequest or dict with raw_payload, tenant_id, etc.

        Returns:
            PipelineRunResult with final state and outcome
        """
        start_time = time.monotonic()

        # S0: Create initial ExecutionContext
        import dataclasses

        initial_ec = ExecutionContext(
            trace_id="",
            request_id="",
            tenant_id=getattr(entry_request, 'tenant_id', ''),
            user_id=getattr(entry_request, 'user_id', '') or 'system',
            workspace_id=getattr(entry_request, 'tenant_id', ''),
            conversation_id=getattr(entry_request, 'conversation_id', None),
            connection_id=getattr(entry_request, 'connection_id', None),
        )

        state = PipelineState(execution_context=initial_ec)
        outcome = StageOutcome.CONTINUE
        stage_status = StageStatus.NORMAL
        cordon_stage = None
        cordon_reason = None
        failed_check = None
        final_stage = "S0"
        error = None

        for stage_id in PIPELINE_SEQUENCE[:12]:  # S0 through S11
            if not self._running:
                break

            final_stage = stage_id
            stage_contract = get_stage(stage_id)
            logger.info("Executing %s: %s", stage_id, stage_contract.display_name)

            # Execute stage handler if registered
            handler = self._handlers.get(stage_id)
            if handler:
                try:
                    state = handler(state)
                except Exception as e:
                    logger.error("Stage %s failed: %s", stage_id, e)
                    outcome = StageOutcome.FAILED
                    stage_status = StageStatus.ERROR
                    error = str(e)
                    break

            # Check cordon outcomes
            if stage_id in CORDON_STAGES:
                cordon = self._check_cordon(state, stage_id)
                if cordon:
                    failed_check = cordon.get("failed_check")
                    cordon_reason = cordon.get("reason")
                    outcome = self._map_status_to_outcome(StageStatus.DENY)
                    stage_status = StageStatus.DENY
                    cordon_stage = stage_id
                    logger.warning(
                        "Cordon at %s: %s (check: %s)",
                        stage_id, cordon_reason, failed_check,
                    )
                    break

        duration_ms = (time.monotonic() - start_time) * 1000

        return PipelineRunResult(
            final_state=state,
            final_stage=final_stage,
            outcome=outcome,
            status=stage_status,
            error=error,
            cordon_stage=cordon_stage,
            cordon_reason=cordon_reason,
            failed_check=failed_check,
            duration_ms=duration_ms,
        )

    def _check_cordon(self, state: PipelineState, stage_id: str) -> dict | None:
        """Check if execution should be cordoned at this stage."""
        if stage_id == "S7":
            pd = state.path_decision
            if pd and hasattr(pd, 'can_proceed'):
                if not pd.can_proceed:
                    return {"failed_check": "path_routing", "reason": pd.reason}
        elif stage_id == "S8":
            sr = state.safety_result
            if sr and hasattr(sr, 'allowed'):
                if not sr.allowed:
                    return {"failed_check": sr.failed_check, "reason": sr.reason or "safety gate denied"}
        elif stage_id == "S10":
            conf = state.confirmation
            if conf and hasattr(conf, 'status'):
                if conf.status in ("rejected", "expired"):
                    return {"failed_check": "confirmation_" + conf.status, "reason": f"Confirmation {conf.status}"}
        elif stage_id == "S11":
            vr = state.validation_result
            if vr and hasattr(vr, 'is_valid'):
                if not vr.is_valid:
                    return {"failed_check": vr.failed_check, "reason": vr.reason or "Plan validation failed"}
        return None

    def _map_status_to_outcome(self, status: StageStatus) -> StageOutcome:
        """Map StageStatus to StageOutcome for the pipeline runner."""
        mapping = {
            StageStatus.NORMAL: StageOutcome.CONTINUE,
            StageStatus.CLARIFY: StageOutcome.DELEGATE,
            StageStatus.DENY: StageOutcome.CORDON,
            StageStatus.ERROR: StageOutcome.FAILED,
            StageStatus.PROBE: StageOutcome.RETRY,
        }
        return mapping.get(status, StageOutcome.FAILED)

    async def start(self) -> None:
        """Start the pipeline runner."""
        self._running = True
        logger.info("PipelineRunner started")

    async def stop(self) -> None:
        """Stop the pipeline runner."""
        self._running = False
        logger.info("PipelineRunner stopped")
