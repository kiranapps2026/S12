"""
GOLDEN TEST FILE (OWNER). Pinned by hash. The agent edits it only on the owner's explicit
instruction.
Rulings: R-AA (S0.1 activation check; proposed id, see docs/proposals/S0_1_PAUSE_CHECK.md).
A paused or not-yet-active tenant/workspace runs no S1-S11 work; the database clock decides;
fail closed; the check also gates every reply to a waiting confirmation.

Fixture contract (tests/fixtures/pipeline.py): make_pipeline_deps(scenario) -> deps whose
`activation` is a StaticActivation (settable *_paused_until / *_activation_at / now / error);
build_pipeline(deps).run(entry) -> PipelineRunResult(status, final_stage, reason, stages_run,
final_state).
"""
import asyncio
import time

import pytest

from contracts.activation import ActivationState
from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from engine.stages.s0_entry.activation import inactive_reason
from tests.fixtures.pipeline import make_entry, make_pipeline_deps
from tests.fixtures.scenarios import make_scenario

NOW = 1_000_000.0
FUTURE, PAST = NOW + 3600, NOW - 3600
HIGH = dict(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
REQ = {"message": "x", "connection_id": "conn-1"}


def _state(**kw):
    base = dict(database_now=NOW, tenant_paused_until=None, tenant_activation_at=None,
                workspace_paused_until=None, workspace_activation_at=None)
    return ActivationState(**{**base, **kw})


@pytest.mark.parametrize("kw,expected", [
    ({}, None),
    ({"tenant_paused_until": FUTURE}, "tenant_paused"),
    ({"tenant_paused_until": PAST}, None),                       # pause elapsed
    ({"tenant_paused_until": NOW}, None),                        # exactly now: no longer paused
    ({"workspace_paused_until": FUTURE}, "workspace_paused"),
    ({"tenant_activation_at": FUTURE}, "not_yet_active"),
    ({"workspace_activation_at": FUTURE}, "not_yet_active"),
    ({"tenant_activation_at": PAST, "workspace_activation_at": PAST}, None),
    ({"tenant_paused_until": FUTURE, "workspace_paused_until": FUTURE}, "tenant_paused"),   # first wins
    ({"workspace_paused_until": FUTURE, "tenant_activation_at": FUTURE}, "workspace_paused"),
])
def test_reason_table(kw, expected):
    assert inactive_reason(_state(**kw)) == expected


def _run(mutate=None, sc=None):
    deps = make_pipeline_deps(sc or make_scenario())
    if mutate:
        mutate(deps.activation)
    return deps, asyncio.run(build_pipeline(deps).run(make_entry(REQ)))


@pytest.mark.parametrize("field,reason", [
    ("tenant_paused_until", "tenant_paused"),
    ("workspace_paused_until", "workspace_paused"),
    ("tenant_activation_at", "not_yet_active"),
    ("workspace_activation_at", "not_yet_active"),
])
def test_a_paused_tenant_runs_nothing_after_s0(field, reason):
    _, result = _run(lambda a: setattr(a, field, time.time() + 3600))
    assert (result.status, result.final_stage, result.reason) == (StageStatus.DENY, "S0", reason)
    assert result.stages_run == ("S0",)
    s = result.final_state
    assert s.normalized_input is None and s.intent_result is None and s.safety_result is None
    assert s.execution_context.auth_passed is False


def test_a_finished_pause_runs_normally():
    _, result = _run(lambda a: setattr(a, "tenant_paused_until", time.time() - 5))
    assert result.status is StageStatus.NORMAL and result.stages_run[-1] == "S11"


def test_the_deny_happens_before_the_scope_is_read():
    """Even a broken scope factory is never reached for a paused tenant."""
    deps = make_pipeline_deps(make_scenario())
    deps.activation.tenant_paused_until = time.time() + 60

    class Boom:
        async def for_run(self, *a):
            raise AssertionError("scope must not be read for a paused tenant")

    import dataclasses
    result = asyncio.run(build_pipeline(dataclasses.replace(deps, scopes=Boom())).run(make_entry(REQ)))
    assert result.reason == "tenant_paused"


def test_unreadable_activation_state_denies():
    def boom(a):
        a.error = RuntimeError("db down")
    _, result = _run(boom)
    assert (result.status, result.reason) == (StageStatus.DENY, "activation_state_unavailable")


def test_a_missing_reader_denies():
    import dataclasses
    deps = dataclasses.replace(make_pipeline_deps(make_scenario()), activation=None)
    result = asyncio.run(build_pipeline(deps).run(make_entry(REQ)))
    assert (result.status, result.reason) == (StageStatus.DENY, "activation_state_unavailable")


def test_a_pause_also_blocks_the_reply_to_a_waiting_confirmation():
    deps = make_pipeline_deps(make_scenario(**HIGH))
    runner = build_pipeline(deps)
    paused = asyncio.run(runner.run(make_entry(REQ)))
    cid = paused.final_state.confirmation.confirmation.confirmation_id
    deps.activation.workspace_paused_until = time.time() + 60
    out = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert (out.status, out.reason) == (StageStatus.DENY, "workspace_paused")
    assert out.final_state.execution_manifest is None
    deps.activation.workspace_paused_until = None               # pause lifted: still answerable
    assert asyncio.run(runner.reply("tenant-1", cid, "user-1", True)).status is StageStatus.NORMAL
