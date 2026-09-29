"""
GOLDEN TEST FILE (OWNER). Pinned by hash. The agent edits it only on the owner's explicit
instruction; the amendments below were made on such an instruction.
AMENDMENTS: manifest versions come from the frozen binding and the ExecutionContext (never constants);
a consumed confirmation for THIS plan hash is required; unknown dependencies and duplicate step
ids are dag_invalid; a denied plan writes validation_result and no manifest (status DENY).
Rulings: runbook R-S (S11 checks, in order: binding, plan hash, confirmation, budget, DAG,
non-empty), ValidationResult(is_valid, errors).

Fixture contract: see test_s6_task_profile.py and test_s10_confirmation.py headers.
run_stage returns the PipelineState produced by the real handler; on denial S11 writes
validation_result and leaves execution_manifest as None.
"""
import dataclasses

from contracts.plan_hash import canonical_plan_digest
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import run_stage, state_ready_for, tamper

LOW = dict(mutation="W", risk=0.2, steps=3, graph="chain", confidence=0.8)


def _with_plan(state, plan, rehash):
    s9 = state.get_stage_output("S9")
    new = dataclasses.replace(s9, plan=plan,
                              plan_hash=canonical_plan_digest(plan) if rehash else s9.plan_hash)
    return tamper(state, plan=new)


def _deny_code(out):
    vr = out.validation_result
    assert out.execution_manifest is None
    assert vr.is_valid is False
    return tuple(vr.errors)


def _setup():
    sc = make_scenario(**LOW)
    return sc, state_ready_for("S11", sc)


def test_s11_valid_plan_creates_manifest():
    sc, state = _setup()
    out = run_stage("S11", state, sc)
    assert out.validation_result.is_valid is True
    assert out.execution_manifest.plan_hash == state.get_stage_output("S9").plan_hash


def test_s11_kernel_op_mismatch_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    steps = (dataclasses.replace(plan.steps[0], kernel_op_id="other.op"),) + tuple(plan.steps[1:])
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, steps=steps), rehash=False), sc)
    assert _deny_code(out) == ("binding_mismatch",)


def test_s11_risk_mismatch_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    steps = (dataclasses.replace(plan.steps[0], risk=0.01),) + tuple(plan.steps[1:])
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, steps=steps), rehash=False), sc)
    assert _deny_code(out) == ("binding_mismatch",)


def test_s11_plan_hash_mismatch_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, budget_reserved=plan.budget_reserved + 1),
                                      rehash=False), sc)
    assert _deny_code(out) == ("plan_hash_mismatch",)


def test_s11_empty_plan_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, steps=()), rehash=True), sc)
    assert _deny_code(out) == ("plan_empty",)


def test_s11_negative_budget_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, budget_reserved=-1), rehash=True), sc)
    assert _deny_code(out) == ("budget_invalid",)


def test_s11_cycle_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    first, *rest = plan.steps
    last = rest[-1]
    steps = (dataclasses.replace(first, depends_on=(last.id,)),) + tuple(rest)
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, steps=steps), rehash=True), sc)
    assert _deny_code(out) == ("dag_invalid",)


def test_s11_unconsumed_confirmation_denies():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    state = state_ready_for("S11", sc)            # S10 created a pending confirmation
    assert state.confirmation.required is True
    out = run_stage("S11", state, sc)             # never consumed
    assert _deny_code(out) == ("confirmation_mismatch",)


def test_s11_manifest_versions_come_from_the_binding_and_the_context():
    sc, state = _setup()
    fb, ctx = state.frozen_binding_identity, state.execution_context
    m = run_stage("S11", state, sc).execution_manifest
    assert (m.capability_version, m.binding_version, m.risk_policy_version, m.authorization_version) == (
        fb.capability_version, fb.binding_version, fb.risk_policy_version, fb.authorization_version)
    assert m.policy_version == ctx.policy_version_id and m.policy_version
    assert (m.execution_id, m.trace_id) == (state.get_stage_output("S9").execution_id, ctx.trace_id)


def test_s11_denial_status_and_reason():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, budget_reserved=-1), rehash=True), sc)
    assert (str(out.stage_status).lower(), out.deny_reason) == ("deny", "budget_invalid")


def test_s11_unknown_dependency_denies():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    steps = (dataclasses.replace(plan.steps[0], depends_on=("no-such-step",)),) + tuple(plan.steps[1:])
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, steps=steps), rehash=True), sc)
    assert _deny_code(out) == ("dag_invalid",)


def test_s11_duplicate_step_ids_deny():
    sc, state = _setup()
    plan = state.get_stage_output("S9").plan
    steps = (plan.steps[0], dataclasses.replace(plan.steps[1], id=plan.steps[0].id)) + tuple(plan.steps[2:])
    out = run_stage("S11", _with_plan(state, dataclasses.replace(plan, steps=steps), rehash=True), sc)
    assert _deny_code(out) == ("dag_invalid",)


def _consumed(state, sc, plan_hash=None):
    import asyncio
    from contracts.execution_manifest import ConfirmationOutcome
    from engine.stages.s10_confirmation.handler import resume_confirmation
    resumed = asyncio.run(resume_confirmation(state, sc.confirmation_store, user_id=state.execution_context.user_id))
    assert str(resumed.stage_status).lower() == "normal"
    if plan_hash is not None:
        c = dataclasses.replace(resumed.confirmation.confirmation, plan_hash=plan_hash)
        resumed = tamper(resumed, confirmation=ConfirmationOutcome(True, c))
    return resumed


def test_s11_consumed_confirmation_for_this_plan_allows_the_manifest():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    state = state_ready_for("S11", sc)
    out = run_stage("S11", _consumed(state, sc), sc)
    assert out.validation_result.is_valid is True
    assert out.execution_manifest.plan_hash == state.get_stage_output("S9").plan_hash


def test_s11_consumed_confirmation_for_another_plan_denies_tampered():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    state = state_ready_for("S11", sc)
    out = run_stage("S11", _consumed(state, sc, plan_hash="0" * 64), sc)
    assert _deny_code(out) == ("confirmation_mismatch",)
