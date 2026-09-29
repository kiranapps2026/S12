"""
The S0–S11 runner: one sequence, statuses stop the run, exceptions become ERROR.

Source: RUNBOOK STEP 3, R-C (composition root), R-I (sequence scope)
"""
import asyncio
import dataclasses

import pytest

from contracts.pipeline_state import PRE_EXECUTION_SEQUENCE, PipelineState
from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.pipeline import make_entry, make_pipeline_deps, run_pipeline
from tests.fixtures.scenarios import make_scenario

ALL = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")


def test_stage_sequence_is_s0_to_s11():
    assert PRE_EXECUTION_SEQUENCE == ALL
    result = run_pipeline({"message": "list users", "connection_id": "conn-1"})
    assert result.status is StageStatus.NORMAL
    assert result.stages_run == ALL


def test_scope_failure_ends_in_error_before_s1():
    deps = make_pipeline_deps(make_scenario())

    class Broken:
        async def for_run(self, tenant_id, workspace_id):
            raise RuntimeError("database down")

    runner = build_pipeline(dataclasses.replace(deps, scopes=Broken()))
    result = asyncio.run(runner.run(make_entry()))
    assert (result.status, result.reason, result.stages_run) == (StageStatus.ERROR, "scope_unavailable", ("S0",))
    assert result.final_state.normalized_input is None


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

    runner.wrap("S6", lambda real: boom)
    runner.wrap("S7", lambda real: spy)
    result = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    assert (result.final_stage, result.status, result.reason) == ("S6", StageStatus.ERROR, "RuntimeError")
    assert ran == []                       # no later stage ran
    assert result.stages_run[-1] == "S5"   # S6 never completed
    assert result.final_state.task_profile is None


def test_handler_without_status_stops_as_error():
    runner = build_pipeline(make_pipeline_deps(make_scenario()))

    async def no_status(state):
        return dataclasses.replace(state, stage_status=None)

    runner.wrap("S1", lambda real: no_status)
    result = asyncio.run(runner.run(make_entry()))
    assert (result.final_stage, result.status, result.reason) == ("S1", StageStatus.ERROR, "stage_status_missing")


def test_runner_enforces_s7_outcome_even_if_handler_says_normal():
    """A1: a handler cannot let a deny/clarify route continue by reporting NORMAL."""
    sc = make_scenario(risk=0.97)           # above the 0.95 threshold -> S7 deny
    runner = build_pipeline(make_pipeline_deps(sc))

    def lying(real):
        async def s7(state):
            return (await real(state)).with_status(StageStatus.NORMAL)
        return s7

    runner.wrap("S7", lying)
    result = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    assert (result.final_stage, result.status, result.reason) == ("S7", StageStatus.DENY, "risk_above_threshold")
    assert result.final_state.safety_result is None


def test_runner_enforces_s10_pending_confirmation():
    """A2: a pending confirmation stops the run; S11 does not run and no manifest exists."""
    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    runner = build_pipeline(make_pipeline_deps(sc))

    def lying(real):
        async def s10(state):
            return (await real(state)).with_status(StageStatus.NORMAL)
        return s10

    runner.wrap("S10", lying)
    result = asyncio.run(runner.run(make_entry({"message": "x", "connection_id": "c"})))
    assert (result.final_stage, result.status, result.reason) == ("S10", StageStatus.CLARIFY, "confirmation_required")
    assert result.final_state.execution_manifest is None
    assert "S11" not in result.stages_run


def test_s0_is_run_and_missing_identity_denies():
    entry = dataclasses.replace(make_entry(), workspace_id=None)
    runner = build_pipeline(make_pipeline_deps(make_scenario()))
    result = asyncio.run(runner.run(entry))
    assert (result.final_stage, result.status, result.reason) == ("S0", StageStatus.DENY, "missing_workspace_id")
    assert result.final_state.execution_context is None
