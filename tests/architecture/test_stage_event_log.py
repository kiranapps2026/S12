"""
GOLDEN TEST FILE (OWNER). Pinned by hash. The agent edits it only on the owner's explicit
instruction.
Rulings: every S0-S11 stage outcome is recorded in the event log; the record holds no user text;
if an event cannot be recorded the run stops with ERROR ledger_unavailable (a refusal stays a
refusal); tenant is None only when S0 stopped before identity was known.

Fixture contract: make_pipeline_deps(scenario).events is an InMemoryEvents recording every
StageEvent (settable `fail` / `fail_on_stage`).
"""
import asyncio
import dataclasses
import time

from contracts.stage_events import StageEvent
from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.deps import ConfigurableAuthState, make_s8_deps
from tests.fixtures.pipeline import make_entry, make_pipeline_deps
from tests.fixtures.scenarios import make_scenario

HIGH = dict(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
REQ = {"message": "secret text the log must never contain", "connection_id": "conn-1"}
ALL = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]


def _run(sc=None, deps=None, request=REQ):
    deps = deps or make_pipeline_deps(sc or make_scenario())
    return deps, asyncio.run(build_pipeline(deps).run(make_entry(request)))


def test_a_full_run_records_every_stage_in_order():
    deps, result = _run()
    ev = deps.events.events
    assert [e.stage for e in ev] == ALL and {e.status for e in ev} == {"normal"}
    ctx = result.final_state.execution_context
    assert {(e.trace_id, e.request_id, e.tenant_id) for e in ev} == {(ctx.trace_id, ctx.request_id, "tenant-1")}
    assert all(e.duration_ms >= 0 for e in ev) and all(e.reason is None for e in ev)


def test_the_log_never_holds_user_text():
    deps, _ = _run()
    blob = " ".join(str(dataclasses.astuple(e)) for e in deps.events.events)
    assert "secret text" not in blob
    assert {f.name for f in dataclasses.fields(StageEvent)} == {
        "stage", "status", "reason", "duration_ms", "trace_id", "request_id", "tenant_id"}


def test_a_denial_is_recorded_with_its_reason_and_nothing_follows():
    s8 = make_s8_deps(kill_switch=False, auth=ConfigurableAuthState(tenant="suspended"))
    deps, result = _run(deps=make_pipeline_deps(make_scenario(), s8=s8))
    last = deps.events.events[-1]
    assert (last.stage, last.status, last.reason) == ("S8", "deny", "tenant_active_inactive")
    assert [e.stage for e in deps.events.events] == ALL[:9]
    assert (result.status, result.final_stage) == (StageStatus.DENY, "S8")


def test_activation_denial_is_recorded_as_s0_1():
    deps = make_pipeline_deps(make_scenario())
    deps.activation.tenant_paused_until = time.time() + 60
    _, result = _run(deps=deps)
    assert [(e.stage, e.status, e.reason) for e in deps.events.events] == [
        ("S0", "normal", None), ("S0.1", "deny", "tenant_paused")]
    assert result.final_stage == "S0"


def test_s0_denial_without_identity_has_no_tenant_or_trace():
    deps = make_pipeline_deps(make_scenario())
    entry = dataclasses.replace(make_entry(REQ), tenant_id=None)
    asyncio.run(build_pipeline(deps).run(entry))
    (e,) = deps.events.events
    assert (e.stage, e.status, e.reason, e.tenant_id, e.trace_id, e.request_id) == (
        "S0", "deny", "missing_tenant_id", None, None, None)


def test_s0_denial_for_a_missing_workspace_still_belongs_to_the_tenant():
    deps = make_pipeline_deps(make_scenario())
    asyncio.run(build_pipeline(deps).run(dataclasses.replace(make_entry(REQ), workspace_id=None)))
    (e,) = deps.events.events
    assert (e.reason, e.tenant_id) == ("missing_workspace_id", "tenant-1")


def test_an_unrecordable_stage_stops_the_run_before_the_next_stage():
    deps = make_pipeline_deps(make_scenario())
    deps.events.fail_on_stage = "S5"
    _, result = _run(deps=deps)
    assert (result.status, result.final_stage, result.reason) == (StageStatus.ERROR, "S5", "ledger_unavailable")
    assert [e.stage for e in deps.events.events] == ALL[:5]          # S5's own event never landed
    assert result.final_state.task_profile is None                    # S6 never ran
    assert "S6" not in result.stages_run


def test_ledger_down_at_the_start_runs_nothing():
    deps = make_pipeline_deps(make_scenario())
    deps.events.fail = True
    _, result = _run(deps=deps)
    assert (result.status, result.final_stage, result.reason) == (StageStatus.ERROR, "S0", "ledger_unavailable")
    assert result.stages_run == ("S0",) and result.final_state.normalized_input is None


def test_a_denial_stays_a_denial_when_the_ledger_is_down():
    """The refusal itself is what matters; it is never turned into an approval."""
    s8 = make_s8_deps(kill_switch=False, auth=ConfigurableAuthState(tenant="suspended"))
    deps = make_pipeline_deps(make_scenario(), s8=s8)
    deps.events.fail_on_stage = "S8"
    _, result = _run(deps=deps)
    assert (result.status, result.reason) == (StageStatus.DENY, "tenant_active_inactive")
    assert result.final_state.execution_manifest is None


def test_confirmation_pause_and_reply_are_recorded():
    deps = make_pipeline_deps(make_scenario(**HIGH))
    runner = build_pipeline(deps)
    paused = asyncio.run(runner.run(make_entry(REQ)))
    assert [(e.stage, e.status, e.reason) for e in deps.events.events][-1] == (
        "S10", "clarify", "confirmation_required")
    n = len(deps.events.events)
    cid = paused.final_state.confirmation.confirmation.confirmation_id
    assert asyncio.run(runner.reply("tenant-1", cid, "user-1", True)).status is StageStatus.NORMAL
    assert [(e.stage, e.status) for e in deps.events.events[n:]] == [("S10", "normal"), ("S11", "normal")]


def test_rejection_and_stale_authorization_on_reply_are_recorded():
    deps = make_pipeline_deps(make_scenario(**HIGH))
    runner = build_pipeline(deps)
    cid = asyncio.run(runner.run(make_entry(REQ))).final_state.confirmation.confirmation.confirmation_id
    n = len(deps.events.events)
    asyncio.run(runner.reply("tenant-1", cid, "user-1", False))
    assert [(e.stage, e.status, e.reason) for e in deps.events.events[n:]] == [
        ("S10", "deny", "confirmation_rejected")]


def test_an_unrecordable_reply_step_never_reaches_s11():
    deps = make_pipeline_deps(make_scenario(**HIGH))
    runner = build_pipeline(deps)
    cid = asyncio.run(runner.run(make_entry(REQ))).final_state.confirmation.confirmation.confirmation_id
    deps.events.fail = True
    out = asyncio.run(runner.reply("tenant-1", cid, "user-1", True))
    assert (out.status, out.reason) == (StageStatus.ERROR, "ledger_unavailable")
    assert out.final_state.execution_manifest is None
