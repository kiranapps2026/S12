"""S5 binding and risk, S6 task profile, S7 routing table."""
from __future__ import annotations

import pytest

from supragents.contracts.outputs import TaskProfile
from supragents.contracts.vocabulary import GraphType, Mutation, PathDecision, StageStatus, TruthState
from supragents.stages.s07_path import route
from tests.builders import Harness
from tests.fakes.ports import FakePolicy, FakePolicyVersions, intent_json
from tests.fakes.registry import binding, capability, kernel_op


def _state(stage: str, answer: str, setup=None, **harness):
    h = Harness(**harness)
    if setup:
        setup(h.registry)
    h.say(answer)
    return h.run_stage(stage, h.state_before(stage))


def _report_capability(registry, *bindings, op_truth=TruthState.PRODUCTION_ENABLED):
    cap = capability("report.run", Mutation.READ, 0.2)
    registry.capabilities.append(cap)
    registry.kernel_ops["op.a"] = kernel_op("op.a", Mutation.WRITE, risk=0.4, truth=op_truth)
    registry.kernel_ops["op.b"] = kernel_op("op.b", Mutation.READ)
    registry.bindings.extend(binding(cap, **spec) for spec in bindings)


def test_s5_selection_is_priority_then_created_then_id():
    def setup(registry):
        _report_capability(registry,
                           dict(op_id="op.b", binding_id="z", priority=2, created_at=0.0),
                           dict(op_id="op.a", binding_id="y", priority=1, created_at=5.0),
                           dict(op_id="op.b", binding_id="x", priority=1, created_at=5.0),
                           dict(op_id="op.a", binding_id="w", priority=0, active=False))
    frozen = _state("S5", intent_json("report.run"), setup).frozen_binding
    assert frozen.binding_id == "x"


def test_s5_risk_and_mutation_take_the_maximum_of_registry_inputs():
    def setup(registry):
        _report_capability(registry, dict(op_id="op.a", binding_id="a"))
    frozen = _state("S5", intent_json("report.run"), setup).frozen_binding
    assert (frozen.effective_risk, frozen.effective_mutation) == (0.4, Mutation.WRITE)


@pytest.mark.parametrize("bindings, op_truth, reason", [
    ((), TruthState.PRODUCTION_ENABLED, "provider_unavailable"),
    ((dict(op_id="op.a", active=False),), TruthState.PRODUCTION_ENABLED, "provider_unavailable"),
    ((dict(op_id="op.a"),), TruthState.DEPRECATED, "kernel_operation_unavailable"),
    ((dict(op_id="missing"),), TruthState.PRODUCTION_ENABLED, "kernel_operation_unavailable"),
])
def test_s5_unresolvable_binding_clarifies(bindings, op_truth, reason):
    state = _state("S5", intent_json("report.run"),
                   lambda r: _report_capability(r, *bindings, op_truth=op_truth))
    assert (state.halt.status, state.halt.reason) == (StageStatus.CLARIFY, reason)


def test_s5_records_policy_versions_on_the_context():
    context = _state("S5", intent_json("contact.list")).execution_context
    assert (context.tenant_policy_version_id, context.workspace_policy_version_id,
            context.policy_version_id) == ("tpv-5", "wpv-2", "pv-8")


@pytest.mark.parametrize("source", [FakePolicyVersions(error=True), FakePolicyVersions(policy_version_id="")])
def test_s5_missing_policy_versions_fail_closed(source):
    state = _state("S5", intent_json("contact.list"), policy_versions=source)
    assert (state.halt.status, state.halt.reason) == (StageStatus.ERROR, "policy_versions_unavailable")
    assert state.execution_context.policy_version_id is None


@pytest.mark.parametrize("answer, cost, confirm", [
    (intent_json("contact.list"), 1, False),
    (intent_json("contact.create"), 3, False),
    (intent_json("contact.create", items=[{"n": i} for i in range(5)]), 15, False),
    (intent_json("contact.delete"), 5, True),
    (intent_json("email.send"), 3, True),
])
def test_s6_cost_and_confirmation(answer, cost, confirm):
    profile = _state("S6", answer).task_profile
    assert (profile.cost, profile.requires_confirmation) == (cost, confirm)
    assert profile.risk == _state("S6", answer).frozen_binding.effective_risk


def _profile(graph: GraphType, risk: float) -> TaskProfile:
    return TaskProfile("i", ("c",), graph, 1, (Mutation.READ,), risk, 1, False, "s", ("p",))


@pytest.mark.parametrize("graph, risk, confidence, threshold, expected", [
    (GraphType.SIMPLE, 0.1, 0.95, 0.0, (PathDecision.DENY, "risk_threshold_invalid")),
    (GraphType.SIMPLE, 0.95, 0.95, 0.95, (PathDecision.DENY, "risk_above_threshold")),
    (GraphType.SIMPLE, 0.1, 0.49, 0.95, (PathDecision.CLARIFY, "low_confidence")),
    (GraphType.COMPLEX, 0.1, 0.95, 0.95, (PathDecision.CLARIFY, "complex_not_supported")),
    (GraphType.SIMPLE, 0.3, 0.9, 0.95, (PathDecision.FAST, None)),
    (GraphType.SIMPLE, 0.31, 0.95, 0.95, (PathDecision.WORKFLOW, None)),
    (GraphType.CHAIN, 0.6, 0.7, 0.95, (PathDecision.WORKFLOW, None)),
    (GraphType.CHAIN, 0.1, 0.69, 0.95, (PathDecision.CLARIFY, "uncertain_intent")),
])
def test_s7_routing_table(graph, risk, confidence, threshold, expected):
    assert route(_profile(graph, risk), confidence, threshold) == expected


def test_s7_unreadable_policy_denies():
    state = _state("S7", intent_json("contact.list"), policy=FakePolicy(error=True))
    assert (state.halt.status, state.halt.reason) == (StageStatus.DENY, "policy_unavailable")
