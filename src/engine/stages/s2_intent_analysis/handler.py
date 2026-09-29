"""
S2 Intent Analysis — the ONLY unconditional LLM call.

Decomposes user intent into structured IntentResult.
Max 2 attempts: primary + retry.

Source: FINAL_ARCHITECTURE.md §11, §12
Owner: S2 / Intent Analysis
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from contracts.pipeline_state import PipelineState
from contracts.errors import SuprAgentsError
from contracts.stage_outputs import IntentResult
from contracts.stage_registry import StageStatus

#: intent_type values that end the run at S2 (vocabulary pending an owner ruling id).
INTENT_UNKNOWN = "unknown"
INTENT_PROHIBITED = "prohibited"

logger = logging.getLogger(__name__)


class IntentAnalysisError(SuprAgentsError):
    """Failed to analyze intent."""
    def __init__(self, message: str, attempt: int = 0) -> None:
        super().__init__(message, code="INTENT_ANALYSIS_ERROR")
        self.attempt = attempt


class LLMProvider:
    """Interface for LLM providers."""

    async def analyze_intent(self, sanitized_input: dict) -> IntentResult:
        """Analyze intent from sanitized input."""
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """Mock LLM provider that returns simple heuristic-based intent analysis."""

    async def analyze_intent(self, sanitized_input: dict) -> IntentResult:
        """Produce a simple IntentResult from input heuristics."""
        text = str(sanitized_input.get("text", "") or "").lower()
        params = {k: v for k, v in sanitized_input.items() if k != "text"}

        if any(w in text for w in ("list", "get", "show", "find", "search", "query")):
            intent_type = "read"
            operations = ["query"]
        elif any(w in text for w in ("create", "add", "new", "insert", "post")):
            intent_type = "write"
            operations = ["create"]
        elif any(w in text for w in ("update", "modify", "change", "edit")):
            intent_type = "write"
            operations = ["update"]
        elif any(w in text for w in ("delete", "remove")):
            intent_type = "delete"
            operations = ["delete"]
        else:
            intent_type = "unknown"
            operations = ["query"]

        is_workflow = "then" in text or "after" in text or bool(params.get("steps"))

        return IntentResult(
            intent_type=intent_type,
            target_entities=params.get("targets", ["default"]),
            operations=operations,
            parameters=params,
            is_workflow=is_workflow,
            confidence=0.8 if intent_type != "unknown" else 0.3,
            raw_llm_output=f"[mock] intent_type={intent_type}, ops={operations}",
        )


async def handle(state: PipelineState, llm: LLMProvider) -> PipelineState:
    """
    S2 handler: call LLM (via provider) to analyze intent.

    Max 2 attempts. Never delegates this responsibility.
    Returns updated PipelineState with IntentResult set.
    """
    context = state.execution_context
    norm = state.normalized_input
    sanitized = norm.sanitized_input if norm else {}

    last_error = None
    result = None

    for attempt in range(1, 3):
        try:
            result = await llm.analyze_intent(sanitized)
            result = IntentResult(
                intent_type=result.intent_type,
                target_entities=result.target_entities,
                operations=result.operations,
                parameters=result.parameters,
                is_workflow=result.is_workflow,
                confidence=result.confidence,
                raw_llm_output=result.raw_llm_output,
                attempt=attempt,
            )
            logger.info("S2 intent analysis succeeded on attempt %d: %s", attempt, result.intent_type)
            break
        except Exception as e:
            last_error = str(e)
            logger.warning("S2 intent analysis attempt %d failed: %s", attempt, e)
            if attempt == 1:
                continue
            raise IntentAnalysisError(
                f"Intent analysis failed after 2 attempts: {last_error}",
                attempt=attempt,
            )

    if result is None:
        raise IntentAnalysisError("Intent analysis returned no result")

    state = state.replace_context("S2", task_id=str(uuid.uuid4()))  # R-M
    state = state.with_stage_output("S2", result)
    if result.intent_type == INTENT_PROHIBITED:
        return state.with_status(StageStatus.DENY, "intent_prohibited")
    if result.intent_type == INTENT_UNKNOWN:
        return state.with_status(StageStatus.CLARIFY, "intent_unclear")
    return state
