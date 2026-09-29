"""
S6–S11 never re-resolve: risk, mutation and binding are read from the frozen binding.

Source: RUNBOOK STEP 8
"""
from unittest import mock

from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.pipeline import make_entry, make_pipeline_deps, run_pipeline, run_through
from tests.fixtures.scenarios import ScenarioRegistry, make_scenario
import asyncio

REQUEST = {"message": "create contact", "connection_id": "conn-1"}


def test_s6_to_s11_no_resolver_calls():
    sc = make_scenario(mutation="W", risk=0.3, steps=3, graph="chain", confidence=0.8)
    deps = make_pipeline_deps(sc)
    at_s5 = run_through("S5", REQUEST, scenario=sc)          # real S0..S5

    runner = build_pipeline(deps)
    handlers = runner.handlers(asyncio.run(deps.scopes.for_run("tenant-1", "ws-1")))
    reg = deps.registry
    with mock.patch.object(ScenarioRegistry, "discover", wraps=reg.discover) as discover, \
         mock.patch.object(ScenarioRegistry, "list_bindings", wraps=reg.list_bindings) as bindings, \
         mock.patch.object(ScenarioRegistry, "get_capability", wraps=reg.get_capability) as get_cap, \
         mock.patch("engine.stages.s5_provider_resolution.handler.handle") as s5_spy:
        state = at_s5
        for stage in ("S6", "S7", "S8", "S9", "S10", "S11"):
            state = asyncio.run(handlers[stage](state))
            assert state.stage_status is StageStatus.NORMAL, (stage, state.deny_reason)
    assert discover.call_count == 0
    assert bindings.call_count == 0
    assert get_cap.call_count == 0
    assert s5_spy.call_count == 0
    assert state.execution_manifest is not None


def test_frozen_binding_identity_preserved():
    sc = make_scenario(mutation="W", risk=0.3, steps=2, graph="chain", confidence=0.8)
    at_s5 = run_through("S5", REQUEST, scenario=sc)
    final = run_pipeline(REQUEST, sc)
    assert final.status is StageStatus.NORMAL
    frozen_after_s5 = at_s5.frozen_binding_identity
    frozen_final = final.final_state.frozen_binding_identity
    assert frozen_final == frozen_after_s5                     # same values

    # identity: hand the S5 object through S6..S11 and it comes out as the same object
    deps = make_pipeline_deps(sc)
    handlers = build_pipeline(deps).handlers(asyncio.run(deps.scopes.for_run("tenant-1", "ws-1")))
    state = at_s5
    for stage in ("S6", "S7", "S8", "S9", "S10", "S11"):
        state = asyncio.run(handlers[stage](state))
    assert state.frozen_binding_identity is frozen_after_s5
