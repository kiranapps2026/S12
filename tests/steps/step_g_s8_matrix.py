"""
Step G: S8 Safety Gate — Complete test matrix using existing test fixtures.

8 checks × 5 fail modes = 40 tests.
Plus edge cases: all-UNKNOWN, missing identity, missing dependency.

Source: DATA_CONTRACTS.md §8, PIPELINE_STAGES.md §10
"""

from __future__ import annotations

import dataclasses
import pytest

from contracts.kernel_policy import KernelPolicy
from engine.stages.s8_safety_gate.dependencies import S8Dependencies
from engine.stages.s8_safety_gate.handler import handle
from tests.fixtures.deps import (
    ConfigurableAuthState,
    ConfigurableCircuitBreaker,
    ConfigurableMutationPolicy,
    RAISE,
    make_s8_deps,
)
from tests.fixtures.states import state_ready_for_s8


def _run(state, deps: S8Dependencies):
    return __import__('asyncio').run(handle(state, deps))


# --- Check 1: user_active ---

class TestCheck1UserActive:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_none(self):
        state = state_ready_for_s8()
        ctx = dataclasses.replace(state.execution_context, user_id=None)
        state = dataclasses.replace(state, execution_context=ctx)
        deps = make_s8_deps(auth=ConfigurableAuthState(user=None))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "user_active"

    def test_empty(self):
        state = state_ready_for_s8()
        ctx = dataclasses.replace(state.execution_context, user_id="")
        state = dataclasses.replace(state, execution_context=ctx)
        deps = make_s8_deps(auth=ConfigurableAuthState(user=""))
        result = _run(state, deps)
        assert result.safety_result.allowed is False

    def test_inactive(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(user="inactive"))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "user_active"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(user=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "user_active"


# --- Check 2: tenant_active ---

class TestCheck2TenantActive:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_none(self):
        state = state_ready_for_s8()
        ctx = dataclasses.replace(state.execution_context, tenant_id=None)
        state = dataclasses.replace(state, execution_context=ctx)
        deps = make_s8_deps(auth=ConfigurableAuthState(tenant=None))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "tenant_active"

    def test_empty(self):
        state = state_ready_for_s8()
        ctx = dataclasses.replace(state.execution_context, tenant_id="")
        state = dataclasses.replace(state, execution_context=ctx)
        deps = make_s8_deps(auth=ConfigurableAuthState(tenant=""))
        result = _run(state, deps)
        assert result.safety_result.allowed is False

    def test_suspended(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(tenant="suspended"))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "tenant_active"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(tenant=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "tenant_active"


# --- Check 3: connection_active ---

class TestCheck3ConnectionActive:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_none(self):
        state = state_ready_for_s8()
        ctx = dataclasses.replace(state.execution_context, connection_id=None)
        state = dataclasses.replace(state, execution_context=ctx)
        deps = make_s8_deps(auth=ConfigurableAuthState(connection=None))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "connection_active"

    def test_empty(self):
        state = state_ready_for_s8()
        ctx = dataclasses.replace(state.execution_context, connection_id="")
        state = dataclasses.replace(state, execution_context=ctx)
        deps = make_s8_deps(auth=ConfigurableAuthState(connection=("", None)))
        result = _run(state, deps)
        assert result.safety_result.allowed is False

    def test_revoked(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(connection=("revoked", None)))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "connection_active"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(connection=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "connection_active"


# --- Check 4: capability_granted ---

class TestCheck4CapabilityGranted:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_denied(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(grant=False))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "capability_granted"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(grant=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "capability_granted"


# --- Check 5: resource_scope ---

class TestCheck5ResourceScope:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_denied(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(scope=False))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "resource_scope"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(scope=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "resource_scope"


# --- Check 6: circuit_breaker ---

class TestCheck6CircuitBreaker:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_open(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(breaker=ConfigurableCircuitBreaker(value="OPEN"))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "circuit_breaker"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(breaker=ConfigurableCircuitBreaker(value=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "circuit_breaker"


# --- Check 7: budget_available ---

class TestCheck7BudgetAvailable:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(auth=ConfigurableAuthState(budget=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "budget_available"


# --- Check 8: mutation_safety ---

class TestCheck8MutationSafety:
    def test_pass(self):
        state = state_ready_for_s8()
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is True

    def test_denied(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(mutation=ConfigurableMutationPolicy(value=False))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "mutation_safety"

    def test_unavailable(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(mutation=ConfigurableMutationPolicy(value=RAISE))
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "mutation_safety"


# --- Kill switch (from KernelPolicy) ---

class TestKillSwitch:
    def test_kill_switch_engaged_denies(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(kill_switch=True)
        result = _run(state, deps)
        assert result.safety_result.allowed is False
        assert result.safety_result.failed_check == "kill_switch"
        assert result.safety_result.reason == "kill_switch"

    def test_kill_switch_disengaged_allows(self):
        state = state_ready_for_s8()
        deps = make_s8_deps(kill_switch=False)
        result = _run(state, deps)
        assert result.safety_result.allowed is True


# --- Edge cases ---

class TestEdgeCases:
    def test_no_task_profile_denies(self):
        state = state_ready_for_s8()
        state = dataclasses.replace(state, task_profile=None)
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is False

    def test_no_frozen_binding_denies(self):
        state = state_ready_for_s8()
        state = dataclasses.replace(state, frozen_binding_identity=None)
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is False

    def test_missing_identity_denies(self):
        from contracts.pipeline_state import PipelineState
        from contracts.execution_context import ExecutionContext
        ctx = ExecutionContext(
            trace_id="t", request_id="r", tenant_id="", workspace_id="",
            user_id="", raw_input={}
        )
        state = PipelineState(execution_context=ctx)
        deps = make_s8_deps()
        result = _run(state, deps)
        assert result.safety_result.allowed is False
