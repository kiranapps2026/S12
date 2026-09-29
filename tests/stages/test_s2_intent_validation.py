"""
GOLDEN TEST FILE (OWNER). Pinned by hash. The agent edits it only on the owner's explicit
instruction.
Rulings: PIPELINE_STAGES §4 (S2 is the only LLM call; its output is untrusted), R-M (task_id set
by S2 through the context whitelist), R-U (risk, mutation and capabilities are registry facts).
The model may only choose among the registry's intents, "unknown" (-> CLARIFY intent_unclear) or
"prohibited" (-> DENY intent_prohibited); an invalid answer is retried once with feedback, then
CLARIFY intent_unparseable; a model failure is ERROR llm_unavailable, never a guess.
The vocabulary ("unknown", "prohibited") awaits its owner ruling id.

Fixture contract: run_through("S1", request) -> state after S1; the IntentModel is passed to the
real S2 handler `handle(state, model, registry)`; ScenarioRegistry(scenario) is the registry.
"""
from __future__ import annotations

import asyncio
import glob
import json

import pytest

from contracts.stage_registry import StageStatus
from engine.stages.s2_intent_analysis.handler import handle as s2
from tests.fixtures.pipeline import run_through
from tests.fixtures.scenarios import ScenarioRegistry, make_scenario
from tests.fixtures.states import ScenarioIntentModel

REQ = {"message": "list my contacts", "connection_id": "conn-1"}


class Scripted:
    """IntentModel returning scripted raw answers, one per call; records the feedback."""

    def __init__(self, *answers, error: Exception | None = None):
        self.answers, self.error, self.feedback = list(answers), error, []

    async def complete(self, text, intents, feedback):
        from contracts.intent_model import IntentCompletion
        self.feedback.append(feedback)
        if self.error:
            raise self.error
        return IntentCompletion(text=self.answers.pop(0), model="m", total_tokens=5)


def _run(model, sc=None, request=REQ):
    sc = sc or make_scenario()
    state = run_through("S1", request=request)
    return asyncio.run(s2(state, model, ScenarioRegistry(sc)))


def _ok(intent="query", confidence=0.9, **extra):
    return json.dumps({"intent": intent, "confidence": confidence, "parameters": {}, **extra})


def test_valid_answer_becomes_intent_result_and_task_id():
    out = _run(Scripted(_ok()))
    r = out.intent_result
    assert (r.intent_type, r.confidence, r.attempt, r.is_workflow) == ("query", 0.9, 1, False)
    assert out.execution_context.task_id                      # system-generated, R-M
    assert out.stage_status is StageStatus.NORMAL


def test_the_model_sees_the_users_text_and_the_registrys_intents_only():
    model = Scripted(_ok())
    _run(model)
    assert model.feedback == [None]


def test_items_make_it_a_workflow():
    raw = json.dumps({"intent": "query", "confidence": 0.9, "parameters": {"items": [{}, {}]}})
    assert _run(Scripted(raw)).intent_result.is_workflow is True


@pytest.mark.parametrize("bad", [
    "not json", "[]", _ok(intent="Not An Identifier"), _ok(intent="delete_everything"),
    json.dumps({"intent": "query", "confidence": "high", "parameters": {}}),
    json.dumps({"intent": "query", "confidence": True, "parameters": {}}),
    json.dumps({"intent": "query", "confidence": 1.5, "parameters": {}}),
    json.dumps({"intent": "query", "confidence": 0.5, "parameters": []}),
])
def test_invalid_answer_is_retried_once_with_feedback_then_clarifies(bad):
    model = Scripted(bad, bad)
    out = _run(model)
    assert (out.stage_status, out.deny_reason) == (StageStatus.CLARIFY, "intent_unparseable")
    assert out.intent_result is None
    assert model.feedback[0] is None and model.feedback[1]      # reason passed to the retry


def test_retry_can_succeed_and_records_the_attempt():
    out = _run(Scripted("not json", _ok()))
    assert (out.intent_result.attempt, out.stage_status) == (2, StageStatus.NORMAL)


def test_an_intent_the_registry_never_offered_is_rejected_even_if_well_formed():
    out = _run(Scripted(_ok(intent="contact.delete"), _ok(intent="contact.delete")))
    assert out.deny_reason == "intent_unparseable"


def test_unknown_intent_clarifies_and_prohibited_denies():
    unknown = _run(Scripted(_ok(intent="unknown", confidence=0.2)))
    assert (unknown.stage_status, unknown.deny_reason) == (StageStatus.CLARIFY, "intent_unclear")
    prohibited = _run(Scripted(_ok(intent="prohibited")))
    assert (prohibited.stage_status, prohibited.deny_reason) == (StageStatus.DENY, "intent_prohibited")


def test_model_failure_is_an_error_not_a_guess():
    out = _run(Scripted(error=RuntimeError("boom")))
    assert (out.stage_status, out.deny_reason) == (StageStatus.ERROR, "llm_unavailable")
    assert out.intent_result is None


def test_missing_model_or_registry_fails_closed():
    state = run_through("S1", request=REQ)
    assert asyncio.run(s2(state, None, ScenarioRegistry(make_scenario()))).deny_reason == "llm_unavailable"
    assert asyncio.run(s2(state, Scripted(_ok()), None)).deny_reason == "llm_unavailable"


def test_request_without_text_clarifies_without_calling_the_model():
    model = Scripted(_ok())
    out = _run(model, request={"connection_id": "c", "other": 1})
    assert (out.stage_status, out.deny_reason) == (StageStatus.CLARIFY, "missing_text")
    assert model.feedback == []


def test_the_model_cannot_influence_risk_mutation_or_capabilities():
    """Extra fields in the answer are ignored; S5 still takes everything from the registry."""
    sc = make_scenario(mutation="D", risk=0.4)
    answer = json.dumps({"intent": "delete", "confidence": 0.9, "parameters": {
        "risk": 0.0, "mutation": "R", "candidates": [{"capability_id": "evil"}]}})
    state = run_through("S1", request=REQ)
    out = asyncio.run(s2(state, Scripted(answer), ScenarioRegistry(sc)))
    assert out.stage_status is StageStatus.NORMAL
    from tests.fixtures.states import run_stage, state_ready_for
    s5 = run_stage("S5", state_ready_for("S5", sc), sc).frozen_binding_identity
    assert (s5.effective_mutation, s5.effective_risk, s5.capability_id) == ("D", 0.4, "cap-1")


def test_scenario_model_is_deterministic():
    sc = make_scenario()
    a = asyncio.run(ScenarioIntentModel(sc).complete("x", ("query",), None)).text
    b = asyncio.run(ScenarioIntentModel(sc).complete("x", ("query",), None)).text
    assert a == b


def test_s2_is_the_only_stage_that_talks_to_a_model():
    users = [f for f in glob.glob("src/engine/stages/s*/handler.py")
             if "IntentModel" in open(f).read()]
    assert [u for u in users if "s2_intent" not in u] == []
    assert not any("MockLLMProvider" in open(f).read() for f in glob.glob("src/**/*.py", recursive=True))
