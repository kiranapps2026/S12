"""
Pipeline journey helpers — the REAL runner, real handlers, fixture dependencies.

Source: R-H (runbook): journeys use real handlers, not hand-built state.

  make_pipeline_deps(scenario, *, llm=None, s8=None) -> PipelineDependencies
  run_pipeline(request, scenario=None, *, stop_after=None, ...) -> PipelineRunResult
  run_through(stage_id, request, deps) -> PipelineState   (must end NORMAL)
"""
from __future__ import annotations

import asyncio

from contracts.kernel_policy import KernelPolicy
from contracts.pipeline_state import PipelineState
from engine.control_plane.pipeline_state_runner import (
    PipelineDependencies, PipelineRunResult, build_pipeline,
)
from engine.stages.s0_entry.handler import EntryRequest
from tests.fixtures.deps import make_s8_deps
from tests.fixtures.scenarios import ScenarioRegistry, make_scenario
from tests.fixtures.states import _ScenarioDrivenLLM


def make_pipeline_deps(scenario, *, llm=None, s8=None) -> PipelineDependencies:
    return PipelineDependencies(
        llm=llm or _ScenarioDrivenLLM(scenario),
        registry=ScenarioRegistry(scenario),
        policy=KernelPolicy(kill_switch_engaged=False,
                            risk_deny_threshold=scenario.risk_deny_threshold),
        s8=s8 or make_s8_deps(kill_switch=False),
        confirmation_store=scenario.confirmation_store,
    )


def make_entry(request: dict | None = None) -> EntryRequest:
    request = request or {"message": "test", "entry_channel": "api"}
    return EntryRequest(
        raw_payload=request,
        entry_channel=request.get("entry_channel", "api"),
        tenant_id=request.get("tenant_id", "tenant-1"),
        workspace_id=request.get("workspace_id", "ws-1"),
        user_id=request.get("user_id", "user-1"),
        conversation_id=request.get("conversation_id"),
        connection_id=request.get("connection_id"),
    )


def run_pipeline(request: dict | None = None, scenario=None, *, stop_after: str | None = None,
                 llm=None, s8=None, deps: PipelineDependencies | None = None) -> PipelineRunResult:
    """Run the real S0..S11 runner over the request."""
    scenario = scenario or make_scenario()
    deps = deps or make_pipeline_deps(scenario, llm=llm, s8=s8)
    return asyncio.run(build_pipeline(deps).run(make_entry(request), stop_after=stop_after))


def run_through(stage_id: str, request: dict | None = None, deps=None,
                scenario=None) -> PipelineState:
    """Run real handlers S0..stage_id and return the PipelineState as stage_id leaves it.

    `deps` is an optional S8Dependencies override. The run must end NORMAL; a stage that
    stops it is reported with its stage and reason.
    """
    result = run_pipeline(request, scenario, stop_after=stage_id, s8=deps)
    if result.final_stage != stage_id or result.status.value != "NORMAL":
        raise AssertionError(
            f"run_through({stage_id}): stopped at {result.final_stage}: "
            f"{result.status} / {result.reason}")
    return result.final_state
