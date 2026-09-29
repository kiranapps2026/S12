"""One real DeepSeek call through the adapter and the real S2 handler.

Run:  DEEPSEEK_API_KEY=... pytest tests_live      (costs a few tokens)
"""
import asyncio
import json
import os

from adapters.llm.deepseek import DeepSeekIntentModel
from engine.stages.s2_intent_analysis.handler import handle as s2
from tests.fixtures.pipeline import run_through
from tests.fixtures.scenarios import ScenarioRegistry, make_scenario

INTENTS = ("contact.list", "contact.create", "contact.delete")


def _model():
    return DeepSeekIntentModel(os.environ["DEEPSEEK_API_KEY"])


def test_live_classification_returns_valid_json():
    completion = asyncio.run(_model().complete("show me all my contacts", INTENTS, None))
    answer = json.loads(completion.text)
    assert answer["intent"] == "contact.list"
    assert 0.0 <= float(answer["confidence"]) <= 1.0
    assert completion.total_tokens > 0


def test_live_off_topic_is_not_forced_into_an_intent():
    answer = json.loads(asyncio.run(_model().complete("what is the weather like on Mars?", INTENTS, None)).text)
    assert answer["intent"] in ("unknown", "prohibited") or answer["confidence"] < 0.5


def test_live_through_the_real_s2_handler():
    class Registry(ScenarioRegistry):
        async def known_intents(self, tenant_id):
            return INTENTS

    state = run_through("S1", request={"message": "delete the contact John Smith", "connection_id": "c"})
    out = asyncio.run(s2(state, _model(), Registry(make_scenario())))
    assert out.intent_result.intent_type == "contact.delete"
