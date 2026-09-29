"""M2a: heterogeneous linear chains (rulings R-AB..R-AL). Single-capability behaviour is covered
by the existing golden files and must not change; these tests cover only the new path."""
import asyncio
import dataclasses

import pytest

from contracts.codec import decode_state, encode_state
from contracts.stage_registry import StageStatus
from engine.stages.s6_task_profile_assembly.handler import CROSS_PROVIDER_CONFIRMATION
from engine.stages.s7_path_decision.handler import MULTI_STEP_CONFIDENCE_FLOOR
from tests.fixtures.deps import ConfigurableAuthState, make_s8_deps
from tests.fixtures.multi import Cap, run_chain

CREATE_THEN_EMAIL = [("contact.create", {"name": "Ana", "email": "ana@x.com"}),
                     ("email.send", {"to": "ana@x.com", "subject": "Invoice"})]


def _outcome(result):
    return result.status.value, result.final_stage, result.reason


# ---- the happy path: two different capabilities, one plan ----------------------------------------

def test_two_different_capabilities_become_a_two_step_chain():
    result, _ = run_chain(CREATE_THEN_EMAIL)
    state = result.final_state
    assert _outcome(result) == ("NORMAL", "S11", None)
    assert state.capability_match is None and state.frozen_binding_identity is None   # R-AB
    assert [b.kernel_op_id for b in state.bindings] == ["op.contact.create", "op.email.send"]
    assert [s.kernel_op_id for s in state.plan.plan.steps] == ["op.contact.create", "op.email.send"]
    assert state.graph_analysis.complexity == "chain"
    assert state.path_decision.decision.value == "workflow"


def test_each_step_carries_its_own_properties_and_bound_parameters():
    steps = run_chain(CREATE_THEN_EMAIL)[0].final_state.plan.plan.steps
    a, b = steps
    assert (a.mutation, a.risk, a.cost) == ("W", 0.2, 3)
    assert (b.mutation, b.risk, b.cost) == ("W", 0.3, 2)
    assert a.params == {"name": "Ana", "email": "ana@x.com"}            # R-AE: bound at S9
    assert b.params == {"to": "ana@x.com", "subject": "Invoice"}
    assert (a.depends_on, b.depends_on) == ((), (a.id,))


def test_profile_risk_is_the_max_and_cost_the_sum():
    state = run_chain(CREATE_THEN_EMAIL)[0].final_state
    p = state.task_profile
    assert (p.risk, p.cost, p.steps_estimated) == (0.3, 5, 2)
    assert p.capabilities == ("cap.contact.create", "cap.email.send")
    assert p.mutations == ("W", "W") and p.providers == ("crm", "mail")
    assert state.plan.plan.budget_reserved == 5 == sum(s.cost for s in state.plan.plan.steps)


def test_the_model_never_decides_properties_only_which_registered_intents():
    steps = [("contact.create", {"risk": 0.0, "mutation": "R", "cost": 0, "kernel_op_id": "evil"}),
             ("email.send", {})]
    state = run_chain(steps)[0].final_state
    a = state.plan.plan.steps[0]
    assert (a.mutation, a.risk, a.cost, a.kernel_op_id) == ("W", 0.2, 3, "op.contact.create")


# ---- S2: what the model may say ------------------------------------------------------------------

def test_a_single_intent_answer_is_unchanged():
    from tests.fixtures.multi import ChainModel
    result, _ = run_chain(None, raw='{"intent": "contact.list", "confidence": 0.95, "parameters": {}}')
    state = result.final_state
    assert _outcome(result) == ("NORMAL", "S11", None)
    assert state.frozen_binding_identity is not None and state.frozen_bindings is None
    assert state.intent_result.steps == ()


def test_a_one_element_steps_list_is_a_single_step_plan():
    result, _ = run_chain([("contact.list", {})])
    assert result.final_state.frozen_binding_identity is not None
    assert result.final_state.frozen_bindings is None


@pytest.mark.parametrize("steps,reason", [
    ([("contact.create", {}), ("unknown", {})], "intent_unclear"),
    ([("contact.create", {}), ("prohibited", {})], "intent_prohibited"),
])
def test_unknown_or_prohibited_inside_a_chain_stops_it(steps, reason):
    result, _ = run_chain(steps)
    assert result.reason == reason and result.final_stage == "S2"


def test_an_intent_the_registry_does_not_offer_is_retried_then_refused():
    result, deps = run_chain([("contact.create", {}), ("wire.money", {})])
    assert _outcome(result) == ("CLARIFY", "S2", "intent_unparseable")
    assert len(deps.intent_model.calls) == 2


@pytest.mark.parametrize("raw", [
    '{"steps": [], "confidence": 0.9}', '{"steps": "x", "confidence": 0.9}',
    '{"steps": [1, 2], "confidence": 0.9}', '{"steps": [{"intent": "contact.create"}]}',
    '{"steps": [{"intent": "contact.create", "parameters": []}, {"intent": "email.send"}], "confidence": 0.9}',
])
def test_malformed_steps_are_never_accepted(raw):
    assert run_chain(None, raw=raw)[0].reason == "intent_unparseable"


def test_parameters_are_bounded_and_plain_json():
    big = {"body": "x" * 2100}
    assert run_chain([("contact.create", big), ("email.send", {})])[0].reason == "intent_unparseable"


# ---- R-AC / R-AK: at most 5 steps, items expand --------------------------------------------------

def test_five_steps_are_allowed_and_six_are_not():
    five = [("contact.list", {})] * 5
    assert _outcome(run_chain(five)[0])[:2] == ("NORMAL", "S11")
    assert _outcome(run_chain(five + [("contact.list", {})])[0]) == ("CLARIFY", "S2", "too_many_steps")
    assert run_chain([("contact.list", {})] * 9)[0].reason == "too_many_steps"


def test_items_expand_to_n_steps_within_the_cap():
    steps = [("contact.create", {"items": [{"n": "a"}, {"n": "b"}]}), ("email.send", {"to": "x"})]
    plan = run_chain(steps)[0].final_state.plan.plan
    assert [s.params for s in plan.steps] == [{"item": {"n": "a"}}, {"item": {"n": "b"}}, {"to": "x"}]
    assert [s.kernel_op_id for s in plan.steps] == ["op.contact.create"] * 2 + ["op.email.send"]
    assert [s.depends_on for s in plan.steps] == [(), ("step-1",), ("step-2",)]


def test_create_three_then_email_each_is_six_steps_and_is_refused():
    steps = [("contact.create", {"items": [{}, {}, {}]}), ("email.send", {"items": [{}, {}, {}]})]
    assert _outcome(run_chain(steps)[0]) == ("CLARIFY", "S2", "too_many_steps")


# ---- S3/S7: ambiguity and confidence -------------------------------------------------------------

def test_an_intent_with_several_candidate_capabilities_is_ambiguous():
    from tests.fixtures.multi import DEFAULT_CAPS
    caps = {**DEFAULT_CAPS, "email.send": Cap("W", 0.3, 2, "mail", alternatives=2)}
    assert _outcome(run_chain(CREATE_THEN_EMAIL, caps=caps)[0]) == ("CLARIFY", "S7", "ambiguous_capability")


def test_a_step_with_no_capability_asks_the_user():
    from tests.fixtures.multi import DEFAULT_CAPS
    caps = {k: v for k, v in DEFAULT_CAPS.items() if k != "email.send"}
    # email.send is no longer offered, so the model's answer is refused before S3
    assert run_chain(CREATE_THEN_EMAIL, caps=caps)[0].reason == "intent_unparseable"


def test_the_multi_step_confidence_floor_is_higher_than_the_single_step_one():
    assert MULTI_STEP_CONFIDENCE_FLOOR == 0.85
    assert _outcome(run_chain(CREATE_THEN_EMAIL, confidence=0.85)[0])[:2] == ("NORMAL", "S11")
    assert _outcome(run_chain(CREATE_THEN_EMAIL, confidence=0.84)[0]) == ("CLARIFY", "S7", "low_confidence")
    # the same confidence is fine for one step (>= 0.7 workflow)
    assert run_chain([("contact.create", {})], confidence=0.75)[0].status is StageStatus.NORMAL


def test_the_riskiest_step_decides_the_risk_threshold():
    from tests.fixtures.multi import DEFAULT_CAPS
    caps = {**DEFAULT_CAPS, "email.send": Cap("W", 0.97, 2, "mail")}
    assert _outcome(run_chain(CREATE_THEN_EMAIL, caps=caps)[0]) == ("DENY", "S7", "risk_above_threshold")


# ---- S6: confirmation ----------------------------------------------------------------------------

def test_any_delete_step_needs_confirmation_and_the_chain_stops_at_s10():
    result, deps = run_chain([("contact.create", {}), ("contact.delete", {"id": "c1"})])
    assert _outcome(result) == ("CLARIFY", "S10", "confirmation_required")
    conf = result.final_state.confirmation.confirmation
    assert [o["kernel_op_id"] for o in conf.operations] == ["op.contact.create", "op.contact.delete"]
    assert conf.operations[1]["params"] == {"id": "c1"}                  # R-AE: the user sees the params
    assert conf.plan_hash == result.final_state.plan.plan_hash


def test_three_distinct_providers_need_confirmation_even_when_all_are_reads():
    assert CROSS_PROVIDER_CONFIRMATION == 3
    two = run_chain([("contact.list", {}), ("report.run", {})])[0]
    three = run_chain([("contact.list", {}), ("report.run", {}), ("email.send", {})])[0]
    assert _outcome(two)[:2] == ("NORMAL", "S11")
    assert _outcome(three) == ("CLARIFY", "S10", "confirmation_required")


def test_total_cost_over_twenty_needs_confirmation():
    from tests.fixtures.multi import DEFAULT_CAPS
    caps = {**DEFAULT_CAPS, "contact.list": Cap("R", 0.1, 11, "crm"), "report.run": Cap("R", 0.1, 10, "crm")}
    assert _outcome(run_chain([("contact.list", {}), ("report.run", {})], caps=caps)[0]) == \
        ("CLARIFY", "S10", "confirmation_required")


# ---- S8: every step is checked -------------------------------------------------------------------

def test_a_grant_missing_for_the_second_step_denies_the_whole_plan():
    auth = ConfigurableAuthState(grants={"cap.email.send": False})
    result, _ = run_chain(CREATE_THEN_EMAIL, s8=make_s8_deps(auth=auth))
    assert _outcome(result) == ("DENY", "S8", "capability_granted_denied")
    assert result.final_state.plan is None


def test_an_open_breaker_for_the_second_provider_denies():
    from tests.fixtures.deps import ConfigurableCircuitBreaker
    class PerProvider(ConfigurableCircuitBreaker):
        def state(self, provider_id):
            return "OPEN" if provider_id == "mail" else "CLOSED"
    result, _ = run_chain(CREATE_THEN_EMAIL, s8=make_s8_deps(breaker=PerProvider()))
    assert _outcome(result) == ("DENY", "S8", "circuit_breaker_open")


def test_the_mutation_policy_is_asked_for_every_step():
    from tests.fixtures.deps import ConfigurableMutationPolicy
    policy = ConfigurableMutationPolicy()
    run_chain([("contact.create", {}), ("contact.list", {})], s8=make_s8_deps(mutation=policy))
    assert [c[1] for c in policy.calls] == [("W", 0.2), ("R", 0.1)]


def test_the_budget_check_sees_the_plan_total():
    seen = []
    class Auth(ConfigurableAuthState):
        def budget_available(self, tenant_id, amount):
            seen.append(amount)
            return True
    run_chain(CREATE_THEN_EMAIL, s8=make_s8_deps(auth=Auth()))
    assert set(seen) == {5}


# ---- S11: per-step binding equality --------------------------------------------------------------

def _through_s10():
    result, deps = run_chain(CREATE_THEN_EMAIL)
    return result.final_state


def _s11(state):
    from engine.stages.s11_plan_validation.handler import handle
    return asyncio.run(handle(state))


def _tamper(state, index, **changes):
    plan_result = state.plan
    steps = list(plan_result.plan.steps)
    steps[index] = dataclasses.replace(steps[index], **changes)
    plan = dataclasses.replace(plan_result.plan, steps=tuple(steps))
    from contracts.plan_hash import canonical_plan_digest
    return dataclasses.replace(state, plan=dataclasses.replace(
        plan_result, plan=plan, plan_hash=canonical_plan_digest(plan)))   # a hash that matches the tampering


@pytest.mark.parametrize("changes", [
    {"kernel_op_id": "op.contact.create"},           # step 2 runs step 1's operation
    {"mutation": "R"}, {"risk": 0.0}, {"cost": 1}, {"depends_on": ()},
])
def test_a_step_that_differs_from_its_own_binding_is_refused_even_with_a_matching_hash(changes):
    state = _tamper(_through_s10(), 1, **changes)
    out = _s11(dataclasses.replace(state, validation_result=None, execution_manifest=None))
    assert out.deny_reason == "binding_mismatch"


def test_swapped_steps_are_refused():
    state = _through_s10()
    plan = state.plan.plan
    a, b = plan.steps
    swapped = dataclasses.replace(plan, steps=(dataclasses.replace(a, kernel_op_id=b.kernel_op_id,
                                                                  mutation=b.mutation, risk=b.risk, cost=b.cost),
                                                dataclasses.replace(b, kernel_op_id=a.kernel_op_id,
                                                                  mutation=a.mutation, risk=a.risk, cost=a.cost)))
    from contracts.plan_hash import canonical_plan_digest
    tampered = dataclasses.replace(state, plan=dataclasses.replace(
        state.plan, plan=swapped, plan_hash=canonical_plan_digest(swapped)))
    out = _s11(dataclasses.replace(tampered, validation_result=None, execution_manifest=None))
    assert out.deny_reason == "binding_mismatch"


def test_a_missing_or_extra_step_is_refused():
    state = _through_s10()
    for steps in (state.plan.plan.steps[:1], state.plan.plan.steps * 2):
        plan = dataclasses.replace(state.plan.plan, steps=steps)
        from contracts.plan_hash import canonical_plan_digest
        tampered = dataclasses.replace(state, plan=dataclasses.replace(
            state.plan, plan=plan, plan_hash=canonical_plan_digest(plan)), validation_result=None,
            execution_manifest=None)
        assert _s11(tampered).deny_reason == "binding_mismatch"


def test_the_plan_hash_changes_when_steps_are_reordered_or_a_binding_changes():
    from contracts.plan_hash import canonical_plan_digest
    a = _through_s10().plan
    reordered = dataclasses.replace(a.plan, steps=tuple(reversed(a.plan.steps)))
    assert canonical_plan_digest(reordered) != a.plan_hash
    other = run_chain([("contact.create", {"name": "Bob"}), ("email.send", {"to": "b"})])[0].final_state.plan
    assert other.plan_hash != a.plan_hash


def test_the_manifest_joins_distinct_versions_only():
    state = _through_s10()
    m = state.execution_manifest
    assert (m.capability_version, m.binding_version) == ("cap-v7", "bind-v3")


# ---- suspend / resume ----------------------------------------------------------------------------

def test_a_suspended_chain_round_trips_through_the_codec_and_holds_no_intent_parameters():
    from engine.control_plane.pipeline_state_runner import _minimized
    result, _ = run_chain([("contact.create", {"name": "Ana"}), ("contact.delete", {"id": "c1"})])
    stored = _minimized(result.final_state)
    assert all(step.parameters == {} for step in stored.intent_result.steps)
    back = decode_state(encode_state(stored))
    assert back == stored and len(back.frozen_bindings) == 2 and len(back.capability_matches) == 2


def test_a_confirmed_chain_runs_to_s11_through_the_runner_reply():
    from engine.control_plane.pipeline_state_runner import build_pipeline
    from tests.fixtures.multi import ChainModel, chain_deps
    from tests.fixtures.pipeline import make_entry
    deps = chain_deps(ChainModel([("contact.create", {}), ("contact.delete", {"id": "c1"})]))
    runner = build_pipeline(deps)
    first = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    cid = first.final_state.confirmation.confirmation.confirmation_id
    done = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert _outcome(done) == ("NORMAL", "S11", None)
    assert done.final_state.execution_manifest.plan_hash == first.final_state.plan.plan_hash
    again = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))          # a second reply is refused
    assert again.status is not StageStatus.NORMAL
