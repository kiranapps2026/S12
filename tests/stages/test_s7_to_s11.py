"""
GOLDEN TEST FILE (OWNER). Pinned by hash. The agent edits it only on the owner's explicit
instruction; the amendments below were made on such an instruction.
AMENDMENTS: a denied stage reports through stage_status/deny_reason and writes no output; S9/S10/S11
refuse a run whose S8 result or auth_result_id was not recorded (auth_result_id is a UUID).
Rulings: runbook R-N (S9, S10, S11 deny with "safety_not_passed" unless S8 allowed and
auth_passed is true; a stage never raises for this and writes no output of its own),
R-M (S8 records auth_passed and auth_result_id; the manifest records auth_result_id).

Fixture contract additions: run_stage returns the PipelineState produced by the real
handler, with `stage_status` (StageStatus) and `deny_reason` (str | None) describing that
stage's result.
"""
import dataclasses

from contracts.safety import SafetyResult
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import run_stage, state_ready_for, tamper

LOW = dict(mutation="R", risk=0.1, steps=1, graph="simple", confidence=0.95)
OWN_FIELD = {"S9": "plan", "S10": "confirmation", "S11": "execution_manifest"}


def _status(out):
    s = out.stage_status
    return str(getattr(s, "value", s)).lower()


def _assert_safety_denial(stage):
    sc = make_scenario(**LOW)
    state = state_ready_for(stage, sc)
    for bad in (
        tamper(state, safety_result=SafetyResult(allowed=False, reason="x", failed_check="user_active")),
        tamper(state, execution_context=dataclasses.replace(state.execution_context, auth_passed=False)),
    ):
        out = run_stage(stage, bad, sc)
        assert (_status(out), out.deny_reason) == ("deny", "safety_not_passed")
        assert getattr(out, OWN_FIELD[stage]) == getattr(bad, OWN_FIELD[stage])


def test_s9_requires_safety_passed():
    _assert_safety_denial("S9")


def test_s10_requires_safety_passed():
    _assert_safety_denial("S10")


def test_s11_requires_safety_passed():
    _assert_safety_denial("S11")


def test_manifest_records_auth_result_id():
    sc = make_scenario(**LOW)
    state = state_ready_for("S11", sc)
    ctx = state.execution_context
    assert ctx.auth_passed is True and ctx.auth_result_id
    out = run_stage("S11", state, sc)
    assert out.execution_manifest.auth_result_id == ctx.auth_result_id


def test_auth_result_id_is_a_uuid_and_only_set_on_allow():
    import uuid
    sc = make_scenario(**LOW)
    state = state_ready_for("S9", sc)
    uuid.UUID(state.execution_context.auth_result_id)
    assert state.execution_context.auth_passed is True


def test_no_stage_after_a_refused_safety_gate_writes_anything():
    """Even if a buggy caller kept going, S9, S10 and S11 add nothing to a refused run."""
    sc = make_scenario(**LOW)
    state = state_ready_for("S9", sc)
    bad = tamper(state, safety_result=SafetyResult(allowed=False, reason="x", failed_check="user_active"))
    for stage in ("S9",):
        out = run_stage(stage, bad, sc)
        assert out.plan is None and out.confirmation is None and out.execution_manifest is None
