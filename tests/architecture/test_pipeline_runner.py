"""
The S0–S11 runner: one sequence, statuses stop the run, exceptions become ERROR.

Source: RUNBOOK STEP 3, R-C (composition root), R-I (sequence scope)
"""
import asyncio
import dataclasses

import pytest

from contracts.pipeline_state import PRE_EXECUTION_SEQUENCE, PipelineState
from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import PipelineRunner, build_pipeline
from tests.fixtures.pipeline import make_entry, make_pipeline_deps, run_pipeline
from tests.fixtures.scenarios import make_scenario

ALL = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")


def test_stage_sequence_is_s0_to_s11():
    assert PRE_EXECUTION_SEQUENCE == ALL
    result = run_pipeline({"message": "list users", "connection_id": "conn-1"})
    assert result.status is StageStatus.NORMAL
    assert result.stages_run == ALL


def test_runner_requires_every_handler():
    deps = make_pipeline_deps(make_scenario())
    with pytest.raises(ValueError, match="missing handlers"):
        PipelineRunner({"S1": lambda s: s}, deps)


def test_uncaught_exception_becomes_error_and_stops():
    sc = make_scenario()
    deps = make_pipeline_deps(sc)
    runner = build_pipeline(deps)
    ran = []

    async def boom(state):
        raise RuntimeError("handler exploded")

    async def spy(state):
        ran.append("S7")
        return state

    runner._handlers["S6"] = boom
    runner._handlers["S7"] = spy
    result = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    assert (result.final_stage, result.status, result.reason) == ("S6", StageStatus.ERROR, "RuntimeError")
    assert ran == []                       # no later stage ran
    assert result.stages_run[-1] == "S5"   # S6 never completed
    assert result.final_state.task_profile is None


def test_handler_without_status_stops_as_error():
    runner = build_pipeline(make_pipeline_deps(make_scenario()))

    async def no_status(state):
        return dataclasses.replace(state, stage_status=None)

    runner._handlers["S1"] = no_status
    result = asyncio.run(runner.run(make_entry()))
    assert (result.final_stage, result.status, result.reason) == ("S1", StageStatus.ERROR, "stage_status_missing")


def test_runner_enforces_s7_outcome_even_if_handler_says_normal():
    """A1: a handler cannot let a deny/clarify route continue by reporting NORMAL."""
    sc = make_scenario(risk=0.97)           # above the 0.95 threshold -> S7 deny
    runner = build_pipeline(make_pipeline_deps(sc))
    real_s7 = runner._handlers["S7"]

    async def lying_s7(state):
        out = await real_s7(state)
        return out.with_status(StageStatus.NORMAL)

    runner._handlers["S7"] = lying_s7
    result = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    assert (result.final_stage, result.status, result.reason) == ("S7", StageStatus.DENY, "risk_above_threshold")
    assert result.final_state.safety_result is None


def test_runner_enforces_s10_pending_confirmation():
    """A2: a pending confirmation stops the run; S11 does not run and no manifest exists."""
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    runner = build_pipeline(make_pipeline_deps(sc))
    real_s10 = runner._handlers["S10"]

    async def lying_s10(state):
        return (await real_s10(state)).with_status(StageStatus.NORMAL)

    runner._handlers["S10"] = lying_s10
    result = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    assert (result.final_stage, result.status, result.reason) == ("S10", StageStatus.CLARIFY, "confirmation_required")
    assert result.final_state.execution_manifest is None
    assert "S11" not in result.stages_run


def test_s0_is_run_and_missing_identity_denies():
    entry = make_entry()
    entry.workspace_id = None
    runner = build_pipeline(make_pipeline_deps(make_scenario()))
    result = asyncio.run(runner.run(entry))
    assert (result.final_stage, result.status, result.reason) == ("S0", StageStatus.DENY, "missing_workspace_id")
    assert result.final_state.execution_context is None
