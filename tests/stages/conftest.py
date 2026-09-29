"""
Shared pytest fixtures for stage tests.
"""

from __future__ import annotations

import pytest

from contracts.execution_context import ExecutionContext
from contracts.kernel_policy import KernelPolicy


@pytest.fixture
def base_context():
    """Base ExecutionContext for most stage tests."""
    return ExecutionContext(
        trace_id="trace-1",
        request_id="req-1",
        conversation_id="conv-1",
        connection_id=None,
        tenant_id="tenant-1",
        workspace_id="ws-1",
        user_id="user-1",
    )


@pytest.fixture
def default_policy():
    """Default KernelPolicy for tests — kill switch off."""
    return KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=0.95)
