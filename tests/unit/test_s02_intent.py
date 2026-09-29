"""S2: the single LLM call, schema validation and the one retry."""
from __future__ import annotations

import json

import pytest

from supragents.contracts.errors import DependencyUnavailable
from supragents.contracts.vocabulary import StageStatus
from tests.builders import Harness
from tests.fakes.ports import intent_json


def _s2(*answers):
    h = Harness()
    state = h.state_before("S2")
    h.say(*answers)
    return h, h.run_stage("S2", state)


def test_valid_answer_records_intent_and_task_id():
    h, state = _s2(intent_json("contact.list", 0.8, limit=5))
    intent = state.intent_result
    assert (intent.intent, intent.confidence, dict(intent.parameters), intent.attempt) == ("contact.list", 0.8, {"limit": 5}, 1)
    assert state.execution_context.task_id == intent.task_id
    assert h.intent_model.calls == [("list my contacts", None)]


@pytest.mark.parametrize("bad, feedback", [
    ("not json", "response is not valid JSON"),
    ("[1, 2]", "response must be a JSON object"),
    (json.dumps({"intent": "Bad Intent!", "confidence": 0.9}), "intent must be a lowercase identifier"),
    (json.dumps({"intent": "a", "confidence": True}), "confidence must be a number"),
    (json.dumps({"intent": "a", "confidence": 1.5}), "confidence must be between 0 and 1"),
    (json.dumps({"intent": "a", "confidence": 0.9, "parameters": [1]}), "parameters must be a JSON object"),
])
def test_invalid_answer_is_retried_once_with_feedback(bad, feedback):
    h, state = _s2(bad, intent_json("contact.list"))
    assert state.intent_result.attempt == 2
    assert h.intent_model.calls[1][1] == feedback


def test_two_invalid_answers_clarify():
    h, state = _s2("nope", "still nope")
    assert (state.halt.status, state.halt.reason) == (StageStatus.CLARIFY, "intent_unparseable")
    assert state.intent_result is None and len(h.intent_model.calls) == 2


def test_unreachable_model_is_an_error():
    _, state = _s2(DependencyUnavailable("timeout"))
    assert (state.halt.status, state.halt.reason) == (StageStatus.ERROR, "llm_unavailable")


def test_parameters_are_immutable():
    _, state = _s2(intent_json("contact.list", tags=["a"]))
    with pytest.raises(TypeError):
        state.intent_result.parameters["tags"] = ()


def test_model_is_offered_only_production_intents():
    h, _ = _s2(intent_json("contact.list"))
    assert h.intent_model.offered_intents == [("contact.create", "contact.delete", "contact.list", "email.send")]


def test_every_call_records_token_usage():
    h, state = _s2("not json", intent_json("contact.list"))
    records = h.usage.records
    assert [r.quantity for r in records] == [42, 42]
    first = records[0]
    assert (first.resource_type, first.unit, first.kernel_op_ref, first.model) == (
        "llm.token", "token", "llm.intent_analysis", "scripted-model")
    assert (first.tenant_id, first.trace_id) == ("tenant-a", state.execution_context.trace_id)


def test_unrecordable_usage_stops_the_run():
    h = Harness()
    state = h.state_before("S2")
    h.usage.fail = True
    out = h.run_stage("S2", state)
    assert (out.halt.status, out.halt.reason) == (StageStatus.ERROR, "usage_unrecorded")
    assert out.intent_result is None
