"""JSON codec for suspended runs: exact round trip, no code execution, strict on mismatch."""
import dataclasses
import json

import pytest

from contracts.codec import decode, decode_state, encode, encode_state
from contracts.execution_context import ExecutionContext
from contracts.stage_registry import StageStatus
from tests.fixtures.pipeline import run_pipeline
from tests.fixtures.scenarios import make_scenario

HIGH = dict(mutation="D", risk=0.9, steps=3, graph="chain", confidence=0.8)


def _suspended_state():
    result = run_pipeline({"message": "x", "connection_id": "c"}, make_scenario(**HIGH))
    assert (result.final_stage, result.status) == ("S10", StageStatus.CLARIFY)
    return result.final_state


def test_a_real_suspended_state_round_trips_exactly_through_json_text():
    state = _suspended_state()
    text = json.dumps(encode_state(state))                 # what the database stores
    assert decode_state(json.loads(text)) == state


def test_round_trip_keeps_types_not_just_values():
    back = decode_state(json.loads(json.dumps(encode_state(_suspended_state()))))
    assert isinstance(back.execution_context.tags, frozenset)
    assert isinstance(back.plan.plan.steps, tuple) and isinstance(back.plan.plan.steps[0].depends_on, tuple)
    assert isinstance(back.task_profile.mutations, tuple)
    assert back.stage_status is StageStatus.CLARIFY
    assert back.confirmation.confirmation.consumed_at is None


def test_unknown_fields_are_rejected():
    data = encode_state(_suspended_state())
    data["shell_command"] = "rm -rf /"
    with pytest.raises(TypeError, match="unknown PipelineState fields"):
        decode_state(data)


@pytest.mark.parametrize("path,bad", [
    (("execution_context", "tenant_id"), 42),
    (("task_profile", "risk"), "high"),
    (("task_profile", "requires_confirmation"), "yes"),
    (("plan", "plan", "steps"), {"a": 1}),
    (("plan", "plan", "budget_reserved"), True),
    (("stage_status",), "EXPLODE"),
])
def test_a_value_that_does_not_fit_its_contract_raises(path, bad):
    data = encode_state(_suspended_state())
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = bad
    with pytest.raises((TypeError, ValueError)):
        decode_state(data)


def test_int_is_accepted_where_float_is_declared_json_writes_1_for_1_0():
    data = encode_state(_suspended_state())
    data["task_profile"]["risk"] = 1
    assert decode_state(data).task_profile.risk == 1.0


def test_encode_is_plain_json():
    ctx = dataclasses.replace(_suspended_state().execution_context, tags=frozenset({"b", "a"}))
    assert encode(ctx)["tags"] == ["a", "b"]
    assert decode(ExecutionContext, json.loads(json.dumps(encode(ctx)))) == ctx
