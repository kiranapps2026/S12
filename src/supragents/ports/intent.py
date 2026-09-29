"""S2 LLM port. The model returns raw text; S2 parses and validates it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IntentCompletion:
    """The model's raw answer and what it cost (tokens are billed, PIPELINE_STAGES §4)."""

    text: str
    model: str
    total_tokens: int


class IntentModel(Protocol):
    async def complete(
        self, text: str, intents: tuple[str, ...], feedback: str | None
    ) -> IntentCompletion:
        """Classify ``text`` as one of ``intents`` and return a JSON object as text:
        {"intent": ..., "confidence": 0.0-1.0, "parameters": {...}}.

        ``feedback`` describes why the previous answer was rejected (retry only).
        Raise DependencyUnavailable if the model cannot be reached.
        """
