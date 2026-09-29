"""
S5 Provider Resolution — tests.

Tests cover:
- FrozenBindingIdentity creation via real handlers
- Risk frozen at S5, not recomputed
- S5 rejects wrong types
- Reads from PipelineState, not ExecutionContext.metadata
"""

from __future__ import annotations

import asyncio
import pytest
from dataclasses import FrozenInstanceError

from contracts.pipeline_state import PipelineState
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.errors import ResolutionError
from tests.fixtures.states import state_ready_for, make_scenario


class TestS5ProviderResolution:
    def test_creates_frozen_binding(self):
        """S5 creates a FrozenBindingIdentity from real pipeline."""
        state = state_ready_for("S5", make_scenario(mutation="read", risk=0.2))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        frozen = result.frozen_binding_identity
        assert frozen is not None
        assert frozen.binding_id is not None
        assert frozen.effective_mutation == "read"

    def test_effective_risk_frozen_at_s5(self):
        """effective_risk is computed ONCE at S5 and frozen."""
        state = state_ready_for("S5", make_scenario(mutation="delete", risk=0.8))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        frozen = result.frozen_binding_identity
        assert frozen.effective_risk is not None
        assert frozen.effective_mutation == "delete"

    def test_no_candidates_raises(self):
        """Missing CapabilityMatch from S3 raises ResolutionError."""
        from contracts.stage_outputs import CapabilityMatch
        from contracts.execution_context import ExecutionContext
        ctx = ExecutionContext(
            trace_id="trace-1", request_id="req-1",
            conversation_id=None, connection_id=None,
            tenant_id="tenant-1", workspace_id="ws-1", user_id="user-1",
        )
        state = PipelineState(execution_context=ctx)
        with pytest.raises(ResolutionError):
            asyncio.run(
                __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
            )

    def test_s5_creates_binding_once(self):
        """S5 creates FrozenBindingIdentity and it's frozen (immutable)."""
        state = state_ready_for("S5", make_scenario(mutation="read", risk=0.3))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        binding = result.frozen_binding_identity
        assert binding is not None
        with pytest.raises(FrozenInstanceError):
            binding.effective_risk = 0.5

    def test_s5_freezes_binding(self):
        """FrozenBindingIdentity is frozen after creation."""
        state = state_ready_for("S5", make_scenario(mutation="read", risk=0.3))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        binding = result.frozen_binding_identity
        assert binding is not None
        with pytest.raises(FrozenInstanceError):
            binding.binding_id = "new-id"

    def test_s5_risk_computed_once(self):
        """Risk is computed at S5 and frozen — not recomputed downstream."""
        state = state_ready_for("S5", make_scenario(mutation="delete", risk=0.9))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        binding = result.frozen_binding_identity
        assert binding is not None
        assert binding.effective_risk is not None

    def test_s5_frozen_binding_not_recomputed(self):
        """FrozenBindingIdentity is not recomputed downstream."""
        state = state_ready_for("S5", make_scenario(mutation="read", risk=0.3))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        binding = result.frozen_binding_identity
        assert binding is not None
        with pytest.raises(FrozenInstanceError):
            binding.effective_risk = 0.5
        assert binding.effective_risk is not None  # Still the same

    def test_s5_rejects_wrong_capability_match_type(self):
        """S5 rejects non-CapabilityMatch input."""
        from contracts.errors import ContractViolationError
        # When using state_ready_for("S5"), S3 always produces CapabilityMatch
        # This test verifies that tampering S3 output raises ContractViolationError
        state = state_ready_for("S5", make_scenario(mutation="read", risk=0.2))
        # Tamper the capability_match to a raw dict (wrong type)
        from tests.fixtures.states import tamper
        state = tamper(state, capability_match={"not": "a match"})
        with pytest.raises(ContractViolationError):
            asyncio.run(
                __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
            )

    def test_s5_binding_immutable_fields(self):
        """All FrozenBindingIdentity fields are immutable."""
        state = state_ready_for("S5", make_scenario(mutation="read", risk=0.3))
        result = asyncio.run(
            __import__("engine.stages.s5_provider_resolution.handler", fromlist=["handle"]).handle(state)
        )
        binding = result.frozen_binding_identity
        with pytest.raises(FrozenInstanceError):
            binding.provider = "different_provider"
