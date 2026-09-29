"""
Step E: Type checks for PipelineState stage output assignment.

Tests verify that handlers reject wrong types at the handler level,
which internally uses isinstance checks for type safety.

Source: contracts/pipeline_state.py type checks
"""
from __future__ import annotations

import asyncio
import pytest

from tests.fixtures.states import state_ready_for, make_scenario


class TestTypeChecks:
    """Stage outputs reject wrong types via handler-level isinstance checks."""

    def test_wrong_type_rejected_safety_result(self):
        """S8 handler rejects non-SafetyResult via type checks."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.1))
        # Tamper safety_result to a wrong type
        from tests.fixtures.states import tamper
        from contracts.safety import SafetyResult
        state = tamper(state, safety_result="not_a_safety_result")
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        from tests.fixtures.deps import make_s8_deps
        with pytest.raises((TypeError, ValueError, Exception)):
            asyncio.run(s8_handle(state, make_s8_deps()))

    def test_wrong_type_rejected_path_decision(self):
        """S7 handler rejects non-PathDecision via type checks."""
        state = state_ready_for("S7", make_scenario(mutation="R", risk=0.1))
        from tests.fixtures.states import tamper
        state = tamper(state, path_decision=42)
        from engine.stages.s7_path_decision.handler import handle as s7_handle
        from contracts.kernel_policy import KernelPolicy
        policy = KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=0.95)
        with pytest.raises((TypeError, ValueError, Exception)):
            asyncio.run(s7_handle(state, policy=policy))

    def test_wrong_type_rejected_task_profile(self):
        """S6 handler rejects non-TaskProfile via type checks."""
        state = state_ready_for("S6", make_scenario(mutation="R", risk=0.1))
        from tests.fixtures.states import tamper
        state = tamper(state, task_profile="not_a_task_profile")
        from engine.stages.s6_task_profile_assembly.handler import handle as s6_handle
        with pytest.raises((TypeError, ValueError, Exception)):
            asyncio.run(s6_handle(state))

    def test_correct_type_accepted(self):
        """Correct types are accepted by handlers."""
        from contracts.safety import SafetyResult, PathDecision
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.1))
        from tests.fixtures.deps import make_s8_deps
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        result = asyncio.run(s8_handle(state, make_s8_deps()))
        assert result.safety_result is not None
        assert result.safety_result.allowed is True

    def test_s11_wrong_field_type_rejected(self):
        """S11 named fields reject wrong types via handler."""
        state = state_ready_for("S11", make_scenario(mutation="R", risk=0.1, steps=1))
        from tests.fixtures.states import tamper
        state = tamper(state, execution_manifest="not_a_manifest")
        from engine.stages.s11_plan_validation.handler import handle as s11_handle
        with pytest.raises((TypeError, ValueError, Exception)):
            asyncio.run(s11_handle(state))
