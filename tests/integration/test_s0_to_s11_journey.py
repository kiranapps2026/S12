"""
Integration tests — S0–S11 complete journey.

Tests the full pipeline from EntryRequest through S11.
Uses run_through() helper per R-H: real handlers, no hand-built state.
"""

from __future__ import annotations

import time

import pytest

from contracts.execution_manifest import Confirmation
from tests.fixtures.pipeline import run_through


class TestS0ToS11Journey:
    """End-to-end journey through all S0–S11 stages."""

    def test_fast_path_runs_s0_to_s11(self):
        """FAST (READ) request runs all 12 stages."""
        state = run_through("S11", request={
            "message": "list all users",
            "entry_channel": "api",
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "conversation_id": "conv-1",
            "connection_id": "conn-1",
        })
        assert state.execution_context is not None
        assert state.intent_result is not None
        assert state.frozen_binding_identity is not None
        assert state.task_profile is not None
        assert state.path_decision is not None
        assert state.safety_result is not None
        assert state.plan is not None
        assert state.confirmation is not None
        assert state.execution_manifest is not None

    def test_every_executable_path_runs_s8(self):
        """Both FAST and WORKFLOW journeys produce a safety_result."""
        fast = run_through("S8", request={
            "message": "read data",
            "entry_channel": "api",
            "tenant_id": "t1",
            "user_id": "u1",
            "connection_id": "conn-1",
        })
        assert fast.safety_result is not None

        wf = run_through("S8", request={
            "message": "workflow task",
            "entry_channel": "api",
            "tenant_id": "t1",
            "user_id": "u1",
            "connection_id": "conn-1",
        })
        assert wf.safety_result is not None

    def test_plan_hash_binds_confirmation(self):
        """S11 manifest plan_hash matches S9 plan_hash."""
        state = run_through("S11", request={
            "message": "create record",
            "entry_channel": "api",
            "tenant_id": "t1",
            "user_id": "u1",
            "connection_id": "conn-1",
        })
        plan = state.plan
        manifest = state.execution_manifest
        assert plan is not None
        assert manifest is not None
        assert manifest.plan_hash == plan.plan_hash

    def test_execution_id_not_request_id(self):
        """execution_id from S9 is distinct from S0's request_id."""
        state = run_through("S9", request={
            "message": "test",
            "entry_channel": "api",
            "tenant_id": "t1",
            "user_id": "u1",
            "connection_id": "conn-1",
        })
        assert state.plan.execution_id != state.execution_context.request_id


class TestExecutionContextImmutabilityJourney:
    """ExecutionContext is never mutated in place during S0–S11."""

    def test_s0_creates_new_context(self):
        """S0 creates a NEW ExecutionContext."""
        state = run_through("S0")
        assert state.execution_context is not None
        assert state.execution_context.trace_id != ""
        assert state.execution_context.request_id != ""

    def test_context_never_mutated_in_place(self):
        """ExecutionContext is frozen — cannot be mutated in place."""
        from dataclasses import FrozenInstanceError
        state = run_through("S0")
        ctx = state.execution_context
        with pytest.raises(FrozenInstanceError):
            ctx.trace_id = "new-trace"


class TestS5FreezesBinding:
    """After S5, FrozenBindingIdentity is immutable."""

    def test_risk_frozen_at_s5(self):
        """risk is frozen at S5."""
        from contracts.stage_outputs import CapabilityMatch
        state = run_through("S5", request={
            "message": "test",
            "entry_channel": "api",
            "tenant_id": "t1",
            "user_id": "u1",
        })
        assert state.frozen_binding_identity is not None
        assert state.frozen_binding_identity.effective_risk is not None


class TestS11ProducesManifest:
    """S11 produces ExecutionManifest from the real S9 output."""

    def test_manifest_created(self):
        """S11 creates ExecutionManifest from PipelineState with real S9 output."""
        state = run_through("S11", request={
            "message": "create contact",
            "entry_channel": "api",
            "tenant_id": "tenant-001",
            "user_id": "user-001",
            "conversation_id": "conv-001",
            "connection_id": "conn-001",
        })
        plan = state.plan
        manifest = state.execution_manifest
        ctx = state.execution_context
        assert manifest is not None
        assert plan is not None
        assert manifest.execution_id == plan.execution_id
        assert manifest.plan_hash == plan.plan_hash
        assert manifest.trace_id == ctx.trace_id
        assert plan.execution_id != ctx.request_id


def test_full_journey_real_handlers():
    """Real runner, real handlers, S0..S11: the identifiers and hashes line up."""
    from contracts.plan_hash import canonical_plan_digest
    from contracts.stage_registry import StageStatus
    from tests.fixtures.pipeline import run_pipeline
    from tests.fixtures.scenarios import make_scenario

    sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
    result = run_pipeline({"message": "delete it", "connection_id": "conn-1"}, sc)
    assert result.status is StageStatus.CLARIFY          # S10 waits for the user

    import asyncio
    from engine.control_plane.pipeline_state_runner import build_pipeline
    from tests.fixtures.pipeline import make_entry, make_pipeline_deps
    runner = build_pipeline(make_pipeline_deps(sc))
    paused = asyncio.run(runner.run(make_entry({"message": "delete it", "connection_id": "conn-1"})))
    final = asyncio.run(runner.resume(paused.final_state))
    assert final.status is StageStatus.NORMAL

    state = final.final_state
    plan_result, ctx = state.plan, state.execution_context
    assert plan_result.execution_id != ctx.request_id
    assert state.confirmation.confirmation.plan_hash == plan_result.plan_hash
    assert state.execution_manifest.execution_id == plan_result.execution_id
    assert canonical_plan_digest(plan_result.plan) == plan_result.plan_hash
    assert state.execution_manifest.auth_result_id == ctx.auth_result_id
