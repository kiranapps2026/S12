"""
Runtime ExecutionContext diff protection tests (post-R0).

These tests ensure that:
1. ExecutionContext cannot be mutated in place (frozen dataclass)
2. Only whitelisted fields may change between stages
3. Resolution fields (binding_id, provider, etc.) are NOT on ExecutionContext —
   they live on FrozenBindingIdentity (R1/B5)

Source: DATA_CONTRACTS.md §2 Critical Rules, PIPELINE_STAGES.md §11
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from contracts.execution_context import ExecutionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_context(**overrides) -> ExecutionContext:
    """Create a minimal ExecutionContext for testing (matches actual post-R0 fields)."""
    defaults = {
        "trace_id": "trace-001",
        "request_id": "req-001",
        "tenant_id": "tenant-001",
        "user_id": "user-001",
        "workspace_id": "ws-001",
        "conversation_id": "conv-001",
        "connection_id": "conn-001",
        # S5 policy version whitelist (only fields addable after S0)
        "tenant_policy_version_id": None,
        "workspace_policy_version_id": None,
        "policy_version_id": None,
    }
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def diff_contexts(before: ExecutionContext, after: ExecutionContext) -> dict[str, tuple]:
    """Return dict of changed fields: {field: (before_value, after_value)}."""
    changes = {}
    for field in type(before).__dataclass_fields__:
        b = getattr(before, field)
        a = getattr(after, field)
        if b != a:
            changes[field] = (b, a)
    return changes


# ---------------------------------------------------------------------------
# S0–S11 field whitelist (post-R0: raw_input/sanitized_input/trace/execution_mode removed)
# ---------------------------------------------------------------------------

STAGE_FIELD_WHITELIST: dict[str, tuple[str, ...]] = {
    "S0": (
        "trace_id", "request_id", "conversation_id", "connection_id",
        "tenant_id", "workspace_id", "user_id",
    ),
    "S1": (),
    "S2": ("task_id",),
    "S5": (
        "tenant_policy_version_id",
        "workspace_policy_version_id",
        "policy_version_id",
    ),
    "S8": ("auth_passed", "auth_result_id"),
}


def validate_context_changes(stage_id: str, before: ExecutionContext, after: ExecutionContext) -> None:
    """
    Validate that only whitelisted fields changed between before and after.

    Raises AssertionError if any unapproved field changed.
    """
    if before is after:
        raise AssertionError(
            f"ExecutionContext was not replaced at {stage_id}. "
            f"Handlers must use dataclasses.replace(), not in-place mutation."
        )

    whitelist = STAGE_FIELD_WHITELIST.get(stage_id, ())
    changes = diff_contexts(before, after)

    unauthorized = []
    for field, (old, new) in changes.items():
        if field not in whitelist:
            unauthorized.append(f"{field}: {old!r} -> {new!r}")

    if unauthorized:
        raise AssertionError(
            f"Stage {stage_id} changed unauthorized ExecutionContext fields: "
            f"{', '.join(unauthorized)}. "
            f"Whitelist for {stage_id}: {whitelist}"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExecutionContextNoInPlaceMutation:
    """ExecutionContext cannot be mutated in place."""

    def test_replace_returns_new_instance(self):
        """dataclasses.replace() returns a new instance."""
        ctx = create_context()
        new = replace(ctx, trace_id="trace-new")
        assert new is not ctx

    def test_replace_preserves_original(self):
        """Original context is unchanged after replace."""
        ctx = create_context()
        replace(ctx, trace_id="trace-new")
        assert ctx.trace_id == "trace-001"

    def test_frozen_prevents_attribute_assignment(self):
        """Frozen dataclass prevents attribute assignment."""
        ctx = create_context()
        with pytest.raises(FrozenInstanceError):
            ctx.intent = {"type": "read"}


class TestExecutionContextFieldWhitelist:
    """Only whitelisted fields may change per stage (post-R0)."""

    def test_s0_can_set_identity_fields(self):
        """S0 can set identity fields."""
        ctx = create_context()
        new = replace(
            ctx,
            trace_id="trace-new",
            request_id="req-new",
            tenant_id="tenant-new",
        )
        changes = diff_contexts(ctx, new)
        for field in changes:
            assert field in STAGE_FIELD_WHITELIST["S0"]

    def test_s2_can_set_task_id(self):
        """S2 can set task_id."""
        ctx = create_context()
        new = replace(
            ctx,
            task_id="task-123",
        )
        changes = diff_contexts(ctx, new)
        for field in changes:
            assert field in STAGE_FIELD_WHITELIST["S2"]

    def test_s5_can_set_policy_version_fields(self):
        """S5 can set policy version fields (whitelist post-R0)."""
        ctx = create_context()
        new = replace(
            ctx,
            tenant_policy_version_id="pv-1",
            workspace_policy_version_id="wpv-1",
            policy_version_id="pv-1",
        )
        changes = diff_contexts(ctx, new)
        for field in changes:
            assert field in STAGE_FIELD_WHITELIST["S5"]

    def test_no_binding_fields_on_context(self):
        """No binding fields on ExecutionContext (R1/B5)."""
        fields = type(create_context()).__dataclass_fields__
        assert 'provider' not in fields, "provider must be on FrozenBindingIdentity, not ExecutionContext"
        assert 'binding_id' not in fields
        assert 'capability_id' not in fields
        assert 'kernel_op_id' not in fields

    def test_other_stages_have_empty_or_no_whitelist(self):
        """S3, S4, S6, S7, S9, S10, S11 have empty whitelists."""
        empty_stages = {"S3", "S4", "S6", "S7", "S9", "S10", "S11"}
        for stage in empty_stages:
            assert STAGE_FIELD_WHITELIST.get(stage, ()) == ()

    def test_s5_writes_only_policy_versions(self):
        """S5 may ONLY set policy version fields (not task_id, not auth fields)."""
        ctx = create_context()
        allowed = {"tenant_policy_version_id", "workspace_policy_version_id", "policy_version_id"}
        new = replace(ctx,
            tenant_policy_version_id="pv-1",
            workspace_policy_version_id="wpv-1",
            policy_version_id="pv-2",
        )
        changes = diff_contexts(ctx, new)
        for field in changes:
            assert field in allowed, f"S5 wrote unapproved field: {field}"

    def test_s8_writes_only_auth_fields(self):
        """S8 may ONLY set auth_passed and auth_result_id."""
        ctx = create_context()
        allowed = {"auth_passed", "auth_result_id"}
        new = replace(ctx, auth_passed=True, auth_result_id="auth-1")
        changes = diff_contexts(ctx, new)
        for field in changes:
            assert field in allowed, f"S8 wrote unapproved field: {field}"


class TestValidateContextChanges:
    """validate_context_changes() enforces the whitelist."""

    def test_no_changes_passes(self):
        """No changes is valid (must be different instances, not same object)."""
        ctx1 = create_context()
        ctx2 = replace(ctx1)
        validate_context_changes("S0", ctx1, ctx2)

    def test_whitelisted_changes_pass(self):
        """Whitelisted changes pass validation."""
        ctx = create_context()
        new = replace(ctx, task_id="task-123")
        validate_context_changes("S2", ctx, new)

    def test_in_place_mutation_raises(self):
        """In-place mutation raises AssertionError."""
        ctx = create_context()
        with pytest.raises(AssertionError, match="not replaced"):
            validate_context_changes("S0", ctx, ctx)

    def test_unauthorized_field_change_raises(self):
        """Unauthorized field change raises AssertionError."""
        ctx = create_context()
        # S1 has empty whitelist — changing any field is unauthorized
        new = replace(ctx, task_id="different")
        with pytest.raises(AssertionError, match="unauthorized"):
            validate_context_changes("S1", ctx, new)


# ---------------------------------------------------------------------------
# S5 whitelist through the real handler (R-E)
# ---------------------------------------------------------------------------

def test_s5_writes_only_policy_version_fields():
    """Running the real S5 changes exactly policy_version_id on the ExecutionContext."""
    from tests.fixtures.scenarios import make_scenario
    from tests.fixtures.states import run_stage, state_ready_for

    sc = make_scenario(mutation="W", risk=0.3)
    before = state_ready_for("S5", sc)
    after = run_stage("S5", before, sc)
    changed = {
        f for f in ExecutionContext.__dataclass_fields__
        if getattr(before.execution_context, f) != getattr(after.execution_context, f)
    }
    assert changed == {"policy_version_id"}
    assert after.execution_context.policy_version_id == "policy-1"
