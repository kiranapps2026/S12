"""
S2 Intent Analysis — the ONLY LLM call.

Source: FINAL_ARCHITECTURE.md §11, §12, PIPELINE_STAGES.md §4
Owner: S2 / Intent Analysis

The model is given the registry's known intents and answers with JSON. That answer is
UNTRUSTED: it becomes an IntentResult only after validation (a known intent, "unknown" or
"prohibited"; a numeric confidence in [0, 1]; a JSON-object `parameters`). An invalid
answer is retried once with the reason as feedback; still invalid -> CLARIFY
`intent_unparseable`. The model can only narrow what happens (unknown -> CLARIFY,
prohibited -> DENY); it cannot add a capability, change risk or mutation.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from contracts.capability import CapabilityRegistry
from contracts.errors import DependencyUnavailable
from contracts.intent_model import IntentModel
from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import IntentResult
from contracts.stage_registry import StageStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
INTENT_UNKNOWN = "unknown"
INTENT_PROHIBITED = "prohibited"
_INTENT_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
MAX_ITEMS = 50


def _request_text(sanitized: Any) -> str | None:
    """The user's text from the sanitized payload ("message" or "text"); None if absent."""
    if isinstance(sanitized, str):
        return sanitized.strip() or None
    if isinstance(sanitized, dict):
        for key in ("message", "text"):
            value = sanitized.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _parse(raw: str, allowed: frozenset[str]) -> tuple[dict | None, str | None]:
    """Return (validated answer, None) or (None, feedback for the retry)."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, "response is not valid JSON"
    if not isinstance(data, dict):
        return None, "response must be a JSON object"
    intent = data.get("intent")
    if not isinstance(intent, str) or not _INTENT_NAME.match(intent):
        return None, "intent must be a lowercase identifier"
    if intent not in allowed:
        return None, f"intent must be one of the allowed values, not {intent!r}"
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, "confidence must be a number"
    if not 0.0 <= confidence <= 1.0:
        return None, "confidence must be between 0 and 1"
    if not isinstance(data.get("parameters", {}), dict):
        return None, "parameters must be a JSON object"
    return data, None


async def handle(state: PipelineState, model: IntentModel | None,
                 registry: CapabilityRegistry | None) -> PipelineState:
    """S2 handler. Returns the state with intent_result and task_id, or a stopped state."""
    ctx, norm = state.execution_context, state.normalized_input
    if ctx is None or norm is None:
        raise ValueError("S2 requires S0 and S1 outputs")
    if model is None or registry is None:
        return state.with_status(StageStatus.ERROR, "llm_unavailable")

    text = _request_text(norm.sanitized_input)
    if text is None:
        return state.with_status(StageStatus.CLARIFY, "missing_text")

    known = tuple(await registry.known_intents(ctx.tenant_id))
    allowed = frozenset((*known, INTENT_UNKNOWN, INTENT_PROHIBITED))

    feedback: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            completion = await model.complete(text, known, feedback)
        except DependencyUnavailable as exc:      # the provider is down / out of credit / refusing: expected
            logger.warning("S2: intent model unavailable (%s)", exc)   # one line, no traceback
            return state.with_status(StageStatus.ERROR, "llm_unavailable")
        except Exception:  # noqa: BLE001 — fail closed; an unexpected failure keeps its traceback
            logger.exception("S2: intent model call failed unexpectedly")
            return state.with_status(StageStatus.ERROR, "llm_unavailable")
        parsed, feedback = _parse(completion.text, allowed)
        if parsed is None:
            logger.warning("S2 attempt %d rejected: %s", attempt, feedback)
            continue

        params = dict(parsed.get("parameters", {}))
        items = params.get("items")
        result = IntentResult(
            intent_type=parsed["intent"],
            target_entities=(),
            operations=(parsed["intent"],),
            parameters=params,
            is_workflow=isinstance(items, list) and len(items) > 1,
            confidence=float(parsed["confidence"]),
            raw_llm_output=completion.text,
            attempt=attempt,
        )
        state = state.replace_context("S2", task_id=str(uuid.uuid4()))  # R-M
        state = state.with_stage_output("S2", result)
        if result.intent_type == INTENT_PROHIBITED:
            return state.with_status(StageStatus.DENY, "intent_prohibited")
        if result.intent_type == INTENT_UNKNOWN:
            return state.with_status(StageStatus.CLARIFY, "intent_unclear")
        return state

    return state.with_status(StageStatus.CLARIFY, "intent_unparseable")
