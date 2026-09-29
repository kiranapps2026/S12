"""
Step H: Runtime no-re-resolve test.

After S5, no stage re-resolves:
- Risk computation (once at S5, frozen in FrozenBindingIdentity)
- Mutation detection (frozen at S5)
- Provider resolution (frozen at S5)

Proof: In a single pipeline run, binding_id is preserved from S5 through S11.
If any stage recomputed, the binding values would differ.

Source: DATA_CONTRACTS §6, FINAL_ARCHITECTURE §14
"""

from __future__ import annotations

import asyncio
import dataclasses

from contracts.kernel_policy import KernelPolicy
from contracts.safety import SafetyResult
from tests.fixtures.states import state_ready_for, make_scenario, tamper
from tests.fixtures.deps import make_s8_deps


class TestNoReResolve:
    """After S5, binding identity is immutable through S11."""

    def test_s6_uses_frozen_binding_values(self):
        """S6 TaskProfile carries S5's frozen risk/mutation/provider — not recomputed."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.3))
        binding = state.frozen_binding_identity
        assert binding is not None
        tp = state.task_profile
        assert tp is not None

        # Within a single run, TaskProfile values equal the frozen binding's values
        assert tp.risk == binding.effective_risk
        assert tp.mutations[0] == binding.effective_mutation
        assert tp.providers == (binding.provider,)

    def test_binding_immutable_through_s8(self):
        """Binding values unchanged from S7→S8 (frozen at S5)."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.3))
        binding = state.frozen_binding_identity
        assert binding is not None
        saved_binding_id = binding.binding_id
        saved_risk = binding.effective_risk
        saved_mutation = binding.effective_mutation
        saved_provider = binding.provider

        # S8 preserves the binding (no re-resolution)
        result = asyncio.run(
            __import__('engine.stages.s8_safety_gate.handler', fromlist=['handle']).handle(state, make_s8_deps())
        )
        assert result.frozen_binding_identity.binding_id == saved_binding_id
        assert result.frozen_binding_identity.effective_risk == saved_risk
        assert result.frozen_binding_identity.effective_mutation == saved_mutation
        assert result.frozen_binding_identity.provider == saved_provider

    def test_binding_immutable_through_s11(self):
        """Full pipeline S8→S9→S10→S11: binding_id never changes."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.3))
        saved_binding_id = state.frozen_binding_identity.binding_id
        assert saved_binding_id is not None

        # Add safety_result (S8 would have set this)
        state = tamper(state, safety_result=SafetyResult(
            allowed=True, reason=None, failed_check=None,
        ))

        # S9: real handler
        from engine.stages.s9_plan_creation.handler import handle as s9_handle
        state = asyncio.run(s9_handle(state))

        # S10: real handler
        from engine.stages.s10_confirmation.handler import handle as s10_handle
        state = asyncio.run(s10_handle(state))

        # S11: real handler
        s11 = asyncio.run(
            __import__('engine.stages.s11_plan_validation.handler', fromlist=['handle']).handle(state)
        )

        # Binding is frozen — same identity through S8→S11
        assert s11.frozen_binding_identity is not None
        assert s11.frozen_binding_identity.binding_id == saved_binding_id
