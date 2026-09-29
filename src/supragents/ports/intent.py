"""S2 LLM port. The model returns raw text; S2 parses and validates it."""
from __future__ import annotations

from typing import Protocol


class IntentModel(Protocol):
    async def complete(self, text: str, feedback: str | None) -> str:
        """Return a JSON object {"intent", "parameters", "confidence"} as text.

        ``feedback`` describes why the previous answer was rejected (retry only).
        Raise DependencyUnavailable if the model cannot be reached.
        """
