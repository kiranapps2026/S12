"""S0 entry and the S0.1 activation check (pause ruling, PIPELINE_STAGES §2 step 8)."""
from __future__ import annotations

import re

import pytest

from supragents.contracts.vocabulary import StageStatus
from supragents.pipeline.result import RunOutcome
from tests.builders import Harness, entry

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _s0(h: Harness, request=None):
    from supragents.contracts.state import PipelineState
    return h.run_stage("S0", PipelineState(entry_request=request or entry()))


def test_context_copies_authenticated_identity_and_generates_ids():
    context = _s0(Harness()).execution_context
    assert UUID4.match(context.trace_id) and UUID4.match(context.request_id)
    assert context.trace_id != context.request_id == context.idempotency_key
    assert (context.tenant_id, context.workspace_id, context.user_id) == ("tenant-a", "workspace-1", "user-1")
    assert context.auth_passed is False and context.task_id is None


@pytest.mark.parametrize("field", ["tenant_id", "workspace_id", "user_id", "membership_id",
                                   "connection_id", "conversation_id", "resource_scope"])
def test_missing_identity_denies(field):
    state = _s0(Harness(), entry(**{field: ""}))
    assert state.halt.status is StageStatus.DENY
    assert state.halt.reason == f"identity_missing:{field}"
    assert state.execution_context is None


@pytest.mark.parametrize("field, reason", [
    ("tenant_paused_until", "tenant_paused"),
    ("workspace_paused_until", "workspace_paused"),
    ("tenant_activation_at", "not_yet_active"),
    ("workspace_activation_at", "not_yet_active"),
])
def test_future_pause_or_activation_denies_before_any_llm_call(field, reason):
    h = Harness()
    h.activation.times[field] = h.clock.current + 1
    result = h.run()
    assert (result.halt.stage, result.halt.status, result.halt.reason) == ("S0", StageStatus.DENY, reason)
    assert h.intent_model.calls == []


@pytest.mark.parametrize("offset", [None, -1, 0])
def test_elapsed_or_absent_pause_continues(offset):
    h = Harness()
    h.activation.times["tenant_paused_until"] = None if offset is None else h.clock.current + offset
    assert h.run().outcome is RunOutcome.COMPLETED


def test_pause_check_uses_database_time():
    h = Harness()
    h.activation.database_now = h.clock.current
    h.activation.times["tenant_paused_until"] = h.clock.current + 30
    h.clock.advance(3600)  # process clock is past the pause; the database clock is not
    assert _s0(h).halt.reason == "tenant_paused"


def test_unreadable_activation_state_fails_closed():
    h = Harness()
    h.activation.error = True
    result = h.run()
    assert (result.halt.status, result.halt.reason) == (StageStatus.DENY, "activation_state_unavailable")
    assert h.intent_model.calls == []
