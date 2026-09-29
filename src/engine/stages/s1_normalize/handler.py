"""
S1 Normalize — sanitize inputs, detect injection attacks.

Source: FINAL_ARCHITECTURE.md §11, SECURITY.md §4
Owner: S1 / Normalize
Canonical sanitizer: DataSanitizer (src/contracts/data_sanitizer.py)
"""

from __future__ import annotations

import logging
import time

from contracts.pipeline_state import PipelineState
from contracts.data_sanitizer import DataSanitizer, Severity
from contracts.stage_registry import StageOutcome
from contracts.stage_outputs import NormalizedInput

logger = logging.getLogger(__name__)


class InjectionDetectedError(Exception):
    """Injection attack detected in input."""
    def __init__(self, message: str, pattern: str = "", severity: str = "") -> None:
        super().__init__(message)
        self.pattern = pattern
        self.severity = severity


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

    if isinstance(raw, dict):
        sanitized, patterns, modified = _sanitize_dict(raw)
        patterns_found.extend(patterns)
        any_modified = modified
    else:
        sanitized = raw

    # Check for critical injections
    has_critical = "prompt_injection" in patterns_found

    if has_critical:
        # Set flag on NormalizedInput — pipeline runner checks S8 for cordon decisions
        logger.warning("S1: critical injection detected — flagged in NormalizedInput")

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

    return state.with_stage_output("S1", normalized)
