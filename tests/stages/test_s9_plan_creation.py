"""
GOLDEN TEST FILE (OWNER). Pinned by hash; the agent must not edit it.
Rulings: runbook R-U (single binding: steps take kernel_op_id/risk/mutation from the
frozen binding), R-P (join_mode "all"), plan hash via canonical_plan_digest.
Fixture contract: see tests/stages/test_s6_task_profile.py header.
"""
import dataclasses
import uuid

from contracts.plan_hash import canonical_plan_digest
from contracts.stage_outputs import PlanCreationResult
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import run_stage, state_ready_for, tamper


def test_s9_plan_shape():
    sc = make_scenario(mutation="W", risk=0.2, steps=3, graph="chain", confidence=0.8)
    state = state_ready_for("S9", sc)
    out = run_stage("S9", state, sc).get_stage_output("S9")
    fb, ctx = state.frozen_binding_identity, state.execution_context
    assert isinstance(out, PlanCreationResult)
    uuid.UUID(out.execution_id)
    uuid.UUID(out.plan.id)
    assert out.execution_id != ctx.request_id
    assert out.plan.join_mode == "all"
    assert len(out.plan.steps) == 3
    for i, step in enumerate(out.plan.steps):
        assert (step.kernel_op_id, step.risk, step.mutation) == (
            fb.kernel_op_id, fb.effective_risk, fb.effective_mutation)
        assert tuple(step.depends_on) == (() if i == 0 else (out.plan.steps[i - 1].id,))
    assert out.plan_hash == canonical_plan_digest(out.plan)


def test_s9_uses_frozen_risk_when_task_profile_tampered():
    sc = make_scenario(mutation="D", risk_floor=0.2, risk_rule=0.9, confidence=0.95)
    state = state_ready_for("S9", sc)
    assert state.frozen_binding_identity.effective_risk == 0.9
    state = tamper(state, task_profile=dataclasses.replace(state.task_profile, risk=0.1))
    out = run_stage("S9", state, sc).get_stage_output("S9")
    assert all(step.risk == 0.9 for step in out.plan.steps)


def test_s9_plan_hash_changes_with_execution_inputs():
    sc_a = make_scenario(steps=1)
    sc_b = make_scenario(steps=2, graph="chain", confidence=0.8)
    a = run_stage("S9", state_ready_for("S9", sc_a), sc_a).get_stage_output("S9")
    b = run_stage("S9", state_ready_for("S9", sc_b), sc_b).get_stage_output("S9")
    assert a.plan_hash != b.plan_hash
