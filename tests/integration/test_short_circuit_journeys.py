"""
Short-circuit journeys: the real runner stops at the denying stage, and no stage after it
produces output.

Source: RUNBOOK STEP 9. Journeys never write stage outputs by hand.
"""
import asyncio
import dataclasses
import time

from contracts.pipeline_state import PRE_EXECUTION_SEQUENCE, STAGE_OUTPUT_FIELD
from contracts.stage_outputs import IntentResult
from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.deps import ConfigurableAuthState, make_s8_deps
from tests.fixtures.pipeline import make_entry, make_pipeline_deps, run_pipeline
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import ScenarioIntentModel

REQ = {"message": "do it", "connection_id": "conn-1"}


def _assert_no_output_after(result, stage):
    later = PRE_EXECUTION_SEQUENCE[PRE_EXECUTION_SEQUENCE.index(stage) + 1:]
    for s in later:
        assert result.final_state.get_stage_output(s) is None, f"{s} produced output after {stage} stopped"
    assert result.final_state.validation_result is None or stage == "S11"
    assert stage not in later and all(s not in result.stages_run for s in later)


def test_s2_deny():
    sc = make_scenario()
    result = run_pipeline(REQ, sc, model=ScenarioIntentModel(sc, intent="prohibited"))
    assert (result.final_stage, result.status, result.reason) == ("S2", StageStatus.DENY, "intent_prohibited")
    _assert_no_output_after(result, "S2")


def test_s2_clarify():
    sc = make_scenario()
    result = run_pipeline(REQ, sc, model=ScenarioIntentModel(sc, intent="unknown"))
    assert (result.final_stage, result.status, result.reason) == ("S2", StageStatus.CLARIFY, "intent_unclear")
    _assert_no_output_after(result, "S2")


def test_s8_deny():
    sc = make_scenario()
    suspended = make_s8_deps(kill_switch=False, auth=ConfigurableAuthState(tenant="suspended"))
    result = run_pipeline(REQ, sc, s8=suspended)
    assert (result.final_stage, result.status, result.reason) == ("S8", StageStatus.DENY, "tenant_active_inactive")
    assert result.final_state.execution_context.auth_passed is False
    _assert_no_output_after(result, "S8")


def test_s10_expired_deny():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    deps = make_pipeline_deps(sc)
    runner = build_pipeline(deps)
    paused = asyncio.run(runner.run(make_entry(REQ)))
    assert (paused.final_stage, paused.status, paused.reason) == ("S10", StageStatus.CLARIFY, "confirmation_required")
    assert paused.final_state.execution_manifest is None

    # the user answers after the confirmation has expired
    conf = paused.final_state.confirmation.confirmation
    rows = deps.confirmation_store._inner._rows
    rows[conf.confirmation_id] = (dataclasses.replace(conf, expires_at=time.time() - 1),
                                  *rows[conf.confirmation_id][1:])
    result = asyncio.run(runner.reply("tenant-1", conf.confirmation_id, "user-1", True))
    assert (result.status, result.reason) == (StageStatus.DENY, "confirmation_expired")
    assert result.final_state.execution_manifest is None
    assert result.final_state.validation_result is None


def test_s10_confirmed_reply_reaches_manifest_exactly_once():
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    runner = build_pipeline(make_pipeline_deps(sc))
    paused = asyncio.run(runner.run(make_entry(REQ)))
    cid = paused.final_state.confirmation.confirmation.confirmation_id
    result = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert result.status is StageStatus.NORMAL
    assert result.final_state.execution_manifest.plan_hash == paused.final_state.plan.plan_hash
    assert result.final_state.confirmation.confirmation.consumed_at is not None
    again = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))       # single use
    assert (again.status, again.reason) == (StageStatus.DENY, "confirmation_mismatch")
    assert again.final_state.execution_manifest is None


def test_s11_plan_mutation_deny():
    sc = make_scenario(mutation="W", risk=0.2, steps=3, graph="chain", confidence=0.8)
    deps = make_pipeline_deps(sc)
    runner = build_pipeline(deps)
    s10 = asyncio.run(runner.run(make_entry(REQ), stop_after="S10"))
    assert s10.status is StageStatus.NORMAL
    state = s10.final_state
    plan = state.plan.plan
    mutated = dataclasses.replace(plan, steps=(dataclasses.replace(plan.steps[0], risk=0.0),) + plan.steps[1:])
    state = dataclasses.replace(state, plan=dataclasses.replace(state.plan, plan=mutated))
    handlers = runner.handlers(asyncio.run(deps.scopes.for_run("tenant-1", "ws-1")))
    result = asyncio.run(runner._run_from(state, handlers, ("S11",), list(s10.stages_run), 0.0, None))
    assert (result.final_stage, result.status, result.reason) == ("S11", StageStatus.DENY, "binding_mismatch")
    assert result.final_state.execution_manifest is None
    assert result.final_state.validation_result.is_valid is False
