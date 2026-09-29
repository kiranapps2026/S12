"""
Shared S8 safety check functions.

Pure functions that evaluate one safety rule and return a CheckResult.
Source: DATA_CONTRACTS §8, PIPELINE_STAGES §10, RUNBOOK R-B, R-D

Every check follows one pattern:
- missing id -> "<check>_missing_id"
- deps/provider missing/None -> "<check>_unavailable"
- exception -> "<check>_unavailable"
- unknown or wrong-type value -> "<check>_invalid"
- rule not met -> check-specific reason
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from contracts.safety import TaskProfile
from contracts.execution_context import ExecutionContext
from contracts.authorization_state_provider import AuthorizationStateProvider
from engine.stages.s8_safety_gate.dependencies import (
    S8Dependencies,
    CircuitBreaker,
    MutationPolicy,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    reason: str | None = None


ACTIVE = "active"
KNOWN_INACTIVE = frozenset({"inactive", "suspended", "deactivated", "revoked", "deleted"})


def check_user_active(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 1: user status == active."""
    name = "user_active"
    if not context.user_id:
        return CheckResult(name, False, "user_active_missing_id")
    if deps is None or deps.auth_state is None:
        return CheckResult(name, False, "user_active_unavailable")
    try:
        status = deps.auth_state.user_status(context.user_id)
    except Exception:
        return CheckResult(name, False, "user_active_unavailable")
    if status is None:
        return CheckResult(name, False, "user_active_unavailable")
    if not isinstance(status, str) or (status != ACTIVE and status not in KNOWN_INACTIVE):
        return CheckResult(name, False, "user_active_invalid")
    if status != ACTIVE:
        return CheckResult(name, False, "user_active_inactive")
    return CheckResult(name, True, None)


def check_tenant_active(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 2: tenant status == active."""
    name = "tenant_active"
    if not context.tenant_id:
        return CheckResult(name, False, "tenant_active_missing_id")
    if deps is None or deps.auth_state is None:
        return CheckResult(name, False, "tenant_active_unavailable")
    try:
        status = deps.auth_state.tenant_status(context.tenant_id)
    except Exception:
        return CheckResult(name, False, "tenant_active_unavailable")
    if status is None:
        return CheckResult(name, False, "tenant_active_unavailable")
    if not isinstance(status, str) or (status != ACTIVE and status not in KNOWN_INACTIVE):
        return CheckResult(name, False, "tenant_active_invalid")
    if status != ACTIVE:
        return CheckResult(name, False, "tenant_active_inactive")
    return CheckResult(name, True, None)


def check_connection_active(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 3: connection status == active and not expired."""
    name = "connection_active"
    if not context.connection_id:
        return CheckResult(name, False, "connection_active_missing_id")
    if deps is None or deps.auth_state is None:
        return CheckResult(name, False, "connection_active_unavailable")
    try:
        result = deps.auth_state.connection_status(context.connection_id)
    except Exception:
        return CheckResult(name, False, "connection_active_unavailable")
    if result is None:
        return CheckResult(name, False, "connection_active_unavailable")
    # Must be a 2-tuple (str, float|None); anything else is _invalid
    if not isinstance(result, tuple) or len(result) != 2:
        return CheckResult(name, False, "connection_active_invalid")
    status, expires_at = result
    if status is None:
        return CheckResult(name, False, "connection_active_unavailable")
    if expires_at is not None and expires_at <= time.time():
        return CheckResult(name, False, "connection_active_expired")
    if not isinstance(status, str) or (status != ACTIVE and status not in KNOWN_INACTIVE):
        return CheckResult(name, False, "connection_active_invalid")
    if status != ACTIVE:
        return CheckResult(name, False, "connection_active_inactive")
    if expires_at is not None and expires_at <= time.time():
        return CheckResult(name, False, "connection_active_expired")
    return CheckResult(name, True, None)


def check_capability_granted(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 4: has_grant(tenant, user, capability) is True."""
    name = "capability_granted"
    capability_id = getattr(frozen_binding, "capability_id", None)
    if not capability_id:
        return CheckResult(name, False, "capability_granted_missing_id")
    if deps is None or deps.auth_state is None:
        return CheckResult(name, False, "capability_granted_unavailable")
    try:
        granted = deps.auth_state.has_grant(
            context.tenant_id or "",
            context.user_id or "",
            capability_id,
        )
    except Exception:
        return CheckResult(name, False, "capability_granted_unavailable")
    if granted is None:
        return CheckResult(name, False, "capability_granted_unavailable")
    if not isinstance(granted, bool):
        return CheckResult(name, False, "capability_granted_invalid")
    if granted is not True:
        return CheckResult(name, False, "capability_denied")
    return CheckResult(name, True, None)


def check_resource_scope(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 5: workspace in tenant/user scope."""
    name = "resource_scope"
    if not context.workspace_id:
        return CheckResult(name, False, "resource_scope_missing_id")
    if deps is None or deps.auth_state is None:
        return CheckResult(name, False, "resource_scope_unavailable")
    try:
        in_scope = deps.auth_state.in_scope(
            context.tenant_id or "",
            context.user_id or "",
            context.workspace_id,
        )
    except Exception:
        return CheckResult(name, False, "resource_scope_unavailable")
    if in_scope is None:
        return CheckResult(name, False, "resource_scope_unavailable")
    if not isinstance(in_scope, bool):
        return CheckResult(name, False, "resource_scope_invalid")
    if in_scope is not True:
        return CheckResult(name, False, "resource_scope_denied")
    return CheckResult(name, True, None)


def check_circuit_breaker(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 6: circuit breaker CLOSED or HALF_OPEN for the provider."""
    name = "circuit_breaker"
    provider_id = getattr(frozen_binding, "provider", None)
    if not provider_id:
        return CheckResult(name, False, "circuit_breaker_missing_id")
    if deps is None or deps.circuit_breaker is None:
        return CheckResult(name, False, "circuit_breaker_unavailable")
    try:
        state = deps.circuit_breaker.state(provider_id)
    except Exception:
        return CheckResult(name, False, "circuit_breaker_unavailable")
    if state is None:
        return CheckResult(name, False, "circuit_breaker_unavailable")
    if not isinstance(state, str):
        return CheckResult(name, False, "circuit_breaker_invalid")
    if state == "OPEN":
        return CheckResult(name, False, "circuit_breaker_open")
    if state not in ("CLOSED", "HALF_OPEN"):
        return CheckResult(name, False, "circuit_breaker_invalid")
    return CheckResult(name, True, None)


def check_budget_available(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 7: budget sufficient for estimated cost."""
    name = "budget_available"
    estimated_cost = getattr(task_profile, "cost", None)
    if estimated_cost is None or estimated_cost <= 0:
        return CheckResult(name, False, f"budget_unavailable: invalid estimated_cost={estimated_cost}")
    if deps is None or deps.auth_state is None:
        return CheckResult(name, False, "budget_available_unavailable")
    try:
        ok = deps.auth_state.budget_available(context.tenant_id or "", estimated_cost)
    except Exception:
        return CheckResult(name, False, "budget_available_unavailable")
    if ok is None:
        return CheckResult(name, False, "budget_available_unavailable")
    if not isinstance(ok, bool):
        return CheckResult(name, False, "budget_available_invalid")
    if ok is not True:
        return CheckResult(name, False, "budget_unavailable")
    return CheckResult(name, True, None)


def check_mutation_safety(
    context: ExecutionContext,
    task_profile: TaskProfile,
    frozen_binding: Any,
    deps: S8Dependencies | None,
) -> CheckResult:
    """Check 8: mutation policy permits the effective mutation and risk."""
    name = "mutation_safety"
    mutation = getattr(frozen_binding, "effective_mutation", None)
    risk = getattr(frozen_binding, "effective_risk", None)
    if mutation is None or risk is None:
        return CheckResult(name, False, "mutation_safety_missing_id")
    if deps is None or deps.mutation_policy is None:
        return CheckResult(name, False, "mutation_safety_unavailable")
    try:
        permitted = deps.mutation_policy.permits(mutation, risk)
    except Exception:
        return CheckResult(name, False, "mutation_safety_unavailable")
    if permitted is None:
        return CheckResult(name, False, "mutation_safety_unavailable")
    if not isinstance(permitted, bool):
        return CheckResult(name, False, "mutation_safety_invalid")
    if permitted is not True:
        return CheckResult(name, False, "mutation_invalid")
    return CheckResult(name, True, None)


# Ordered list of checks: (name, function)
SAFETY_CHECKS: tuple[tuple[str, Any], ...] = (
    ("user_active", check_user_active),
    ("tenant_active", check_tenant_active),
    ("connection_active", check_connection_active),
    ("capability_granted", check_capability_granted),
    ("resource_scope", check_resource_scope),
    ("circuit_breaker", check_circuit_breaker),
    ("budget_available", check_budget_available),
    ("mutation_safety", check_mutation_safety),
)
