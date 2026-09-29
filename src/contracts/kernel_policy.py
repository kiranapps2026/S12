"""
Kernel policy — runtime policy for the execution kernel.

Source: DATA_CONTRACTS.md §11, SECURITY.md §7, RUNBOOK R-Y
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KernelPolicy:
    """
    Runtime policy that governs kernel behavior.

    Loaded at startup, versioned, never changed during execution.
    Per R-Y: metadata removed (callers add named fields instead).
    kill_switch_engaged and risk_deny_threshold are required (no defaults).
    """
    kill_switch_engaged: bool            # True = all executions denied
    risk_deny_threshold: float           # Risk above this -> DENY (e.g. 0.95)

    # Defaults follow (required fields must be first)
    max_retry_attempts: int = 2
    default_timeout_seconds: float = 300.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_seconds: int = 60
    max_delegation_depth: int = 3
    max_concurrent_executions_per_tenant: int = 100
    budget_reservation_timeout_seconds: int = 30
    confirmation_timeout_seconds: int = 3600
    verification_max_attempts: int = 3
    verification_attempt_interval_seconds: int = 1
    verification_timeout_seconds: int = 5
    llm_call_timeout_seconds: int = 120
    max_llm_calls_per_execution: int = 2
    enable_mutation_safety: bool = True
    enable_tenant_isolation: bool = True
    enable_audit_log: bool = True
    enable_event_replay: bool = True


@dataclass(frozen=True)
class PolicyVersions:
    """Policy versions in force for one tenant and workspace; S5 records them (R-E)."""
    tenant_policy_version_id: str
    workspace_policy_version_id: str
    policy_version_id: str
