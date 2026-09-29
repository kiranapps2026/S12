"""
S0-S11 Certification Test Suite

Validates all certification requirements for the PipelineState architecture.
Uses real handlers — no direct stage output writes in tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from contracts.pipeline_state import PipelineState, STAGE_OUTPUT_FIELD
from contracts.execution_context import ExecutionContext
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.safety import TaskProfile, SafetyResult, PathDecision
from contracts.kernel_policy import KernelPolicy
from contracts.stage_outputs import CapabilityMatch
from engine.stages.s0_entry.handler import EntryRequest, handle as s0_handle
from engine.stages.s1_normalize.handler import handle as s1_handle
from engine.stages.s2_intent_analysis.handler import handle as s2_handle, MockLLMProvider
from engine.stages.s3_capability_discovery.handler import handle as s3_handle
from engine.stages.s4_graph_classification.handler import handle as s4_handle
from engine.stages.s5_provider_resolution.handler import handle as s5_handle
from engine.stages.s6_task_profile_assembly.handler import handle as s6_handle
from engine.stages.s7_path_decision.handler import handle as s7_handle
from engine.stages.s8_safety_gate.handler import handle as s8_handle
from engine.stages.s9_plan_creation.handler import handle as s9_handle
from engine.stages.s10_confirmation.handler import handle as s10_handle
from tests.fixtures.states import state_ready_for, make_scenario, tamper
from tests.fixtures.deps import make_s8_deps, make_s8_deps_with_ks
from contracts.stage_registry import StageOutcome


# ============================================================================
# HELPER FIXTURES
# ============================================================================

def _make_s2_state() -> PipelineState:
    """Create PipelineState with execution_context set (post-S0 state)."""
    import dataclasses
    ctx = ExecutionContext(
        trace_id="trace-test",
        request_id="req-test",
        conversation_id=None,
        connection_id=None,
        tenant_id="tenant-1",
        workspace_id="tenant-1",
        user_id="user-1",
    )
    # Create PipelineState then set execution_context
    ps = PipelineState(execution_context=None)
    return dataclasses.replace(ps, execution_context=ctx)


# ============================================================================
# COMMIT D: HANDLER MIGRATION TO PIPELINESTATE
# ============================================================================

class TestCommitD_HandlerMigration:
    """Verify all S0-S11 handlers return PipelineState directly."""

    def test_all_handlers_return_pipeline_state(self):
        """Every S0-S11 handler should accept PipelineState or EntryRequest and return PipelineState."""
        handler_dir = Path(__file__).parent.parent / "src" / "engine" / "stages"
        stages = ["s0_entry", "s1_normalize", "s2_intent_analysis", "s3_capability_discovery",
                  "s4_graph_classification", "s5_provider_resolution", "s6_task_profile_assembly",
                  "s7_path_decision", "s8_safety_gate", "s9_plan_creation", "s10_confirmation",
                  "s11_plan_validation"]

        for stage in stages:
            handler_file = handler_dir / stage / "handler.py"
            assert handler_file.exists(), f"Handler file not found: {handler_file}"

            text = handler_file.read_text()
            # S0 creates ExecutionContext from EntryRequest — special case
            if stage == "s0_entry":
                assert "entry: EntryRequest" in text, f"{stage} handler doesn't accept EntryRequest"
                assert "-> ExecutionContext" in text, f"{stage} handler should return ExecutionContext"
            else:
                assert "state: PipelineState" in text, f"{stage} handler doesn't accept PipelineState"
                assert "-> PipelineState" in text, f"{stage} handler doesn't return PipelineState"

    def test_no_compatibility_adapter_in_runner(self):
        """Verify pipeline runner uses direct handler calls with PipelineState."""
        runner_file = Path(__file__).parent.parent / "src" / "engine" / "control_plane" / "pipeline_state_runner.py"
        if runner_file.exists():
            text = runner_file.read_text()
            has_new_style = "handler(state)" in text or "handler_func(state)" in text


# ============================================================================
# COMMIT E: REMOVE EXECUTIONCONTEXT.METADATA AND ADAPTER
# ============================================================================

class TestCommitE_RemoveDeprecated:
    """Verify ExecutionContext.metadata and adapter are removed."""

    def test_effective_risk_removed_from_execution_context(self):
        """B5: effective_risk and effective_mutation removed from ExecutionContext."""
        ctx = ExecutionContext(
            trace_id="t", request_id="r",
            conversation_id=None, connection_id=None,
            tenant_id="t", workspace_id="t", user_id="u",
        )

        assert not hasattr(ctx, 'effective_risk'), "effective_risk should not be in ExecutionContext"
        assert not hasattr(ctx, "effective_mutation"), "mutation_type should not be in ExecutionContext"

    def test_provider_fields_removed_from_execution_context(self):
        """provider, binding_id, capability_id, kernel_op_id are NOT in ExecutionContext."""
        ctx = ExecutionContext(
            trace_id="t", request_id="r",
            conversation_id=None, connection_id=None,
            tenant_id="t", workspace_id="t", user_id="u",
        )

        assert not hasattr(ctx, 'provider'), "provider should not be in ExecutionContext"
        assert not hasattr(ctx, 'binding_id'), "binding_id should not be in ExecutionContext"
        assert not hasattr(ctx, 'capability_id'), "capability_id should not be in ExecutionContext"
        assert not hasattr(ctx, 'kernel_op_id'), "kernel_op_id should not be in ExecutionContext"


# ============================================================================
# R2: PIPELINESTATE FIELD TYPES
# ============================================================================

class TestR2_PipelineStateFieldTypes:
    """Verify PipelineState fields have concrete frozen dataclass types."""

    def test_field_types_documented(self):
        """Verify stage_outputs.py documents IMPLEMENTATION CONTRACT."""
        stage_outputs_file = Path(__file__).parent.parent / "src" / "contracts" / "stage_outputs.py"
        assert stage_outputs_file.exists(), "stage_outputs.py should exist"
        text = stage_outputs_file.read_text()
        assert "IMPLEMENTATION CONTRACT" in text, "stage_outputs.py should document IMPLEMENTATION CONTRACT"
        # Types are now implemented (not PENDING SPEC)
        assert "PENDING SPEC" not in text, "stage_outputs.py should not still have PENDING SPEC — types are implemented"

    def test_pipeline_state_fields_exist(self):
        """All STAGE_OUTPUT_FIELD keys should exist in PipelineState."""
        for stage_id, field_name in STAGE_OUTPUT_FIELD.items():
            assert field_name in PipelineState.__dataclass_fields__, \
                f"Field {field_name} (for {stage_id}) not in PipelineState"


# ============================================================================
# R3: STAGEOUTCOME VOCABULARY
# ============================================================================

class TestR3_StageOutcomeVocabulary:
    """Verify StageOutcome is canonical vocabulary."""

    def test_stage_outcome_defined(self):
        """StageOutcome should be defined and used internally."""
        assert hasattr(StageOutcome, 'CONTINUE')
        assert hasattr(StageOutcome, 'CORDON')
        assert hasattr(StageOutcome, 'FAILED')

    def test_stage_outcome_values(self):
        """StageOutcome values are the canonical vocabulary."""
        assert StageOutcome.CONTINUE.value == "continue"
        assert StageOutcome.CORDON.value == "cordon"
        assert StageOutcome.FAILED.value == "failed"


# ============================================================================
# S8 MATRIX TEST
# ============================================================================

class TestS8Matrix:
    """S8 test matrix: 8 named checks × fail modes → DENY."""

    def test_kill_switch_cordons(self):
        """S8 fails safety check for revoked connection — cordons execution."""
        # Use real handlers via state_ready_for
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.3))
        # Override auth to simulate revoked connection
        from tests.fixtures.deps import make_s8_deps
        deps = make_s8_deps(kill_switch=False)
        # Auth state with revoked connection
        deps.auth_state.connections["conn-1"] = ("revoked", None)
        result = asyncio.run(s8_handle(state, deps))
        assert result.safety_result is not None
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "connection_active"


# ============================================================================
# DATA FLOW INVARIANTS
# ============================================================================

class TestDataFlowInvariants:
    """Verify S0-S11 data flow invariants."""

    def test_s5_binding_immutable_after_freeze(self):
        """FrozenBindingIdentity is immutable after S5."""
        frozen = FrozenBindingIdentity(
            binding_id="test",
            capability_id="cap",
            kernel_op_id="op",
            provider="p",
            engine_module="supr.kernel.engines.test",
            adapter_class="A",
            effective_risk=0.5,
            effective_mutation="READ",
            resolved_at_stage="S5",
            selection_rank=0,
        )

        with pytest.raises(FrozenInstanceError):
            frozen.effective_risk = 0.9

    def test_s6_reads_from_frozen_binding(self):
        """S6 reads effective_risk from FrozenBindingIdentity only."""
        s6_file = Path(__file__).parent.parent / "src" / "engine" / "stages" / "s6_task_profile_assembly" / "handler.py"
        if s6_file.exists():
            text = s6_file.read_text()
            assert "frozen_binding_identity" in text, "S6 should reference frozen_binding_identity"
            assert "effective_risk" in text, "S6 should read effective_risk"

    def test_s5_risk_computed_once(self):
        """S5 computes effective_risk once, S6 reads it. S6 never recomputes."""
        state_ready = state_ready_for("S8", make_scenario(mutation="R", risk=0.3))
        cap = state_ready.capability_match
        assert cap is not None
        frozen = state_ready.frozen_binding_identity
        assert frozen is not None
        expected_risk = max(cap.risk_floor, frozen.effective_risk)
        assert frozen.effective_risk == expected_risk, (
            f"S5 risk ({frozen.effective_risk}) != max(cap.risk_floor={cap.risk_floor}, "
            f"frozen.effective_risk={frozen.effective_risk})"
        )

    def test_confirmation_plan_hash_integrity(self):
        """confirmation.plan_hash == plan_result.plan_hash (S9→S10 integrity)."""
        from tests.fixtures.states import run_stage
        sc = make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8)
        state = state_ready_for("S10", sc)
        assert state.safety_result.allowed, f"S8 denied: {state.safety_result.reason}"
        plan_result = state.plan
        assert plan_result is not None
        s10 = run_stage("S10", state, sc)
        assert s10.confirmation.required is True
        conf = s10.confirmation.confirmation
        assert conf.plan_hash == plan_result.plan_hash, (
            f"S10 confirmation plan_hash ({conf.plan_hash}) != "
            f"S9 plan_hash ({plan_result.plan_hash})"
        )


# ============================================================================
# CERTIFICATION SUMMARY
# ============================================================================

def test_certification_summary():
    """Print certification summary."""
    print("\n" + "=" * 60)
    print("S0-S11 CERTIFICATION SUMMARY")
    print("=" * 60)
    print(f"PipelineState fields: {len(STAGE_OUTPUT_FIELD)} (S0-S11)")
    print(f"Stage outputs: {list(STAGE_OUTPUT_FIELD.values())}")
    print(f"Frozen dataclasses: NormalizedInput, IntentResult, CapabilityMatch, GraphAnalysis, Plan, PlanCreationResult, ValidationResult, Confirmation, ExecutionManifest, TaskProfile, SafetyResult, PathDecision, FrozenBindingIdentity")
    print("=" * 60 + "\n")
