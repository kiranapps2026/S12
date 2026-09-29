"""DeepSeek adapter: the built-in request, response parsing and fail-closed errors."""
from __future__ import annotations

import asyncio
import json
import urllib.error

import pytest

from adapters.llm.deepseek import DeepSeekIntentModel
from adapters.llm.deepseek_request import ENDPOINT, REQUEST_SETTINGS
from contracts.errors import DependencyUnavailable

KEY = "sk-test-secret"
ANSWER = '{"intent": "contact.list", "confidence": 0.9, "parameters": {}}'
REPLY = {"model": "deepseek-flash", "status": "completed", "usage": {"total_tokens": 57},
         "output": [{"type": "reasoning", "summary": []},
                    {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": ANSWER}]}]}


class Transport:
    def __init__(self, reply=REPLY, error: Exception | None = None) -> None:
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.error:
            raise self.error
        return self.reply


def _complete(transport, feedback=None):
    model = DeepSeekIntentModel(KEY, transport=transport)
    return asyncio.run(model.complete("list my contacts", ("contact.list", "contact.create"), feedback))


def test_request_uses_the_built_in_settings_and_only_the_key_from_outside():
    transport = Transport()
    _complete(transport)
    url, headers, body, timeout = transport.calls[0]
    assert url == ENDPOINT == "https://api.deepseek.com/responses"
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert {k: v for k, v in body.items() if k in REQUEST_SETTINGS} == dict(REQUEST_SETTINGS)
    assert body["model"] == "deepseek-flash" and body["reasoning"] == {"effort": "none"}
    assert body["temperature"] == 0.1 and body["max_output_tokens"] == 500
    assert timeout == 30.0


def test_output_is_constrained_to_the_known_intents():
    transport = Transport()
    _complete(transport)
    text_format = transport.calls[0][2]["text"]["format"]
    assert text_format["type"] == "json_schema" and text_format["name"] == "intent_result"
    schema = text_format["schema"]
    assert schema["properties"]["intent"]["enum"] == ["contact.list", "contact.create", "unknown", "prohibited"]
    assert schema["required"] == ["intent", "confidence", "parameters"]


def test_input_carries_the_request_and_retry_feedback():
    transport = Transport()
    _complete(transport, feedback="confidence must be a number")
    body = transport.calls[0][2]
    assert "Never invent an intent" in body["instructions"]
    assert [item["content"] for item in body["input"]][0] == "list my contacts"
    assert "confidence must be a number" in body["input"][1]["content"]


def test_reply_is_parsed_into_text_model_and_tokens():
    completion = _complete(Transport())
    assert (completion.model, completion.total_tokens) == ("deepseek-flash", 57)
    assert json.loads(completion.text)["intent"] == "contact.list"


@pytest.mark.parametrize("transport", [
    Transport(error=urllib.error.URLError("unreachable")),
    Transport(error=TimeoutError()),
    Transport(error=urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", {}, None)),
    Transport(reply={**REPLY, "status": "incomplete"}),
    Transport(reply={**REPLY, "output": []}),
    Transport(reply={"unexpected": True}),
])
def test_failures_become_dependency_unavailable_without_the_key(transport):
    with pytest.raises(DependencyUnavailable) as raised:
        _complete(transport)
    assert KEY not in str(raised.value)


def test_empty_key_is_rejected():
    with pytest.raises(ValueError):
        DeepSeekIntentModel("")
