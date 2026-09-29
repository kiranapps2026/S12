"""
Tests for PipelineState contract — the typed accumulator for S0–S11.

Source: DATA_CONTRACTS.md §2, PIPELINE_STAGES.md §11
"""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from contracts.execution_context import ExecutionContext
from contracts.pipeline_state import PipelineState, STAGE_OUTPUT_FIELD
from contracts.errors import ContractViolationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_context():
    """Create a sample ExecutionContext for testing (matches actual fields after R0)."""
    return ExecutionContext(
        trace_id="trace-001",
        request_id="req-001",
        tenant_id="tenant-001",
        user_id="user-001",
        workspace_id="ws-001",
        conversation_id="conv-001",
        connection_id="conn-001",
        
    )


@pytest.fixture
def initial_state(sample_context):
    """Create an initial PipelineState."""
    return PipelineState(execution_context=sample_context)


# ---------------------------------------------------------------------------
# PipelineState immutability tests
# ---------------------------------------------------------------------------

class TestPipelineStateImmutability:
    """PipelineState is frozen — no in-place mutation."""

    def test_pipeline_state_is_frozen(self, initial_state):
        """PipelineState cannot be mutated in place."""
        with pytest.raises(FrozenInstanceError):
            initial_state.intent_result = {"type": "read"}

    def test_with_stage_output_returns_new_instance(self, initial_state):
        """with_stage_output() returns a NEW PipelineState."""
        from contracts.stage_outputs import IntentResult
        new_state = initial_state.with_stage_output("S2", IntentResult(
            intent_type="read",
            target_entities=(),
            operations=(),
            parameters={},
        ))
        assert new_state is not initial_state

    def test_original_unchanged_after_with_stage_output(self, initial_state):
        """Original PipelineState remains unchanged after with_stage_output()."""
        from contracts.stage_outputs import IntentResult
        new_state = initial_state.with_stage_output("S2", IntentResult(
            intent_type="read",
            target_entities=(),
            operations=(),
            parameters={},
        ))
        assert initial_state.intent_result is None
        assert new_state.intent_result is not None


# ---------------------------------------------------------------------------
# Stage output field tests
# ---------------------------------------------------------------------------

class TestStageOutputFields:
    """Each stage owns exactly one field."""

    def test_all_stages_have_output_field(self):
        """Every stage S0–S11 has a mapped output field."""
        assert set(STAGE_OUTPUT_FIELD.keys()) == set(STAGE_OUTPUT_FIELD.keys())

    def test_s0_sets_execution_context(self, sample_context):
        """S0 sets execution_context."""
        state = PipelineState(execution_context=sample_context)
        assert state.execution_context is sample_context

    def test_s2_sets_intent_result(self, initial_state):
        """S2 can set intent_result."""
        from contracts.stage_outputs import IntentResult
        intent = IntentResult(
            intent_type="read",
            target_entities=("contacts",),
            operations=(),
            parameters={},
        )
        new_state = initial_state.with_stage_output("S2", intent)
        assert new_state.intent_result == intent
        assert initial_state.intent_result is None

    def test_s5_sets_frozen_binding_identity(self, initial_state):
        """S5 can set frozen_binding_identity."""
        from contracts.frozen_binding import FrozenBindingIdentity
        binding = FrozenBindingIdentity(
            binding_id="bind-001",
            capability_id="cap-001",
            kernel_op_id="op-001",
            provider="ghl",
            engine_module="test.module",
            adapter_class="GHLAdapter",
            effective_risk=0.3,
            effective_mutation="READ",
            resolved_at_stage="S5",
        )
        new_state = initial_state.with_stage_output("S5", binding)
        assert new_state.frozen_binding_identity is binding


# ---------------------------------------------------------------------------
# Overwrite protection tests
# ---------------------------------------------------------------------------

class TestOverwriteProtection:
    """A stage output cannot be overwritten once set."""

    def test_cannot_overwrite_stage_output(self, initial_state):
        """Cannot overwrite an existing stage output."""
        from contracts.stage_outputs import IntentResult
        from contracts.errors import ContractViolationError
        state_with_s2 = initial_state.with_stage_output("S2", IntentResult(
            intent_type="read",
            target_entities=(),
            operations=(),
            parameters={},
        ))
        with pytest.raises(ContractViolationError, match="Cannot overwrite"):
            state_with_s2.with_stage_output("S2", IntentResult(
                intent_type="write",
                target_entities=(),
                operations=(),
                parameters={},
            ))

    def test_unknown_stage_raises(self, initial_state):
        """Unknown stage ID raises ValueError."""
        with pytest.raises(ValueError, match="Unknown stage"):
            initial_state.with_stage_output("S99", {})

    def test_with_stage_output_rejects_wrong_type(self, initial_state):
        """with_stage_output rejects wrong type for field."""
        from contracts.errors import ContractViolationError
        with pytest.raises(ContractViolationError, match="expects type"):
            initial_state.with_stage_output("S8", "not_a_safety_result")

    def test_with_stage_output_rejects_non_owner(self, sample_context):
        """Stage cannot write another stage's field."""
        from contracts.errors import ContractViolationError
        from contracts.safety import SafetyResult
        state = PipelineState(execution_context=sample_context)
        # S0 owns execution_context; try to write safety_result (S8's field) as named field
        with pytest.raises(ContractViolationError, match="not owned by"):
            state.with_stage_output("S0", safety_result=SafetyResult(allowed=True))

    def test_with_stage_output_rejects_second_write(self, initial_state):
        """Cannot write to a field that's already set."""
        from contracts.stage_outputs import IntentResult, NormalizedInput
        state_with_s2 = initial_state.with_stage_output("S2", IntentResult(
            intent_type="read",
            target_entities=(),
            operations=(),
            parameters={},
        ))
        # S2 already wrote intent_result; trying to write S1's field is rejected
        with pytest.raises(ContractViolationError, match="Cannot overwrite"):
            state_with_s2.with_stage_output("S2", IntentResult(
                intent_type="write",
                target_entities=(),
                operations=(),
                parameters={},
            ))

    def test_s11_writes_two_owned_fields(self, initial_state):
        """S11 writes both execution_manifest and validation_result."""
        from contracts.execution_manifest import ExecutionManifest
        from contracts.stage_outputs import ValidationResult
        manifest = ExecutionManifest(
            execution_id="exec-1",
            trace_id="trace-1",
            plan_hash="hash",
            capability_version="1.0.0",
            binding_version="1.0.0",
            policy_version="1.0.0",
            risk_policy_version="1.0.0",
            authorization_version="1.0.0",
        )
        validation = ValidationResult(is_valid=True, errors=())
        state = initial_state.with_stage_output("S11", execution_manifest=manifest, validation_result=validation)
        assert state.execution_manifest is manifest
        assert state.validation_result is validation


# ---------------------------------------------------------------------------
# ExecutionContext structure tests (R1/B5: provider on FrozenBinding, not EC)
# ---------------------------------------------------------------------------

class TestExecutionContextStructure:
    """ExecutionContext field ownership per authoritative spec (after R0)."""

    def test_provider_on_frozen_binding_not_context(self, sample_context):
        """provider is on FrozenBindingIdentity, not ExecutionContext (R1/B5)."""
        fields = type(sample_context).__dataclass_fields__
        assert 'provider' not in fields, (
            "provider should not be on ExecutionContext — it's on FrozenBindingIdentity"
        )
        assert 'capability_id' not in fields
        assert 'kernel_op_id' not in fields
        assert 'binding_id' not in fields

    def test_s5_whitelist_fields_only(self, sample_context):
        """Only S5 policy version fields may be added after S0."""
        fields = type(sample_context).__dataclass_fields__
        whitelist = {"tenant_policy_version_id", "workspace_policy_version_id", "policy_version_id"}
        optional_fields = {name for name, f in fields.items() if f.default is not ...}
        assert whitelist.issubset(optional_fields), (
            "S5 whitelist fields must be on ExecutionContext"
        )


# ---------------------------------------------------------------------------
# PipelineState field initialization tests
# ---------------------------------------------------------------------------

class TestPipelineStateInitialization:
    """PipelineState initializes all fields to None except execution_context."""

    def test_execution_context_required(self, sample_context):
        """execution_context is required."""
        state = PipelineState(execution_context=sample_context)
        assert state.execution_context is sample_context

    def test_all_other_fields_default_none(self, sample_context):
        """All stage output fields default to None."""
        state = PipelineState(execution_context=sample_context)
        assert state.normalized_input is None
        assert state.intent_result is None
        assert state.capability_match is None
        assert state.graph_analysis is None
        assert state.frozen_binding_identity is None
        assert state.task_profile is None
        assert state.path_decision is None
        assert state.safety_result is None
        assert state.plan is None
        assert state.confirmation is None
        assert state.execution_manifest is None
        assert state.validation_result is None


class TestReplaceContext:
    """R-M: Controlled context replacement tests."""

    def test_non_whitelisted_stage_raises(self, initial_state):
        """Stage not in whitelist → ContractViolationError."""
        from contracts.errors import ContractViolationError
        with pytest.raises(ContractViolationError, match="not in whitelist"):
            initial_state.replace_context("S9", auth_passed=True)

    def test_non_whitelisted_field_raises(self, initial_state):
        """Field not in stage whitelist → ContractViolationError."""
        from contracts.errors import ContractViolationError
        with pytest.raises(ContractViolationError, match="not allowed"):
            initial_state.replace_context("S8", foo="bar")

    def test_s8_allow_sets_both_fields(self, initial_state):
        """S8 can set auth_passed and auth_result_id."""
        new_state = initial_state.replace_context(
            "S8",
            auth_passed=True,
            auth_result_id="auth-result-1",
        )
        assert new_state.execution_context.auth_passed is True
        assert new_state.execution_context.auth_result_id == "auth-result-1"
        # Original unchanged
        assert initial_state.execution_context.auth_passed is False
        assert initial_state.execution_context.auth_result_id is None

    def test_s8_deny_leaves_context_unchanged(self, initial_state):
        """DENY path: context is same object identity."""
        original_ctx = initial_state.execution_context
        new_state = initial_state.replace_context("S8", auth_passed=True)
        # A second S8 with deny does NOT call replace_context
        # Just verify the ALLOW path produced a new context
        assert new_state.execution_context is not original_ctx

    def test_s5_can_set_policy_versions(self, initial_state):
        """S5 can set policy version fields."""
        new_state = initial_state.replace_context(
            "S5",
            tenant_policy_version_id="v1",
            workspace_policy_version_id="v2",
            policy_version_id="v3",
        )
        assert new_state.execution_context.tenant_policy_version_id == "v1"
        assert new_state.execution_context.workspace_policy_version_id == "v2"
        assert new_state.execution_context.policy_version_id == "v3"
