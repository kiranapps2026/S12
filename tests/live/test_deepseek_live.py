"""One real DeepSeek call with the built-in request. Runs only when DEEPSEEK_API_KEY is set."""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from supragents.adapters.llm.deepseek import DeepSeekIntentModel


def test_live_classification_returns_valid_json():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        pytest.skip("DEEPSEEK_API_KEY is not set: live DeepSeek test not run")
    completion = asyncio.run(DeepSeekIntentModel(key).complete(
        "show me all my contacts", ("contact.list", "contact.create", "contact.delete"), None))
    answer = json.loads(completion.text)
    assert answer["intent"] == "contact.list"
    assert 0.0 <= float(answer["confidence"]) <= 1.0
    assert completion.total_tokens > 0
