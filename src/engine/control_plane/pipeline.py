"""
Pipeline engine — orchestrates the 16-stage execution pipeline (S0-S15).

Source: PIPELINE_STAGES.md, FINAL_ARCHITECTURE.md §11
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from contracts.stage_registry import (
    PIPELINE_SEQUENCE, CORDON_STAGES, StageContract,
    get_stage, get_next_stage,
)

if TYPE_CHECKING:
    from db.session import DatabaseSession

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Runtime context for pipeline execution."""
    execution_id: str
    trace_id: str
    current_stage: str = "S0"
    is_cordoned: bool = False
    cordon_reason: str | None = None
    error: str | None = None


class PipelineEngine:
    """
    Orchestrates the 16-stage execution pipeline.

    The pipeline follows the canonical sequence:
    S0 → S1 → S2 → ... → S15

    Cordon points: S7, S8, S10, S11 can short-circuit execution.
    LLM call: S2 (intent_analysis) is the only unconditional LLM call.
    """

    def __init__(self, db: "DatabaseSession", ledger: "EventLedger") -> None:
        self.db = db
        self.ledger = ledger
        self._stages: dict[str, "PipelineStage"] = {}
        self._running = False

    def register_stage(self, stage: "PipelineStage") -> None:
        """Register a stage handler."""
        self._stages[stage.stage_id] = stage
        logger.debug("Registered stage handler: %s", stage.stage_id)

    async def start(self) -> None:
        """Start the pipeline engine."""
        self._running = True
        logger.info("Pipeline engine started — %d stages registered", len(self._stages))

    async def stop(self) -> None:
        """Stop the pipeline engine."""
        self._running = False
        logger.info("Pipeline engine stopped")

    async def execute(self, execution_id: str, trace_id: str) -> PipelineContext:
        """
        Execute the full pipeline for a given execution.

        Args:
            execution_id: The execution ID
            trace_id: The trace ID

        Returns:
            PipelineContext with final state
        """
        context = PipelineContext(
            execution_id=execution_id,
            trace_id=trace_id,
        )

        logger.info("Starting pipeline execution: %s (trace: %s)", execution_id, trace_id)

        for stage_id in PIPELINE_SEQUENCE:
            if not self._running:
                context.error = "Engine stopped"
                break

            context.current_stage = stage_id
            stage_contract = get_stage(stage_id)

            logger.info("Executing stage %s: %s", stage_id, stage_contract.display_name)

            # Emit stage start event
            await self.ledger.emit(
                event_type="STAGE_STARTED",
                execution_id=execution_id,
                trace_id=trace_id,
                stage=stage_id,
                actor_type="system",
                actor_id="pipeline_engine",
            )

            # Check for cordon
            if stage_id in CORDON_STAGES:
                should_cordon, reason = await self._check_cordon(context, stage_id)
                if should_cordon:
                    context.is_cordoned = True
                    context.cordon_reason = reason
                    logger.warning("Cordon at %s: %s", stage_id, reason)

                    # Determine outcome based on cordon stage
                    if stage_id == "S7":
                        context.error = f"Path routing failed: {reason}"
                    elif stage_id == "S8":
                        context.error = f"Safety gate rejected: {reason}"
                    elif stage_id == "S10":
                        context.error = f"Confirmation denied: {reason}"
                    elif stage_id == "S11":
                        context.error = f"Authorization failed: {reason}"

                    break

            # Execute stage
            stage_handler = self._stages.get(stage_id)
            if stage_handler:
                try:
                    result = await stage_handler.execute(context)
                    context = result
                except Exception as e:
                    logger.error("Stage %s failed: %s", stage_id, e)
                    context.error = str(e)
                    break
            else:
                logger.debug("No handler for stage %s — passing through", stage_id)

            # Emit stage complete event
            await self.ledger.emit(
                event_type="STAGE_COMPLETED",
                execution_id=execution_id,
                trace_id=trace_id,
                stage=stage_id,
                actor_type="system",
                actor_id="pipeline_engine",
            )

        # Emit pipeline complete event
        await self.ledger.emit(
            event_type="PIPELINE_COMPLETED",
            execution_id=execution_id,
            trace_id=trace_id,
            stage=context.current_stage,
            actor_type="system",
            actor_id="pipeline_engine",
            payload={
                "is_cordoned": context.is_cordoned,
                "cordon_reason": context.cordon_reason,
                "error": context.error,
            },
        )

        logger.info(
            "Pipeline execution complete: %s (cordoned=%s, error=%s)",
            execution_id, context.is_cordoned, context.error,
        )
        return context

    async def _check_cordon(self, context: PipelineContext, stage_id: str) -> tuple[bool, str | None]:
        """
        Check if execution should be cordoned at this stage.

        Returns:
            (should_cordon, reason)
        """
        # Placeholder — will be implemented per stage
        return False, None


# ---------------------------------------------------------------------------
# Stage Handler Base Class
# ---------------------------------------------------------------------------

class PipelineStage:
    """
    Base class for pipeline stage handlers.

    Each stage implementation extends this and implements execute().
    """

    stage_id: str = "S0"
    stage_name: str = "base"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute this stage. Override in subclasses."""
        return context
