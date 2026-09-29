"""S9 plan, S10 confirmation (ruling R-Z), S11 validation — and ruling R-N guards."""
from __future__ import annotations

import dataclasses

import pytest

from supragents.contracts.outputs import SafetyResult
from supragents.contracts.plan_hash import plan_digest
from supragents.contracts.vocabulary import ConfirmationStatus, StageStatus
from tests.builders import Harness
from tests.fakes.ports import intent_json

OWN_FIELD = {"S9": "plan_result", "S10": "confirmation_check", "S11": "execution_manifest"}


@pytest.mark.parametrize("stage", ["S9", "S10", "S11"])
@pytest.mark.parametrize("tamper", [
    lambda s: dataclasses.replace(s, safety_result=SafetyResult(allowed=False, result_id="r")),
    lambda s: dataclasses.replace(s, execution_context=dataclasses.replace(s.execution_context, auth_passed=False)),
])
def test_stage_requires_safety_passed(stage, tamper):
    h = Harness()
    state = tamper(h.state_before(stage))
    out = h.run_stage(stage, state)
    assert (out.halt.stage, out.halt.status, out.halt.reason) == (stage, StageStatus.DENY, "safety_not_passed")
    assert getattr(out, OWN_FIELD[stage]) is None


def test_s9_plan_is_hashed_and_uses_frozen_binding():
    h = Harness()
    state = h.run_stage("S9", h.state_before("S9"))
    result, frozen = state.plan_result, state.frozen_binding
    assert result.plan_hash == plan_digest(result.plan)
    assert result.plan.created_at == h.clock.current
    step = result.plan.steps[0]
    assert (step.kernel_op_id, step.mutation, step.risk, step.cost) == (
        frozen.kernel_op_id, frozen.effective_mutation, frozen.effective_risk, frozen.cost_per_step)


def _delete_harness() -> Harness:
    h = Harness()
    h.say(intent_json("contact.delete", id="c-1"))
    return h


def test_s10_store_receives_tenant_and_execution_id():
    h = _delete_harness()
    state = h.state_before("S10")
    out = h.run_stage("S10", state)
    assert len(h.confirmations.saved) == 1
    confirmation, tenant_id, execution_id = h.confirmations.saved[0]
    assert tenant_id == state.execution_context.tenant_id
    assert execution_id == state.plan_result.plan.execution_id
    assert confirmation is out.confirmation_check.confirmation
    assert out.confirmation_check.status is ConfirmationStatus.PENDING


def test_s10_confirmation_lists_exact_operations_and_expires_in_five_minutes():
    h = _delete_harness()
    confirmation = h.run_stage("S10", h.state_before("S10")).confirmation_check.confirmation
    assert [dict(op) for op in confirmation.operations] == [
        {"step_id": "step-1", "kernel_op_id": "crm.contact_delete", "mutation": "D", "cost": 5}]
    assert confirmation.expires_at == h.clock.current + 300


def test_s10_read_only_plan_needs_no_confirmation():
    h = Harness()
    out = h.run_stage("S10", h.state_before("S10"))
    assert out.confirmation_check.status is ConfirmationStatus.NOT_REQUIRED
    assert h.confirmations.saved == []


def test_s11_rejects_a_tampered_plan():
    h = Harness()
    state = h.state_before("S11")
    plan = state.plan_result.plan
    tampered_plan = dataclasses.replace(plan, steps=(dataclasses.replace(plan.steps[0], cost=99),))
    state = dataclasses.replace(state, plan_result=dataclasses.replace(state.plan_result, plan=tampered_plan))
    out = h.run_stage("S11", state)
    assert (out.halt.status, out.halt.reason) == (StageStatus.ERROR, "plan_invalid")
    assert "plan_hash_mismatch" in out.validation_result.errors
    assert out.execution_manifest is None


def _with_steps(state, *steps):
    plan = dataclasses.replace(state.plan_result.plan, steps=steps,
                               budget_required=sum(s.cost for s in steps))
    return dataclasses.replace(state, plan_result=dataclasses.replace(
        state.plan_result, plan=plan, plan_hash=plan_digest(plan)))


@pytest.mark.parametrize("depends, error", [
    ([("b",), ("a",)], "circular_dependency"),
    ([("a",), ()], "circular_dependency"),
    ([("zzz",), ()], "unknown_dependency:a:zzz"),
])
def test_s11_rejects_bad_dependencies(depends, error):
    h = Harness()
    state = h.state_before("S11")
    base = state.plan_result.plan.steps[0]
    steps = [dataclasses.replace(base, id=step_id, depends_on=dep) for step_id, dep in zip("ab", depends)]
    out = h.run_stage("S11", _with_steps(state, *steps))
    assert error in out.validation_result.errors


def test_s11_requires_a_consumed_confirmation():
    h = _delete_harness()
    state = h.run_stage("S10", h.state_before("S10"))  # PENDING, not consumed
    out = h.run_stage("S11", state)
    assert "confirmation_missing" in out.validation_result.errors
    assert out.execution_manifest is None
