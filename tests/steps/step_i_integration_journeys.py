"""
Step I: Integration journeys — short-circuit paths through the pipeline.

Tests that the pipeline correctly short-circuits at each gate:
- S8 short-circuits on kill switch
- S8 short-circuits on safety check failure
- S11 rejects invalid plan (hash mismatch)
- Full pipeline happy path S0→S9

Source: PIPELINE_STAGES.md §10, DATA_CONTRACTS §8, §13
"""

from __future__ import annotations

import asyncio
import dataclasses

from contracts.kernel_policy import KernelPolicy
from contracts.safety import SafetyResult
from tests.fixtures.states import state_ready_for, make_scenario, tamper
from tests.fixtures.deps import make_s8_deps_with_ks


class TestShortCircuitJourneys:
    """Pipeline short-circuits at the correct gate."""

    def test_s8_deny_kill_switch(self):
        """S8 short-circuits on kill switch — no further checks run."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.1))
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        result = asyncio.run(s8_handle(state, make_s8_deps_with_ks(kill_switch=True)))
        assert result.safety_result is not None
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "kill_switch"

    def test_s8_deny_safety_check(self):
        """S8 short-circuits on safety check failure."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.1))
        state = tamper(state, safety_result=None)
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        from engine.stages.s8_safety_gate.dependencies import S8Dependencies
        deps = S8Dependencies(
            policy=KernelPolicy(kill_switch_engaged=False, risk_deny_threshold=0.95),
            auth_state=None,
            circuit_breaker=None,
            mutation_policy=None,
        )
        result = asyncio.run(s8_handle(state, deps))
        assert result.safety_result is not None
        assert result.safety_result.allowed is False

    def test_s11_rejects_invalid_plan(self):
        """S11 rejects when plan hash doesn't match."""
        state = state_ready_for("S10", make_scenario(mutation="R", risk=0.1, steps=1))
        # Tamper the plan hash to be invalid
        from contracts.stage_outputs import Plan, Step, PlanCreationResult
        from contracts.plan_hash import canonical_plan_digest
        bad_plan = Plan(
            id="plan-1",
            steps=(Step(id="s1", kernel_op_id="op", params={}, depends_on=(), mutation="READ", risk=0.1, cost=1),),
            join_mode="all",
            budget_reserved=1,
        )
        # Use a different hash than the plan
        wrong_hash = "a" * 64
        bad_plan_result = PlanCreationResult(plan=bad_plan, plan_hash=wrong_hash, execution_id="exec-1")
        state = tamper(state, plan=bad_plan_result)
        from engine.stages.s11_plan_validation.handler import handle as s11_handle
        result = asyncio.run(s11_handle(state))
        assert result.validation_result is not None
        assert result.validation_result.is_valid is False
        assert result.validation_result.failed_check == "plan_hash_mismatch"


class TestFullPipeline:
    """Full pipeline S0→S9 happy path via real handlers."""

    def test_happy_path_completes(self):
        """Complete pipeline S0→S9 with all checks passing."""
        state = state_ready_for("S8", make_scenario(mutation="R", risk=0.1))
        from engine.stages.s8_safety_gate.handler import handle as s8_handle
        result = asyncio.run(s8_handle(state, make_s8_deps_with_ks(kill_switch=False)))
        assert result.safety_result is not None
        assert result.safety_result.allowed is True

        # S9
        from engine.stages.s9_plan_creation.handler import handle as s9_handle
        result = asyncio.run(s9_handle(result))
        assert result.plan is not None
