"""S12 entry checks (gate §7.1 items 1-5b, 7) for single-step and multi-step plans."""
import asyncio
import dataclasses

import pytest

from contracts.stage_outputs import StepOutputReference, StepParameterBinding, ValidationResult
from engine.control_plane.pipeline_state_runner import build_pipeline
from engine.stages.s12_entry import checks
from engine.stages.s12_entry.checks import check_entry, references_another_step
from tests.fixtures.multi import ChainModel, chain_deps
from tests.fixtures.pipeline import StaticActivation, make_entry, make_pipeline_deps
from tests.fixtures.scenarios import make_scenario

ENTRY = {"message": "x", "conversation_id": "conv-1", "connection_id": "conn-1"}
CHAIN = [("contact.create", {"name": "Ana"}), ("email.send", {"to": "a@x.com"})]


class Bindings:
    """Fixture BindingVersionReader: version per binding id (default bind-v3), None = gone."""
    def __init__(self, versions=None, default="bind-v3", error=None):
        self.versions, self.default, self.error, self.calls = versions or {}, default, error, []

    async def binding_version(self, binding_id):
        self.calls.append(binding_id)
        if self.error:
            raise self.error
        return self.versions.get(binding_id, self.default)


def _state(chain=False):
    """A state that S11 certified."""
    if chain:
        deps = chain_deps(ChainModel(CHAIN))
    else:
        deps = make_pipeline_deps(make_scenario())
    result = asyncio.run(build_pipeline(deps).run(make_entry(ENTRY)))
    assert result.status.value == "NORMAL" and result.final_stage == "S11", result.reason
    return result.final_state


def _check(state, bindings=None, activation=None):
    d = asyncio.run(check_entry(state, bindings=bindings or Bindings(), activation=activation or StaticActivation()))
    return d.allowed, d.reason


def _mutate(state, **changes):
    return dataclasses.replace(state, **changes)


def _ctx(state, **changes):
    return _mutate(state, execution_context=dataclasses.replace(state.execution_context, **changes))


@pytest.mark.parametrize("chain", [False, True])
def test_a_certified_plan_is_admitted(chain):
    assert _check(_state(chain)) == (True, None)


# ---- item 1 / 1a / 2 -------------------------------------------------------------------------

def test_item_1_the_plan_must_have_passed_s11():
    s = _state()
    assert _check(_mutate(s, validation_result=None)) == (False, "plan_not_validated")
    assert _check(_mutate(s, validation_result=ValidationResult(False, ("x",)))) == (False, "plan_not_validated")
    assert _check(_mutate(s, execution_manifest=None)) == (False, "plan_not_validated")


@pytest.mark.parametrize("field", ["task_id", "workspace_id", "conversation_id", "user_id", "tenant_id",
                                   "trace_id", "request_id"])
def test_item_1a_every_value_execution_runs_needs_must_exist(field):
    assert _check(_ctx(_state(), **{field: None})) == (False, "context_incomplete")
    assert _check(_ctx(_state(), **{field: ""})) == (False, "context_incomplete")


def test_item_1a_a_run_without_a_conversation_is_denied():
    s = asyncio.run(build_pipeline(make_pipeline_deps(make_scenario())).run(
        make_entry({"message": "x", "connection_id": "c"}))).final_state
    assert _check(s) == (False, "context_incomplete")


def test_item_2_authorisation_must_be_recorded_and_match_the_manifest():
    s = _state()
    assert _check(_ctx(s, auth_passed=False)) == (False, "authorization_missing")
    assert _check(_ctx(s, auth_result_id=None)) == (False, "authorization_missing")
    assert _check(_ctx(s, auth_result_id="another-id")) == (False, "authorization_missing")


# ---- item 3 ----------------------------------------------------------------------------------

def test_item_3_exactly_one_of_the_singular_binding_and_the_per_step_bindings():
    single, chain = _state(), _state(chain=True)
    assert _check(_mutate(single, frozen_binding_identity=None)) == (False, "binding_missing")
    assert _check(_mutate(chain, frozen_bindings=None)) == (False, "binding_missing")
    assert _check(_mutate(chain, frozen_binding_identity=chain.frozen_bindings[0])) == (False, "binding_missing")
    assert _check(_mutate(single, frozen_bindings=(single.frozen_binding_identity,) * 2)) == (False, "binding_missing")


def test_item_3_a_chain_whose_steps_do_not_map_onto_its_bindings_is_refused():
    chain = _state(chain=True)
    graph = chain.graph_analysis
    broken = tuple({**s, "binding_index": 7} for s in graph.execution_steps)
    assert _check(_mutate(chain, graph_analysis=dataclasses.replace(graph, execution_steps=broken))) == \
        (False, "binding_missing")


# ---- item 4 / 5 / 5a -------------------------------------------------------------------------

def test_item_4_only_join_mode_all_runs():
    s = _state()
    plan = dataclasses.replace(s.plan.plan, join_mode="any")
    assert _check(_mutate(s, plan=dataclasses.replace(s.plan, plan=plan))) == (False, "join_mode_unsupported")


def _with_plan(s, plan, rehash=False, manifest_hash=None):
    from contracts.plan_hash import canonical_plan_digest
    h = canonical_plan_digest(plan) if rehash else s.plan.plan_hash
    result = dataclasses.replace(s.plan, plan=plan, plan_hash=h)
    manifest = dataclasses.replace(s.execution_manifest, plan_hash=manifest_hash or h) if manifest_hash or rehash else s.execution_manifest
    return _mutate(s, plan=result, execution_manifest=manifest)


@pytest.mark.parametrize("chain", [False, True])
def test_item_5_a_changed_plan_is_denied_whichever_hash_was_updated(chain):
    s = _state(chain)
    steps = list(s.plan.plan.steps)
    steps[0] = dataclasses.replace(steps[0], cost=steps[0].cost + 1)
    plan = dataclasses.replace(s.plan.plan, steps=tuple(steps))
    assert _check(_with_plan(s, plan)) == (False, "plan_integrity")                       # nobody re-hashed
    only_s9 = dataclasses.replace(s, plan=dataclasses.replace(
        s.plan, plan=plan, plan_hash=__import__("contracts.plan_hash", fromlist=["x"]).canonical_plan_digest(plan)))
    assert _check(only_s9) == (False, "plan_integrity")                                    # manifest still has the old hash


@pytest.mark.parametrize("value,expected", [
    ({"id": "abc"}, False), ("hello ${name}", False), ("total $5", False), (7, False), ({"a": ["b", 1]}, False),
    ("${steps.1.id}", True), ("{{ steps.1.contact_id }}", True), ("use step-1.output please", True),
    ("$step:1", True), ({"step_id": "step-1", "output_field": "id"}, True),
    ({"nested": [{"deep": "{{steps[1].id}}"}]}, True),
    (StepOutputReference("step-1", "id", "str"), True),
    (StepParameterBinding("step-2", "p", StepOutputReference("step-1", "id", "str")), True),
])
def test_item_5a_detects_references_to_another_steps_output(value, expected):
    assert references_another_step(value) is expected


def test_item_5a_too_deep_to_inspect_counts_as_a_reference():
    deep = "x"
    for _ in range(40):
        deep = {"a": deep}
    assert references_another_step(deep) is True


@pytest.mark.parametrize("chain", [False, True])
def test_item_5a_a_plan_with_a_step_output_reference_is_denied_even_when_hashed_consistently(chain):
    s = _state(chain)
    steps = list(s.plan.plan.steps)
    steps[-1] = dataclasses.replace(steps[-1], params={"to": "${steps.1.email}"})
    plan = dataclasses.replace(s.plan.plan, steps=tuple(steps))
    assert _check(_with_plan(s, plan, rehash=True)) == (False, "data_flow_unsupported")


# ---- item 5b ---------------------------------------------------------------------------------

def test_item_5b_a_single_binding_is_read_once_and_its_version_must_match():
    s = _state()
    reader = Bindings()
    assert _check(s, reader) == (True, None)
    assert reader.calls == [s.frozen_binding_identity.binding_id]
    assert _check(s, Bindings(default="bind-v4")) == (False, "binding_version_mismatch")
    assert _check(s, Bindings(versions={s.frozen_binding_identity.binding_id: None})) == \
        (False, "binding_version_mismatch")                                        # row gone / inactive


def test_item_5b_every_distinct_binding_of_a_chain_is_read_once_and_any_mismatch_denies():
    s = _state(chain=True)
    ids = [b.binding_id for b in s.frozen_bindings]
    reader = Bindings()
    assert _check(s, reader) == (True, None)
    assert reader.calls == ids
    assert _check(s, Bindings(versions={ids[1]: "bind-v9"})) == (False, "binding_version_mismatch")
    assert _check(s, Bindings(versions={ids[0]: None})) == (False, "binding_version_mismatch")


def test_item_5b_a_repeated_binding_is_read_only_once():
    from tests.stages.test_m2a_chain import run_chain
    s = run_chain([("contact.create", {"items": [{}, {}]}), ("email.send", {})])[0].final_state
    # give S9/S11 a conversation so the run reaches the entry check
    s = _ctx(s, conversation_id="conv-1")
    reader = Bindings()
    assert len(s.plan.plan.steps) == 3 and _check(s, reader) == (True, None)
    assert len(reader.calls) == 2 and len(set(reader.calls)) == 2


def test_item_5b_an_unreadable_or_missing_registry_denies():
    s = _state()
    assert _check(s, Bindings(error=RuntimeError("down"))) == (False, "binding_unavailable")
    assert asyncio.run(check_entry(s, bindings=None, activation=StaticActivation())).reason == "binding_unavailable"


# ---- item 7 ----------------------------------------------------------------------------------

def test_item_7_pause_and_scheduled_activation_reasons():
    s = _state()
    for attr, value, reason in [("tenant_paused_until", 10**12, "tenant_paused"),
                                ("workspace_paused_until", 10**12, "workspace_paused"),
                                ("tenant_activation_at", 10**12, "not_yet_active"),
                                ("workspace_activation_at", 10**12, "not_yet_active")]:
        activation = StaticActivation()
        setattr(activation, attr, value)
        assert _check(s, activation=activation) == (False, reason), attr


def test_item_7_an_unreadable_or_missing_activation_state_denies():
    s = _state()
    broken = StaticActivation()
    broken.error = RuntimeError("down")
    assert _check(s, activation=broken) == (False, "activation_state_unavailable")
    assert asyncio.run(check_entry(s, bindings=Bindings(), activation=None)).reason == "activation_state_unavailable"


# ---- order and purity ------------------------------------------------------------------------

def test_the_first_failing_item_decides():
    s = _ctx(_state(), auth_passed=False, conversation_id=None)          # 1a and 2 both fail
    assert _check(s, Bindings(error=RuntimeError("x"))) == (False, "context_incomplete")
    paused = StaticActivation()
    paused.tenant_paused_until = 10**12
    assert _check(_state(), Bindings(default="other"), paused) == (False, "binding_version_mismatch")  # 5b before 7


def test_the_check_reads_the_registry_and_activation_only_after_the_cheap_checks_pass():
    reader, activation = Bindings(), StaticActivation()
    _check(_ctx(_state(), auth_passed=False), reader, activation)
    assert reader.calls == []


def test_denials_are_reported_not_raised_and_the_state_is_untouched():
    s = _state()
    before = dataclasses.asdict(s)
    assert _check(_mutate(s, validation_result=None))[0] is False
    assert dataclasses.asdict(s) == before
