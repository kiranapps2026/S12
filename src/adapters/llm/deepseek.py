"""DeepSeek chat-completions client implementing the IntentModel port (OpenAI-compatible API).

Standard library only (no extra packages). The API key is passed in by the composition root from
the environment and is never logged or included in an error message.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from adapters.llm.deepseek_request import (
    ENDPOINT,
    REQUEST_SETTINGS,
    TIMEOUT_SECONDS,
    system_prompt,
)
from contracts.errors import DependencyUnavailable
from contracts.intent_model import IntentCompletion

Transport = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]
_FAILURES = (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError)
# "stop": finished; "length": cut off (the truncated JSON then fails S2's validation and is retried)
_USABLE_FINISH = ("stop", "length")


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
    messages = [{"role": "system", "content": system_prompt(intents)},
                {"role": "user", "content": text}]
    if feedback is not None:
        messages.append({"role": "user",
                         "content": f"Your previous answer was rejected: {feedback}. Answer again."})
    return {**REQUEST_SETTINGS, "messages": messages}


def parse_reply(reply: dict[str, Any]) -> IntentCompletion:
    """The first choice's message content. An empty or unusable answer is returned as-is (S2
    rejects it and retries with feedback); a missing structure or a filtered/failed completion
    is a failure."""
    choice = reply["choices"][0]
    if choice.get("finish_reason", "stop") not in _USABLE_FINISH:
        raise ValueError(f"finish_reason {choice.get('finish_reason')}")
    content = choice["message"].get("content") or ""
    if not isinstance(content, str):
        raise TypeError("content is not text")
    return IntentCompletion(text=content, model=reply.get("model", REQUEST_SETTINGS["model"]),
                            total_tokens=int(reply["usage"]["total_tokens"]))
