"""
S1 Normalize — sanitize inputs, detect injection attacks.

Source: FINAL_ARCHITECTURE.md §11, SECURITY.md §4
Owner: S1 / Normalize
Canonical sanitizer: DataSanitizer (src/contracts/data_sanitizer.py)
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
import unicodedata
from typing import Any

from contracts.pipeline_state import PipelineState
from contracts.data_sanitizer import DataSanitizer, Severity
from contracts.stage_registry import StageStatus
from contracts.stage_outputs import NormalizedInput
from contracts.reference_source import ReferenceSource
from engine.stages.s1_normalize.entities import extract_entities
from engine.stages.s1_normalize.references import has_reference, resolve_references

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
        cleaned = unicodedata.normalize("NFC", _CONTROL.sub("", value))
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


def _evasion_form(value: str) -> str:
    """The text as an attacker would hide it from a literal regex: compatibility characters folded
    (fullwidth 'ｉｇｎｏｒｅ' -> 'ignore'), invisible format characters removed (zero-width joiners,
    soft hyphens, bidi marks), whitespace collapsed. Used for DETECTION only; the model still
    receives the user's own text (NFC)."""
    folded = unicodedata.normalize("NFKC", value)
    visible = "".join(c for c in folded if unicodedata.category(c) != "Cf")
    return re.sub(r"\s+", " ", visible)


def _hidden_patterns(value: str) -> list[str]:
    """Patterns found only after undoing the obfuscation above."""
    alt = _evasion_form(value)
    if alt == value:
        return []
    hit = DataSanitizer.sanitize(alt).pattern_matched
    return [hit] if hit else []


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
            patterns_found.extend(_hidden_patterns(value))
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
                    patterns_found.extend(_hidden_patterns(item))
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


def _message_key(raw: Any) -> str | None:
    """The key S2 reads its text from: "message", else "text"."""
    if isinstance(raw, dict):
        for key in ("message", "text"):
            if isinstance(raw.get(key), str) and raw[key].strip():
                return key
    return None


def _stop(state: PipelineState, status: StageStatus, reason: str) -> PipelineState:
    """Write an empty NormalizedInput (nothing of the payload is kept) and stop the run."""
    state = state.with_stage_output("S1", NormalizedInput(
        sanitized_input={}, patterns_detected=(reason,), was_modified=False,
        has_critical_injection=False, timestamp=time.time()))
    return state.with_status(status, reason)


async def handle(state: PipelineState, references: ReferenceSource | None = None) -> PipelineState:
    """
    S1 handler (PIPELINE_STAGES §3): limits, control characters, unicode (NFC), trim, `$ref` /
    `$file` / `{{template}}` resolution, entity extraction, DataSanitizer (incl. an
    obfuscation-proof injection scan).

    Reads the raw payload from state.entry_request (S0 output). Order matters: limits first (so
    no regex sees an oversized string), references next, the sanitizer LAST and over the resolved
    text (a stored value may carry an injection). Refusals: DENY input_too_large /
    invalid_characters / too_many_references / injection_detected; CLARIFY unresolved_reference;
    ERROR reference_source_unavailable.
    """
    raw_input = getattr(state, 'entry_request', None)
    raw = raw_input.raw_payload if raw_input else {}
    patterns_found: list[str] = []
    any_modified = False

    problem = _limits_problem(raw)
    if problem is not None:
        logger.warning("S1: DENY %s", problem)
        return _stop(state, StageStatus.DENY, problem)

    raw, controls_stripped = _strip_controls(raw)
    if controls_stripped:
        patterns_found.append("control_characters")
        any_modified = True

    # --- references (actions 2-4) on the user's message ---------------------------------------
    key = _message_key(raw)
    resolved = None
    if key is not None:
        text = raw[key].strip()
        if has_reference(text):
            ctx = state.execution_context
            try:
                resolved = await resolve_references(
                    text, tenant_id=ctx.tenant_id, workspace_id=ctx.workspace_id, user_id=ctx.user_id,
                    conversation_id=ctx.conversation_id, source=references)
            except Exception:  # noqa: BLE001 — fail closed; detail is not exposed
                logger.exception("S1: reference source failed")
                return _stop(state, StageStatus.ERROR, "reference_source_unavailable")
            if resolved.problem:
                return _stop(state, StageStatus.DENY, resolved.problem)
            if resolved.unresolved:
                logger.info("S1: unresolved references: %s", resolved.unresolved)
                return _stop(state, StageStatus.CLARIFY, "unresolved_reference")
            text = resolved.text
            any_modified = True
            if len(text) > MAX_STRING_CHARS:
                return _stop(state, StageStatus.DENY, "input_too_large")
        raw = {**raw, key: text}

    if isinstance(raw, dict):
        sanitized, patterns, modified = _sanitize_dict(raw)
        patterns_found.extend(patterns)
        any_modified = any_modified or modified
    else:
        sanitized = raw

    has_critical = "prompt_injection" in patterns_found
    if has_critical:
        logger.warning("S1: critical injection detected — DENY")

    # --- entities (action 5): advisory, deterministic, on the sanitized text ----------------------
    final_text = sanitized[key] if key is not None and isinstance(sanitized, dict) else ""
    entities: dict = {}
    if final_text and not has_critical:
        today = None
        if references is not None and re.search(r"\b(today|tomorrow|yesterday)\b", final_text, re.I):
            try:
                today = dt.datetime.fromtimestamp(await references.now(), dt.timezone.utc).date()
            except Exception:  # noqa: BLE001 — relative dates are a hint; never a reason to fail
                today = None
        entities = extract_entities(final_text, today)
        if resolved is not None and resolved.files:
            entities["files"] = sorted({*entities.get("files", []), *resolved.files})[:20]

    normalized = NormalizedInput(
        sanitized_input=sanitized,
        patterns_detected=tuple(patterns_found),
        was_modified=any_modified,
        has_critical_injection=has_critical,
        timestamp=time.time(),
        text=final_text,
        entities=entities,
        references=dict(resolved.references) if resolved is not None else {},
    )

    logger.info(
        "S1 normalized: patterns=%s, modified=%s, critical=%s, references=%d",
        patterns_found, any_modified, has_critical, len(normalized.references),
    )

    state = state.with_stage_output("S1", normalized)
    if has_critical:
        return state.with_status(StageStatus.DENY, "injection_detected")
    return state
