"""The state codec round-trips a real suspended run exactly and rejects bad data."""
from __future__ import annotations

import json

import pytest

from supragents.contracts.codec import decode, encode
from supragents.contracts.outputs import Step
from supragents.contracts.state import PipelineState
from tests.builders import Harness, entry
from tests.fakes.ports import intent_json


def _suspended_state() -> PipelineState:
    h = Harness()
    h.say(intent_json("contact.delete", items=[{"id": "a", "tags": ["x"]}, {"id": "b"}]))
    h.run(entry("delete contacts a and b"))
    return next(iter(h.suspended.rows.values()))


def test_round_trip_is_exact():
    row = _suspended_state()
    state = decode(PipelineState, json.loads(row))
    assert json.dumps(encode(state)) == row
    assert state.plan_result.plan.steps[0].params["tags"] == ("x",)


def test_wrong_types_are_rejected():
    data = json.loads(_suspended_state())
    data["execution_context"]["tenant_id"] = 42
    with pytest.raises(TypeError):
        decode(PipelineState, data)


def test_unknown_enum_value_is_rejected():
    step = encode(_decoded_step())
    step["mutation"] = "DROP"
    with pytest.raises(ValueError):
        decode(Step, step)


def _decoded_step() -> Step:
    return decode(PipelineState, json.loads(_suspended_state())).plan_result.plan.steps[0]
