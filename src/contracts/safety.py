"""
Safety and task profile contracts.

Source: DATA_CONTRACTS.md §7, §8, MUTATION_SAFETY.md
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskProfile:
    """Complete task profile assembled at S6 from FrozenBindingIdentity.

    Per DATA_CONTRACTS.md §7: intent, capabilities, graph_type,
    steps_estimated, mutations, risk, cost, requires_confirmation,
    resource_scope, providers.
    """
    intent: str                              # From S2 IntentResult
    capabilities: tuple[str, ...]            # Capability IDs
    graph_type: str                          # "simple" | "chain" | "complex"
    steps_estimated: int                     # Number of steps in the graph
    mutations: tuple[str, ...]               # (effective_mutation,) * steps_estimated
    risk: float                              # From FrozenBindingIdentity.effective_risk
    cost: int                                # capability.cost * steps_estimated
    requires_confirmation: bool              # Per confirmation requirements table
    resource_scope: str                      # From ExecutionContext
    providers: tuple[str, ...]               # Provider IDs needed


@dataclass(frozen=True)
class SafetyResult:
    """Safety check result from S8.

    Source: DATA_CONTRACTS.md §8 — fields: allowed, reason, failed_check.
    """
    allowed: bool
    reason: str | None = None
    failed_check: str | None = None


class PathDecision(enum.StrEnum):
    """Path routing decision — canonical enum (lowercase per R-P).

    Source: DATA_CONTRACTS.md §15
    """
    AGENTIC = "agentic"
    CLARIFY = "clarify"
    DENY = "deny"
    FAST = "fast"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class PathRoutingResult:
    """S7 output: routing decision with reason."""
    decision: PathDecision
    reason: str | None = None

    def __eq__(self, other):
        if isinstance(other, PathDecision):
            return self.decision == other
        if isinstance(other, PathRoutingResult):
            return (self.decision, self.reason) == (other.decision, other.reason)
        return NotImplemented

    def __hash__(self):
        return hash(self.decision)
