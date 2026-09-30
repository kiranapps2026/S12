"""
S0 Entry/Parse — tests.

Tests cover:
- ExecutionContext creation with correct identity
- Request ID generation
- Trace ID generation
- Tenant isolation
- Raw input preservation
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from contracts.execution_context import ExecutionContext
from engine.stages.s0_entry.handler import EntryRequest, handle as s0_handle
from contracts.pipeline_state import PipelineState


def _empty_context():
    """Create a minimal ExecutionContext for S0 initial state."""
    return ExecutionContext(
        trace_id="",
        request_id="",
        tenant_id="",
        user_id="",
        workspace_id="",
        conversation_id=None,
        connection_id=None,
        raw_input={},
    )


class TestS0EntryParse:
    @pytest.fixture
    def entry_request(self):
        """Create an EntryRequest for S0."""
        return EntryRequest(
            raw_payload={"message": "hello"},
            entry_channel="api",
            tenant_id="tenant-001",
            user_id="user-001",
            workspace_id="ws-001",
            conversation_id="conv-001",
            connection_id="conn-001",
        )

    def test_creates_execution_context(self, entry_request):
        """S0 creates a new ExecutionContext (returns PipelineState)."""
        result = asyncio.run(s0_handle(entry_request))

        assert result is not None
        assert result.execution_context is not None
        assert result.execution_context.trace_id != ""
        assert result.execution_context.request_id != ""

    def test_generates_ids(self, entry_request):
        """S0 generates trace_id and request_id."""
        state = asyncio.run(s0_handle(entry_request))

        assert len(state.execution_context.trace_id) > 0
        assert len(state.execution_context.request_id) > 0
        assert state.execution_context.trace_id != state.execution_context.request_id

    def test_preserves_tenant_isolation(self, entry_request):
        """S0 preserves tenant isolation."""
        state = asyncio.run(s0_handle(entry_request))

        assert state.execution_context.tenant_id == "tenant-001"
        assert state.execution_context.user_id == "user-001"

    def test_stores_entry_request(self, entry_request):
        """S0 stores the unmodified EntryRequest in entry_request."""
        state = asyncio.run(s0_handle(entry_request))

        assert state.entry_request is not None
        assert state.entry_request.raw_payload == {"message": "hello"}

    def test_sets_conversation_id(self, entry_request):
        """S0 sets conversation_id."""
        state = asyncio.run(s0_handle(entry_request))

        assert state.execution_context.conversation_id == "conv-001"

    def test_identity_comes_from_entry_not_defaults(self, entry_request):
        """workspace_id is its own value, never the tenant_id (A5)."""
        ctx = asyncio.run(s0_handle(entry_request)).execution_context
        assert (ctx.tenant_id, ctx.workspace_id) == ("tenant-001", "ws-001")

    @pytest.mark.parametrize("missing", ["tenant_id", "workspace_id", "user_id"])
    def test_missing_identity_denies(self, entry_request, missing):
        """A missing identity value is a DENY missing_<field>; no context is created."""
        state = asyncio.run(s0_handle(dataclasses.replace(entry_request, **{missing: None})))
        assert state.execution_context is None
        assert (str(state.stage_status).lower(), state.deny_reason) == ("deny", f"missing_{missing}")
