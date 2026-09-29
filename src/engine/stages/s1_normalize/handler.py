"""
S1 Normalize — sanitize inputs, detect injection attacks.

Source: FINAL_ARCHITECTURE.md §11, SECURITY.md §4
Owner: S1 / Normalize
Canonical sanitizer: DataSanitizer (src/contracts/data_sanitizer.py)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from contracts.pipeline_state import PipelineState
from contracts.data_sanitizer import DataSanitizer, Severity
from contracts.stage_registry import StageStatus
from contracts.stage_outputs import NormalizedInput

logger = logging.getLogger(__name__)


class InjectionDetectedError(Exception):
    """Injection attack detected in input."""
    def __init__(self, message: str, pattern: str = "", severity: str = "") -> None:
        super().__init__(message)
        self.pattern = pattern
        self.severity = severity


# --- input limits (checked BEFORE any regex runs, so the sanitizer's worst case is bounded) ---
MAX_STRING_CHARS = 8000        # one string value (the user's message is the longest legitimate one)
MAX_PAYLOAD_CHARS = 65536      # all strings and keys together
MAX_DEPTH = 10                 # nesting of dicts/lists
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # C0 controls except \t \n \r, and DEL


def _limits_problem(raw: Any) -> str | None:
    """A reason code if the payload is too large/deep or cannot be stored as UTF-8, else None."""
    total = 0
    stack: list[tuple[Any, int]] = [(raw, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_DEPTH:
            return "input_too_large"
        if isinstance(value, str):
            total += len(value)
            if len(value) > MAX_STRING_CHARS or total > MAX_PAYLOAD_CHARS:
                return "input_too_large"
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:          # lone surrogate: not storable, not real text
                return "invalid_characters"
        elif isinstance(value, dict):
            for k, v in value.items():
                stack.append((k, depth + 1))
                stack.append((v, depth + 1))
        elif isinstance(value, (list, tuple)):
            for v in value:
                stack.append((v, depth + 1))
    return None


def _strip_controls(value: Any) -> tuple[Any, bool]:
    """Remove control characters (NUL etc.) from every string; PostgreSQL cannot store NUL."""
    if isinstance(value, str):
        cleaned = _CONTROL.sub("", value)
        return cleaned, cleaned != value
    if isinstance(value, dict):
        out, changed = {}, False
        for k, v in value.items():
            nv, c = _strip_controls(v)
            out[k], changed = nv, changed or c
        return out, changed
    if isinstance(value, list):
        items = [_strip_controls(v) for v in value]
        return [i for i, _ in items], any(c for _, c in items)
    return value, False


def _sanitize_dict(data: dict) -> tuple[dict, list[str], bool]:
    """Recursively sanitize all string values in a dict."""
    patterns_found: list[str] = []
    any_modified = False
    result = {}

    for key, value in data.items():
        if isinstance(value, str):
            sanitized_result = DataSanitizer.sanitize(value)
            result[key] = sanitized_result.sanitized
            if sanitized_result.was_modified:
                any_modified = True
            if sanitized_result.pattern_matched:
                patterns_found.append(sanitized_result.pattern_matched)
        elif isinstance(value, dict):
            inner, patterns, modified = _sanitize_dict(value)
            result[key] = inner
            patterns_found.extend(patterns)
            if modified:
                any_modified = True
        elif isinstance(value, list):
            sanitized_list = []
            for item in value:
                if isinstance(item, str):
                    sr = DataSanitizer.sanitize(item)
                    sanitized_list.append(sr.sanitized)
                    if sr.was_modified:
                        any_modified = True
                    if sr.pattern_matched:
                        patterns_found.append(sr.pattern_matched)
                elif isinstance(item, dict):
                    inner, patterns, modified = _sanitize_dict(item)
                    sanitized_list.append(inner)
                    patterns_found.extend(patterns)
                    if modified:
                        any_modified = True
                else:
                    sanitized_list.append(item)
            result[key] = sanitized_list
        else:
            result[key] = value

    return result, patterns_found, any_modified


async def handle(state: PipelineState) -> PipelineState:
    """
    S1 handler: apply DataSanitizer to all inputs.

    Reads raw payload from state.entry_request (S0 output).
    Returns updated PipelineState with NormalizedInput set.
    CORDONS if critical injection is detected.
    """
    raw_input = getattr(state, 'entry_request', None)
    raw = raw_input.raw_payload if raw_input else {}
    patterns_found: list[str] = []
    any_modified = False

    problem = _limits_problem(raw)
    if problem is not None:
        logger.warning("S1: DENY %s", problem)
        state = state.with_stage_output("S1", NormalizedInput(
            sanitized_input={}, patterns_detected=(problem,), was_modified=False,
            has_critical_injection=False, timestamp=time.time()))    # the raw payload is dropped
        return state.with_status(StageStatus.DENY, problem)

    raw, controls_stripped = _strip_controls(raw)
    if controls_stripped:
        patterns_found.append("control_characters")
        any_modified = True

    if isinstance(raw, dict):
        sanitized, patterns, modified = _sanitize_dict(raw)
        patterns_found.extend(patterns)
        any_modified = any_modified or modified
    else:
        sanitized = raw

    # Check for critical injections
    has_critical = "prompt_injection" in patterns_found

    if has_critical:
        logger.warning("S1: critical injection detected — DENY")

    normalized = NormalizedInput(
        sanitized_input=sanitized,
        patterns_detected=tuple(patterns_found),
        was_modified=any_modified,
        has_critical_injection=has_critical,
        timestamp=time.time(),
    )

    logger.info(
        "S1 normalized: patterns=%s, modified=%s, critical=%s",
        patterns_found, any_modified, has_critical,
    )

    state = state.with_stage_output("S1", normalized)
    if has_critical:
        return state.with_status(StageStatus.DENY, "injection_detected")
    return state
