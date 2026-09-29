"""
Step D: ExecutionContext field cleanup — provider, binding_id, capability_id, kernel_op_id are absent.

Source: DATA_CONTRACTS.md §2, FINAL_ARCHITECTURE.md §7
"""

from __future__ import annotations

import pytest

from contracts.execution_context import ExecutionContext


class TestExecutionContextFields:
    """ExecutionContext must not contain fields that belong on FrozenBindingIdentity."""

    REMOVED_FIELDS = ("provider", "binding_id", "capability_id", "kernel_op_id")

    def test_removed_fields_absent(self):
        """provider, binding_id, capability_id, kernel_op_id are not ExecutionContext fields."""
        for field_name in self.REMOVED_FIELDS:
            assert field_name not in ExecutionContext.__dataclass_fields__, (
                f"{field_name} must not be on ExecutionContext — belongs on FrozenBindingIdentity"
            )

    def test_context_can_construct_without_removed_fields(self):
        """ExecutionContext construction succeeds without removed fields."""
        ctx = ExecutionContext(
            trace_id="trace-1",
            request_id="req-1",
            tenant_id="tenant-1",
            workspace_id="ws-1",
            user_id="user-1",
        )
        assert ctx is not None

    def test_frozen_binding_has_removed_fields(self):
        """Removed fields live on FrozenBindingIdentity, not ExecutionContext."""
        from contracts.frozen_binding import FrozenBindingIdentity
        binding = FrozenBindingIdentity(
            binding_id="bind-1",
            capability_id="cap-1",
            kernel_op_id="op-1",
            provider="local",
            engine_module="test.module",
            adapter_class="A",
            effective_risk=0.5,
            effective_mutation="READ",
            resolved_at_stage="S5",
            selection_rank=0,
        )
        assert binding.provider == "local"
        assert binding.binding_id == "bind-1"
        assert binding.capability_id == "cap-1"
        assert binding.kernel_op_id == "op-1"
