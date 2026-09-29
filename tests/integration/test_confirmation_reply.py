"""Suspended runs and the confirmation reply: authenticated replier, tenant isolation,
re-authorization, restart survival, fail closed."""
import asyncio
import dataclasses

import pytest

from contracts.errors import UnknownConfirmation
from contracts.kernel_policy import KernelPolicy
from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from engine.control_plane.scope import RunScope
from tests.fixtures.deps import ConfigurableAuthState, make_s8_deps
from tests.fixtures.pipeline import make_entry, make_pipeline_deps
from tests.fixtures.scenarios import make_scenario
from tests.fixtures.states import POLICY_VERSIONS

HIGH = dict(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
REQ = {"message": "delete it", "connection_id": "conn-1"}


def _pause(deps=None, sc=None):
    sc = sc or make_scenario(**HIGH)
    deps = deps or make_pipeline_deps(sc)
    runner = build_pipeline(deps)
    paused = asyncio.run(runner.run(make_entry(REQ)))
    assert (paused.final_stage, paused.reason) == ("S10", "confirmation_required"), paused
    return deps, runner, paused, paused.final_state.confirmation.confirmation.confirmation_id


def test_pausing_stores_the_run_under_tenant_and_confirmation_id():
    deps, _, paused, cid = _pause()
    assert list(deps.suspended.rows) == [("tenant-1", cid)]
    assert paused.status is StageStatus.CLARIFY


def test_only_the_confirmations_user_can_answer_and_a_wrong_reply_does_not_burn_it():
    deps, runner, _, cid = _pause()
    wrong = asyncio.run(runner.reply("tenant-1", cid, "someone-else", True))
    assert (wrong.status, wrong.reason) == (StageStatus.DENY, "confirmation_mismatch")
    assert wrong.final_state.execution_manifest is None
    right = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))          # still works
    assert right.status is StageStatus.NORMAL


def test_a_run_is_invisible_to_other_tenants():
    _, runner, _, cid = _pause()
    with pytest.raises(UnknownConfirmation):
        asyncio.run(runner.reply("tenant-2", cid, "user-1", True))


def test_unknown_confirmation_id():
    _, runner, _, _ = _pause()
    with pytest.raises(UnknownConfirmation):
        asyncio.run(runner.reply("tenant-1", "no-such-id", "user-1", True))


def test_rejection_ends_the_run_and_the_confirmation_can_no_longer_be_approved():
    _, runner, _, cid = _pause()
    no = asyncio.run(runner.reply("tenant-1", cid, "user-1", False))
    assert (no.status, no.reason) == (StageStatus.DENY, "confirmation_rejected")
    assert no.final_state.execution_manifest is None
    late = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert (late.status, late.reason) == (StageStatus.DENY, "confirmation_mismatch")


def test_only_the_right_user_can_reject():
    _, runner, _, cid = _pause()
    wrong = asyncio.run(runner.reply("tenant-1", cid, "someone-else", False))
    assert (wrong.status, wrong.reason) == (StageStatus.DENY, "confirmation_mismatch")
    assert asyncio.run(runner.reply("tenant-1", cid, "user-1", True)).status is StageStatus.NORMAL


def test_the_run_survives_a_restart():
    """A new runner (new process) with the same durable stores answers the old run."""
    deps, _, _, cid = _pause()
    fresh = build_pipeline(deps)                    # nothing in memory from the first runner
    assert asyncio.run(fresh.reply("tenant-1", cid, "user-1", True)).status is StageStatus.NORMAL


def test_if_the_suspended_run_cannot_be_stored_the_run_ends_in_error():
    sc = make_scenario(**HIGH)
    deps = make_pipeline_deps(sc)
    deps.suspended.fail_saves = True
    result = asyncio.run(build_pipeline(deps).run(make_entry(REQ)))
    assert (result.status, result.reason) == (StageStatus.ERROR, "suspended_run_unrecorded")


class _Scopes:
    """Scope whose kill switch / auth state can change between the run and the reply."""

    def __init__(self, sc):
        self.auth = ConfigurableAuthState()
        self.kill = False
        self.sc = sc

    async def for_run(self, tenant_id, workspace_id):
        policy = KernelPolicy(kill_switch_engaged=self.kill, risk_deny_threshold=0.95)
        s8 = make_s8_deps(kill_switch=self.kill, auth=self.auth)
        return RunScope(policy=policy, s8=s8, policy_versions=POLICY_VERSIONS)


def _with_scopes():
    sc = make_scenario(**HIGH)
    deps = make_pipeline_deps(sc)
    scopes = _Scopes(sc)
    return dataclasses.replace(deps, scopes=scopes), scopes


def test_kill_switch_engaged_while_waiting_stops_the_run_and_does_not_consume():
    deps, scopes = _with_scopes()
    deps, runner, _, cid = _pause(deps)
    scopes.kill = True
    out = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert (out.status, out.final_stage, out.reason) == (StageStatus.DENY, "S8", "kill_switch")
    assert out.final_state.execution_manifest is None
    scopes.kill = False                                     # switch released: still answerable
    assert asyncio.run(runner.reply("tenant-1", cid, "user-1", True)).status is StageStatus.NORMAL


@pytest.mark.parametrize("attr,value,reason", [
    ("user", "suspended", "user_active_inactive"),
    ("tenant", "suspended", "tenant_active_inactive"),
    ("grant", False, "capability_granted_denied"),
    ("budget", False, "budget_available_denied"),
])
def test_authorization_lost_while_waiting_stops_the_run(attr, value, reason):
    deps, scopes = _with_scopes()
    _, runner, _, cid = _pause(deps)
    setattr(scopes.auth, attr, value)
    out = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert (out.status, out.final_stage, out.reason) == (StageStatus.DENY, "S8", reason)
    assert out.final_state.execution_manifest is None


def test_scope_failure_on_reply_is_an_error_not_an_approval():
    deps, scopes = _with_scopes()
    _, runner, _, cid = _pause(deps)

    async def broken(tenant_id, workspace_id):
        raise RuntimeError("database down")
    scopes.for_run = broken
    out = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert out.status is StageStatus.ERROR and out.final_state.execution_manifest is None
