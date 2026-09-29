"""S3 capability discovery and S4 graph classification."""
from __future__ import annotations

import pytest

from supragents.contracts.vocabulary import GraphType, Mutation, StageStatus, TruthState
from tests.builders import Harness
from tests.fakes.ports import intent_json
from tests.fakes.registry import capability, kernel_op


def _run_to(stage: str, answer: str, registry_setup=None):
    h = Harness()
    if registry_setup:
        registry_setup(h.registry)
    h.say(answer)
    return h.run_stage(stage, h.state_before(stage))


def test_s3_selects_the_single_enabled_capability():
    state = _run_to("S3", intent_json("contact.create"))
    assert state.capability_match.capability.capability_id == "cap.contact.create"


def test_s3_disabled_capability_clarifies():
    def setup(registry):
        registry.add(capability("report.run", Mutation.READ, truth=TruthState.REVIEW), kernel_op("r.run", Mutation.READ))
    state = _run_to("S3", intent_json("report.run"), setup)
    assert (state.halt.status, state.halt.reason) == (StageStatus.CLARIFY, "capability_not_enabled")


def test_s3_two_enabled_capabilities_clarify():
    def setup(registry):
        registry.add(capability("contact.list", Mutation.READ, suffix=".v2"), kernel_op("crm.list2", Mutation.READ))
    state = _run_to("S3", intent_json("contact.list"), setup)
    assert state.halt.reason == "ambiguous_capability"


@pytest.mark.parametrize("items, graph_type, count", [
    (None, GraphType.SIMPLE, 1),
    ([{"n": 1}, {"n": 2}], GraphType.CHAIN, 2),
    ([{"n": i} for i in range(5)], GraphType.CHAIN, 5),
    ([{"n": i} for i in range(6)], GraphType.COMPLEX, 6),
])
def test_s4_step_count_sets_graph_type(items, graph_type, count):
    answer = intent_json("contact.create") if items is None else intent_json("contact.create", items=items)
    graph = _run_to("S4", answer).graph_analysis
    assert (graph.graph_type, graph.step_count) == (graph_type, count)


@pytest.mark.parametrize("items", [[], ["x"], "not-a-list"])
def test_s4_malformed_items_clarify(items):
    state = _run_to("S4", intent_json("contact.create", items=items))
    assert (state.halt.status, state.halt.reason) == (StageStatus.CLARIFY, "invalid_items")
