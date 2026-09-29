"""S2 Intent Analysis: the one unconditional LLM call, validated and retried once.

LLM output is untrusted: it becomes an IntentResult only after schema validation,
and it never populates ExecutionContext (only the system-generated task_id does).
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from supragents.contracts.frozen_json import FrozenJson, freeze
from supragents.contracts.outputs import IntentResult
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus
from supragents.pipeline.deps import PipelineDeps

STAGE = "S2"
MAX_ATTEMPTS = 2
_INTENT_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


@dataclass(frozen=True)
class _ParsedIntent:
    intent: str
    parameters: FrozenJson
    confidence: float


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    text = state.normalized_input.text
    feedback: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = await deps.intent_model.complete(text, feedback)
        except Exception:
            return state.halted(STAGE, StageStatus.ERROR, "llm_unavailable")
        parsed, feedback = _parse(raw)
        if parsed is not None:
            return _record(state, parsed, raw, attempt)
    return state.halted(STAGE, StageStatus.CLARIFY, "intent_unparseable")


def _record(state: PipelineState, parsed: _ParsedIntent, raw: str, attempt: int) -> PipelineState:
    task_id = str(uuid.uuid4())
    state = state.with_output(STAGE, intent_result=IntentResult(
        intent=parsed.intent,
        parameters=parsed.parameters,
        confidence=parsed.confidence,
        raw_response=raw,
        task_id=task_id,
        attempt=attempt,
    ))
    return state.with_context(STAGE, task_id=task_id)


def _parse(raw: str) -> tuple[_ParsedIntent | None, str | None]:
    """Return (parsed, None) or (None, feedback for the retry)."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, "response is not valid JSON"
    if not isinstance(data, dict):
        return None, "response must be a JSON object"
    problem = _schema_problem(data)
    if problem is not None:
        return None, problem
    return _ParsedIntent(
        intent=data["intent"],
        parameters=freeze(data.get("parameters", {})),
        confidence=float(data["confidence"]),
    ), None


def _schema_problem(data: dict[str, Any]) -> str | None:
    intent = data.get("intent")
    if not isinstance(intent, str) or not _INTENT_NAME.match(intent):
        return "intent must be a lowercase identifier"
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return "confidence must be a number"
    if not 0.0 <= confidence <= 1.0:
        return "confidence must be between 0 and 1"
    if not isinstance(data.get("parameters", {}), dict):
        return "parameters must be a JSON object"
    return None
