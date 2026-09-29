"""S8: kill switch first, eight checks in order, fail closed, auth recorded on allow."""
from __future__ import annotations

import pytest

from supragents.contracts.vocabulary import CircuitState, RecordStatus, StageStatus
from supragents.ports.authorization import ConnectionState
from tests.builders import Harness
from tests.fakes.ports import FakeMutationPolicy, FakePolicy


def _s8(h: Harness):
    return h.run_stage("S8", h.state_before("S8"))


def _denied(state, check, reason):
    assert (state.halt.stage, state.halt.status, state.halt.reason) == ("S8", StageStatus.DENY, reason)
    assert state.safety_result.allowed is False and state.safety_result.failed_check == check
    assert state.execution_context.auth_passed is False


def test_all_checks_pass_records_auth_on_context():
    state = _s8(Harness())
    assert state.halt is None and state.safety_result.allowed is True
    assert state.execution_context.auth_passed is True
    assert state.execution_context.auth_result_id == state.safety_result.result_id


@pytest.mark.parametrize("policy, reason", [
    (FakePolicy(kill_switch=True), "kill_switch_engaged"),
    (FakePolicy(error=True), "kill_switch_unavailable"),
])
def test_kill_switch_is_checked_first(policy, reason):
    h = Harness()
    state = h.state_before("S8")
    h.policy = policy
    h.authorization.user = RecordStatus.SUSPENDED  # would fail check 1; kill switch must win
    _denied(h.run_stage("S8", state), "kill_switch", reason)


@pytest.mark.parametrize("setup, check, reason", [
    (lambda h: setattr(h.authorization, "user", RecordStatus.SUSPENDED), "user_active", "user_inactive"),
    (lambda h: setattr(h.authorization, "tenant", RecordStatus.DELETED), "tenant_active", "tenant_inactive"),
    (lambda h: setattr(h.authorization, "connection", ConnectionState(RecordStatus.REVOKED, None)),
     "connection_active", "connection_inactive"),
    (lambda h: setattr(h.authorization, "connection", ConnectionState(RecordStatus.ACTIVE, h.clock.now())),
     "connection_active", "connection_expired"),
    (lambda h: setattr(h.authorization, "grant", False), "capability_granted", "capability_denied"),
    (lambda h: setattr(h.authorization, "scope", False), "resource_scope", "resource_scope_denied"),
    (lambda h: setattr(h.circuit_breaker, "value", CircuitState.OPEN), "circuit_breaker", "circuit_open"),
    (lambda h: setattr(h.authorization, "budget", False), "budget_available", "budget_exceeded"),
    (lambda h: setattr(h, "mutation_policy", FakeMutationPolicy(permit=False)),
     "mutation_safety", "mutation_not_permitted"),
])
def test_each_failing_check_denies_with_its_reason(setup, check, reason):
    h = Harness()
    setup(h)
    _denied(_s8(h), check, reason)


@pytest.mark.parametrize("port, check", [
    ("user", "user_active"), ("tenant", "tenant_active"), ("connection", "connection_active"),
    ("grant", "capability_granted"), ("scope", "resource_scope"), ("budget", "budget_available"),
])
def test_unanswerable_check_fails_closed(port, check):
    h = Harness()
    h.authorization.failing.add(port)
    _denied(_s8(h), check, f"{check}_unavailable")


def test_non_boolean_answers_deny():
    h = Harness()
    h.authorization.grant = "yes"
    _denied(_s8(h), "capability_granted", "capability_denied")


def test_checks_receive_frozen_s5_values():
    h = Harness()
    state = _s8(h)
    frozen = state.frozen_binding
    assert h.mutation_policy.calls == [(frozen.effective_mutation, frozen.effective_risk)]
    assert h.authorization.grant_calls == [frozen.capability_id]
