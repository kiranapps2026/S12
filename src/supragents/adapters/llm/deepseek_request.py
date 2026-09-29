"""The built-in DeepSeek Responses API request: every setting except the API key lives here.

S2 requirements (PIPELINE_STAGES §4): structured output validated against a schema, short
answers, low temperature. Thinking is off (``reasoning.effort = "none"``) because DeepSeek
ignores temperature in thinking mode.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any

ENDPOINT = "https://api.deepseek.com/responses"
MODEL = "deepseek-flash"            # alternative: "deepseek-v4-pro"
TIMEOUT_SECONDS = 30.0
SCHEMA_NAME = "intent_result"
UNKNOWN_INTENT = "unknown"

REQUEST_SETTINGS = MappingProxyType({
    "model": MODEL,
    "reasoning": {"effort": "none"},
    "max_output_tokens": 500,
    "temperature": 0.1,
    "tool_choice": "none",
    "stream": False,
})

INSTRUCTIONS = """You classify a user's request for a business automation system.
Choose the intent from the allowed values; use "unknown" with a low confidence if none fits.
Put the values mentioned in the request into "parameters". For the same operation on several
items, use "parameters": {"items": [{...}, ...]}. Never invent an intent."""


def intent_schema(intents: tuple[str, ...]) -> dict[str, Any]:
    """JSON Schema for the answer; ``intent`` is limited to the registry's known intents."""
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": [*intents, UNKNOWN_INTENT]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "parameters": {"type": "object"},
        },
        "required": ["intent", "confidence", "parameters"],
        "additionalProperties": False,
    }
