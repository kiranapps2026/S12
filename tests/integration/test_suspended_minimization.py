"""A suspended run stores what the reply needs and nothing the user typed."""
import asyncio
import json

from contracts.stage_registry import StageStatus
from engine.control_plane.pipeline_state_runner import build_pipeline
from tests.fixtures.pipeline import make_entry, make_pipeline_deps
from tests.fixtures.scenarios import make_scenario

HIGH = dict(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)


def test_the_stored_run_holds_no_request_text_and_can_still_be_answered():
    deps = make_pipeline_deps(make_scenario(**HIGH))
    runner = build_pipeline(deps)
    paused = asyncio.run(runner.run(make_entry({"message": "delete Secret Person qzqz", "connection_id": "c"})))
    ((key, stored),) = deps.suspended.rows.items()
    assert "Secret Person" not in stored and "qzqz" not in stored
    state = json.loads(stored)
    assert state["entry_request"]["raw_payload"] == {} and state["normalized_input"]["sanitized_input"] == {}
    n = state["normalized_input"]
    assert (n["text"], n["entities"], n["references"]) == ("", {}, {})
    assert state["intent_result"]["parameters"] == {} and state["intent_result"]["raw_llm_output"] == ""
    assert state["intent_result"]["intent_type"] and state["plan"] and state["confirmation"]   # what resume needs
    out = asyncio.run(runner.reply("tenant-1", paused.final_state.confirmation.confirmation.confirmation_id,
                                   "user-1", True))
    assert out.status is StageStatus.NORMAL and out.final_state.execution_manifest is not None


def test_the_live_result_still_carries_the_full_state():
    """Minimization applies to what is stored, not to the state returned to the caller."""
    deps = make_pipeline_deps(make_scenario(**HIGH))
    paused = asyncio.run(build_pipeline(deps).run(make_entry({"message": "delete it", "connection_id": "c"})))
    assert paused.final_state.entry_request.raw_payload["message"] == "delete it"
