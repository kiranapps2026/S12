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
from contracts.stage_outputs import IntentResult, IntentStep
from contracts.stage_registry import StageStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
INTENT_UNKNOWN = "unknown"
INTENT_PROHIBITED = "prohibited"
_INTENT_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
MAX_ITEMS = 50
MAX_PLAN_STEPS = 5              # R-AC: at most 5 steps in a multi-capability plan, items included
MAX_STEP_PARAMETER_CHARS = 2000  # R-AE: per step, as JSON
TOO_MANY_STEPS = "too_many_steps"


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


def _valid_parameters(value: Any, bounded: bool) -> str | None:
    """None if `value` is acceptable step parameters, else the feedback for the retry. The size
    cap (R-AE) applies to the parameters a multi-step plan binds and shows, not to a single intent."""
    if not isinstance(value, dict):
        return "parameters must be a JSON object"
    if not bounded:
        return None
    try:
        size = len(json.dumps(value))
    except (TypeError, ValueError, RecursionError):
        return "parameters must be plain JSON"
    if size > MAX_STEP_PARAMETER_CHARS:
        return f"parameters must be at most {MAX_STEP_PARAMETER_CHARS} characters"
    return None


def _parse(raw: str, allowed: frozenset[str]) -> tuple[dict | None, str | None]:
    """Return (validated answer, None) or (None, feedback for the retry).

    The validated answer always has `steps`: a list of {"intent", "parameters"} (a lone
    top-level intent becomes one step) and `confidence`."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, "response is not valid JSON"
    if not isinstance(data, dict):
        return None, "response must be a JSON object"
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, "confidence must be a number"
    if not 0.0 <= confidence <= 1.0:
        return None, "confidence must be between 0 and 1"

    if "steps" in data:
        raw_steps = data["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            return None, "steps must be a non-empty list"
        if len(raw_steps) > MAX_PLAN_STEPS + 1:      # far too many: no need to look at each one
            raw_steps = raw_steps[:MAX_PLAN_STEPS + 1]
    else:
        raw_steps = [{"intent": data.get("intent"), "parameters": data.get("parameters", {})}]

    steps = []
    for entry in raw_steps:
        if not isinstance(entry, dict):
            return None, "each step must be a JSON object"
        intent = entry.get("intent")
        if not isinstance(intent, str) or not _INTENT_NAME.match(intent):
            return None, "intent must be a lowercase identifier"
        if intent not in allowed:
            return None, f"intent must be one of the allowed values, not {intent!r}"
        problem = _valid_parameters(entry.get("parameters", {}), bounded=len(raw_steps) > 1)
        if problem:
            return None, problem
        steps.append({"intent": intent, "parameters": dict(entry.get("parameters", {}))})
    return {"steps": steps, "confidence": confidence,
            "too_many": "steps" in data and len(data["steps"]) > MAX_PLAN_STEPS}, None


def _expanded_count(steps: list[dict]) -> int:
    """Plan steps after item expansion: a step with `items` becomes one step per item (R-AK)."""
    total = 0
    for step in steps:
        items = step["parameters"].get("items")
        total += len(items) if isinstance(items, list) and items else 1
    return total


async def handle(state: PipelineState, model: IntentModel | None,
                 registry: CapabilityRegistry | None) -> PipelineState:
    """S2 handler. Returns the state with intent_result and task_id, or a stopped state."""
    ctx, norm = state.execution_context, state.normalized_input
    if ctx is None or norm is None:
        raise ValueError("S2 requires S0 and S1 outputs")
    if model is None or registry is None:
        return state.with_status(StageStatus.ERROR, "llm_unavailable")

    text = (norm.text or "").strip() or _request_text(norm.sanitized_input)
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

        steps = parsed["steps"]
        intents = tuple(step["intent"] for step in steps)
        first_params = steps[0]["parameters"]
        items = first_params.get("items")
        multi = len(steps) > 1
        result = IntentResult(
            intent_type=intents[0],
            target_entities=(),
            operations=intents,
            parameters=first_params,
            is_workflow=multi or (isinstance(items, list) and len(items) > 1),
            confidence=float(parsed["confidence"]),
            raw_llm_output=completion.text,
            attempt=attempt,
            steps=tuple(IntentStep(step["intent"], step["parameters"]) for step in steps) if multi else (),
        )
        state = state.replace_context("S2", task_id=state.execution_context.task_id or str(uuid.uuid4()))  # R-M; EVENT_DRIVEN keeps event_id
        state = state.with_stage_output("S2", result)
        if INTENT_PROHIBITED in intents:
            return state.with_status(StageStatus.DENY, "intent_prohibited")
        if INTENT_UNKNOWN in intents:
            return state.with_status(StageStatus.CLARIFY, "intent_unclear")
        if multi and (parsed["too_many"] or _expanded_count(steps) > MAX_PLAN_STEPS):
            return state.with_status(StageStatus.CLARIFY, TOO_MANY_STEPS)   # R-AC
        return state

    return state.with_status(StageStatus.CLARIFY, "intent_unparseable")
