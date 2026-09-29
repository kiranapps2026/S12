"""plan_digest is deterministic and covers every field of the plan."""
from __future__ import annotations

import dataclasses

import pytest

from supragents.contracts.frozen_json import freeze
from supragents.contracts.outputs import Plan, Step
from supragents.contracts.plan_hash import plan_digest
from supragents.contracts.vocabulary import Mutation, RetrySafety

STEP = Step("step-1", "op", freeze({"b": [1, {"c": 2}], "a": "x"}), (), Mutation.READ, 0.1, 1, 30,
            RetrySafety.SAFE, None)
PLAN = Plan("plan-1", "exec-1", (STEP,), "all", 1, 100.0)


def test_digest_is_stable_and_key_order_independent():
    reordered = dataclasses.replace(STEP, params=freeze({"a": "x", "b": [1, {"c": 2}]}))
    assert plan_digest(PLAN) == plan_digest(dataclasses.replace(PLAN, steps=(reordered,)))
    assert len(plan_digest(PLAN)) == 64


@pytest.mark.parametrize("change", [
    {"id": "plan-2"}, {"execution_id": "exec-2"}, {"budget_required": 2}, {"created_at": 101.0},
    {"steps": (dataclasses.replace(STEP, params=freeze({"a": "y"})),)},
    {"steps": (dataclasses.replace(STEP, mutation=Mutation.DELETE),)},
])
def test_any_change_changes_the_digest(change):
    assert plan_digest(dataclasses.replace(PLAN, **change)) != plan_digest(PLAN)


def test_frozen_json_rejects_non_json_and_blocks_mutation():
    with pytest.raises(TypeError):
        freeze({"when": object()})
    with pytest.raises(TypeError):
        STEP.params["a"] = "z"
