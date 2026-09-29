"""Input sanitizer used by S1 (SECURITY §6). Deterministic; no LLM."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_TEXT_LENGTH = 4000

_HIGH_SEVERITY = (
    ("instruction_override", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions?|rules|prompts?)\b", re.I)),
    ("role_hijack", re.compile(r"\byou are now\b|\bact as (an? )?(admin|system|developer)\b", re.I)),
    ("system_prompt_probe", re.compile(r"\b(reveal|print|show)\b.{0,30}\bsystem prompt\b", re.I)),
)
_LOW_SEVERITY = (
    ("markup", re.compile(r"<\s*/?\s*(script|iframe|object|embed)\b[^>]*>", re.I)),
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class SanitizedText:
    text: str
    patterns: tuple[str, ...]
    high_severity: bool


def sanitize(raw: str) -> SanitizedText:
    """Normalize unicode, drop control characters and markup, and name what was found."""
    text = _CONTROL_CHARS.sub("", unicodedata.normalize("NFKC", raw)).strip()
    high = tuple(name for name, pattern in _HIGH_SEVERITY if pattern.search(text))
    low = tuple(name for name, pattern in _LOW_SEVERITY if pattern.search(text))
    for _, pattern in _LOW_SEVERITY:
        text = pattern.sub("", text)
    return SanitizedText(text=text.strip(), patterns=high + low, high_severity=bool(high))
