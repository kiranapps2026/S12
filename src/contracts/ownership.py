"""
Canonical Code Ownership Registry — SINGLE SOURCE OF TRUTH for behavior ownership.

This module defines the single canonical owner for every critical behavior in the
SuprAgents system. No behavior may be implemented outside its canonical owner.

CI enforcement: Any code implementing a behavior outside its canonical module
fails with ARCHITECTURE_DRIFT error.

Source: Audit plan §3 — Canonical Code Ownership
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from functools import lru_cache


# ---------------------------------------------------------------------------
# Ownership Entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OwnershipEntry:
    """Canonical ownership record for a critical behavior."""
    behavior: str
    canonical_owner: str
    canonical_module: str
    allowed_callers: tuple[str, ...]
    forbidden_duplicates: tuple[str, ...]
    test_category: str
    evidence_required: tuple[str, ...] = ()
    security_boundary: bool = False


# ---------------------------------------------------------------------------
# Canonical Ownership Registry
# ---------------------------------------------------------------------------
#
# Every critical behavior has ONE canonical owner.
# No behavior may be implemented outside its canonical module.
# ---------------------------------------------------------------------------

OWNERSHIP_REGISTRY: tuple[OwnershipEntry, ...] = (
    # --- Resolution ---
    OwnershipEntry(
        behavior="Provider resolution",
        canonical_owner="S5 / Resolve Layer",
        canonical_module="src/engine/registry/resolver.py",
        allowed_callers=("S5", "S6"),
        forbidden_duplicates=("adapter", "worker", "provider"),
        test_category="contract:resolver",
        evidence_required=(
            "contract_test: resolver selects correct provider for every capability",
            "failure_test: resolution fails gracefully when no provider matches",
        ),
    ),

    OwnershipEntry(
        behavior="Risk calculation",
        canonical_owner="S5",
        canonical_module="src/engine/registry/risk.py",
        allowed_callers=("S5", "FrozenBindingIdentity"),
        forbidden_duplicates=("S6", "adapter", "worker"),
        test_category="contract:risk",
        evidence_required=(
            "unit_test: risk = max(capability.floor, kernel_op.floor, tag_implied)",
            "mutation_test: risk calculation mutants killed >= 100%",
        ),
        security_boundary=True,
    ),

    # --- Authorization ---
    OwnershipEntry(
        behavior="Authorization",
        canonical_owner="S11 / Authorization Layer",
        canonical_module="src/engine/control_plane/authorization.py",
        allowed_callers=("S11", "S12"),
        forbidden_duplicates=("LLM", "adapter", "worker"),
        test_category="security:authorization",
        evidence_required=(
            "security_test: auth bypass blocked at every boundary",
            "mutation_test: authorization condition mutants killed >= 100%",
            "conformance_test: no alternate auth paths",
        ),
        security_boundary=True,
    ),

    # --- Reliability ---
    OwnershipEntry(
        behavior="Retry decision",
        canonical_owner="Reliability Layer",
        canonical_module="src/engine/reliability/retry.py",
        allowed_callers=("Guard", "S12", "S13", "S14"),
        forbidden_duplicates=("adapter", "worker"),
        test_category="contract:retry",
        evidence_required=(
            "contract_test: W=2 for all mutation types",
            "contract_test: IRREVERSIBLE mutations never retried",
            "failure_test: retry respects mutation safety",
        ),
    ),

    OwnershipEntry(
        behavior="Budget reservation",
        canonical_owner="Budget Tracker",
        canonical_module="src/engine/reliability/budget.py",
        allowed_callers=("S8", "S12"),
        forbidden_duplicates=("adapter", "worker", "S6"),
        test_category="contract:budget",
        evidence_required=(
            "contract_test: reserve/commit/release atomic",
            "contract_test: idempotent reserve",
            "concurrency_test: concurrent reserve handled correctly",
            "mutation_test: budget state transitions mutants killed >= 100%",
        ),
    ),

    OwnershipEntry(
        behavior="Lease acquisition",
        canonical_owner="Lease Manager",
        canonical_module="src/engine/control_plane/lease.py",
        allowed_callers=("S12",),
        forbidden_duplicates=("adapter", "worker", "read-then-insert"),
        test_category="contract:lease",
        evidence_required=(
            "concurrency_test: atomic lease acquisition",
            "failure_test: lease recovery after worker death",
            "conformance_test: no alternate lease paths",
        ),
    ),

    OwnershipEntry(
        behavior="Dead letter routing",
        canonical_owner="DLQ Router",
        canonical_module="src/engine/reliability/dlq.py",
        allowed_callers=("S12", "S13", "S14", "Guard"),
        forbidden_duplicates=("adapter", "worker", "S6"),
        test_category="integration:dlq",
        evidence_required=(
            "integration_test: every failure path routes correctly",
            "contract_test: DeadLetter fields match canonical contract",
        ),
    ),

    OwnershipEntry(
        behavior="Circuit breaker state",
        canonical_owner="Circuit Breaker",
        canonical_module="src/engine/reliability/circuit_breaker.py",
        allowed_callers=("Guard", "S12", "S13"),
        forbidden_duplicates=("adapter", "worker"),
        test_category="contract:circuit_breaker",
        evidence_required=(
            "unit_test: CLOSED→OPEN→HALF_OPEN→CLOSED transitions",
            "unit_test: DEGRADED state handled separately",
            "concurrency_test: circuit state persistence atomic",
            "failure_test: half-open stuck forever prevented",
        ),
    ),

    # --- Provider/Adapter ---
    OwnershipEntry(
        behavior="Provider call",
        canonical_owner="Adapter",
        canonical_module="src/engine/providers/{provider}/adapter.py",
        allowed_callers=("S12", "S13"),
        forbidden_duplicates=("worker", "direct"),
        test_category="contract:adapter",
        evidence_required=(
            "contract_test: all calls go through adapter",
            "contract_test: UNKNOWN propagated correctly",
            "failure_test: timeout returns UNKNOWN, never raises",
        ),
    ),

    # --- Verification ---
    OwnershipEntry(
        behavior="Verification",
        canonical_owner="S13",
        canonical_module="src/engine/control_plane/verification.py",
        allowed_callers=("S13",),
        forbidden_duplicates=("post_execution", "ad_hoc"),
        test_category="contract:verification",
        evidence_required=(
            "contract_test: 6-layer verification enforced",
            "contract_test: UNKNOWN observation never becomes FAIL",
            "failure_test: contradictory observation becomes FAIL",
            "conformance_test: no bypass of verification layer",
        ),
    ),

    # --- Event/Trace ---
    OwnershipEntry(
        behavior="Trace emission",
        canonical_owner="Event Ledger",
        canonical_module="src/engine/control_plane/ledger.py",
        allowed_callers=("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14", "S15"),
        forbidden_duplicates=("adapter", "worker", "ad_hoc_logging"),
        test_category="integration:event-ledger",
        evidence_required=(
            "integration_test: every stage emits LedgerEvent",
            "contract_test: events are immutable after creation",
            "contract_test: trace_id chains all events",
        ),
    ),

    OwnershipEntry(
        behavior="Event correlation",
        canonical_owner="Correlation Engine",
        canonical_module="src/engine/control_plane/correlation.py",
        allowed_callers=("Event Gateway",),
        forbidden_duplicates=("adapter", "worker"),
        test_category="contract:correlation",
        evidence_required=(
            "contract_test: trace_id chains all events",
            "integration_test: correlation survives replays",
        ),
    ),

    # --- State Management ---
    OwnershipEntry(
        behavior="State transition",
        canonical_owner="StateTransitionValidator",
        canonical_module="src/contracts/state_validators.py",
        allowed_callers=("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14", "S15", "Guard"),
        forbidden_duplicates=("ad_hoc", "direct", "raw_update"),
        test_category="contract:state-transitions",
        evidence_required=(
            "contract_test: every illegal transition rejected",
            "mutation_test: state transition mutants killed >= 100%",
            "conformance_test: no direct status updates bypassing validator",
        ),
        security_boundary=True,
    ),

    # --- Memory ---
    OwnershipEntry(
        behavior="Memory persistence",
        canonical_owner="MemoryWriteBarrier",
        canonical_module="src/memory/write_barrier.py",
        allowed_callers=("Memory L0", "Memory L1", "Memory L2", "Memory L3"),
        forbidden_duplicates=("adapter", "worker", "direct"),
        test_category="contract:memory-barrier",
        evidence_required=(
            "contract_test: only MemoryWriteBarrier writes to memory",
            "security_test: worker cannot bypass write barrier",
        ),
    ),

    # --- Tenant Isolation ---
    OwnershipEntry(
        behavior="Tenant isolation",
        canonical_owner="PostgreSQL/RLS",
        canonical_module="src/db/rls/policies.sql",
        allowed_callers=("All DB queries",),
        forbidden_duplicates=("application-level filtering alone",),
        test_category="security:tenant-isolation",
        evidence_required=(
            "security_test: cross-tenant query returns empty",
            "security_test: tenant A cannot access Tenant B data",
            "mutation_test: tenant filter mutants killed >= 100%",
        ),
        security_boundary=True,
    ),

    # --- Configuration ---
    OwnershipEntry(
        behavior="Configuration versioning",
        canonical_owner="Config Version",
        canonical_module="src/contracts/configuration_version.py",
        allowed_callers=("S0", "S11"),
        forbidden_duplicates=("runtime_config_reads",),
        test_category="contract:config-versioning",
        evidence_required=(
            "contract_test: mid-execution config drift impossible",
            "compatibility_test: old config with new code",
        ),
    ),

    # --- Confirmation ---
    OwnershipEntry(
        behavior="Confirmation flow",
        canonical_owner="HITL Controller",
        canonical_module="src/engine/control_plane/confirmation.py",
        allowed_callers=("S10", "S12"),
        forbidden_duplicates=("in_memory", "PlanFreeze"),
        test_category="contract:confirmation",
        evidence_required=(
            "contract_test: S10 creates confirmation token",
            "contract_test: S12 consumes confirmation token",
            "security_test: replay of confirmation token blocked",
        ),
    ),

    OwnershipEntry(
        behavior="Input sanitization",
        canonical_owner="DataSanitizer",
        canonical_module="src/contracts/data_sanitizer.py",
        allowed_callers=("S1",),
        forbidden_duplicates=("adapter", "worker", "S2"),
        test_category="security:injection-defense",
        evidence_required=(
            "security_test: all injection patterns detected",
            "contract_test: severity → action mapping correct",
            "mutation_test: injection pattern detection mutants killed >= 90%",
        ),
        security_boundary=True,
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def get_owner(behavior: str) -> OwnershipEntry | None:
    """Get the canonical owner for a behavior. Returns None if not found."""
    for entry in OWNERSHIP_REGISTRY:
        if entry.behavior == behavior:
            return entry
    return None


def get_all_owners() -> dict[str, OwnershipEntry]:
    """Get all behavior → owner mappings."""
    return {entry.behavior: entry for entry in OWNERSHIP_REGISTRY}


def get_security_boundaries() -> tuple[OwnershipEntry, ...]:
    """Get all behaviors that are security boundaries."""
    return tuple(e for e in OWNERSHIP_REGISTRY if e.security_boundary)


def validate_ownership() -> None:
    """
    Validate the ownership registry at import time.

    Checks:
    - No duplicate behaviors
    - All canonical modules follow naming convention
    - All security boundaries have mutation tests
    """
    behaviors = [e.behavior for e in OWNERSHIP_REGISTRY]
    assert len(behaviors) == len(set(behaviors)), "Duplicate behaviors in ownership registry"

    for entry in OWNERSHIP_REGISTRY:
        assert entry.canonical_module.startswith("src/"), (
            f"Canonical module must start with 'src/': {entry.canonical_module}"
        )
        if entry.security_boundary:
            assert "mutation_test" in "\t".join(entry.evidence_required), (
                f"Security boundary '{entry.behavior}' requires mutation test evidence"
            )


# Validate on import
validate_ownership()
