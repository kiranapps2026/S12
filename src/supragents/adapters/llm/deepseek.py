"""DeepSeek Responses API client implementing the IntentModel port.

Standard library only (no extra packages for the offline bundle). The API key is
passed in by the composition root from the environment and is never logged.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from supragents.adapters.llm.deepseek_request import (
    ENDPOINT,
    INSTRUCTIONS,
    REQUEST_SETTINGS,
    SCHEMA_NAME,
    TIMEOUT_SECONDS,
    intent_schema,
)
from supragents.contracts.errors import DependencyUnavailable
from supragents.ports.intent import IntentCompletion

Transport = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]
_FAILURES = (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError)


def post_json(url: str, headers: dict[str, str], body: bytes, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class DeepSeekIntentModel:
    def __init__(self, api_key: str, transport: Transport = post_json) -> None:
        if not api_key:
            raise ValueError("DeepSeek API key is empty")
        self._api_key = api_key
        self._transport = transport

    async def complete(self, text: str, intents: tuple[str, ...], feedback: str | None) -> IntentCompletion:
        body = json.dumps(build_request(text, intents, feedback)).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "Authorization": f"Bearer {self._api_key}"}
        try:
            reply = await asyncio.to_thread(self._transport, ENDPOINT, headers, body, TIMEOUT_SECONDS)
            return parse_reply(reply)
        except _FAILURES as error:
            raise DependencyUnavailable(f"DeepSeek call failed: {type(error).__name__}") from None


def build_request(text: str, intents: tuple[str, ...], feedback: str | None) -> dict[str, Any]:
    items = [{"type": "message", "role": "user", "content": text}]
    if feedback is not None:
        items.append({"type": "message", "role": "user",
                      "content": f"Your previous answer was rejected: {feedback}. Answer again."})
    return {
        **REQUEST_SETTINGS,
        "instructions": INSTRUCTIONS,
        "input": items,
        "text": {"format": {"type": "json_schema", "name": SCHEMA_NAME, "schema": intent_schema(intents)}},
    }


def parse_reply(reply: dict[str, Any]) -> IntentCompletion:
    """Text of the first output message; a response that is not completed is a failure."""
    if reply.get("status", "completed") != "completed":
        raise ValueError(f"response status {reply.get('status')}")
    parts = [part["text"] for item in reply["output"] if item.get("type") == "message"
             for part in item["content"] if part.get("type") == "output_text"]
    return IntentCompletion(text=parts[0], model=reply.get("model", REQUEST_SETTINGS["model"]),
                            total_tokens=int(reply["usage"]["total_tokens"]))
