"""Canonical vocabulary for S0–S11 (DATA_CONTRACTS §2, §4, §5, §20a, §21).

Every string that crosses a stage boundary is one of these enum members, so a typo
is an import error, not a silent mismatch.
"""
from __future__ import annotations

from enum import StrEnum


class StageStatus(StrEnum):
    """Stage outcome (DATA_CONTRACTS §20a). Anything but NORMAL stops the run."""

    NORMAL = "normal"
    CLARIFY = "clarify"
    DENY = "deny"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    WORKER = "worker"
    SYSTEM = "system"


class ActivationMode(StrEnum):
    """How the request entered the system (PIPELINE_STAGES §2 step 1)."""

    HUMAN = "human"
    SCHEDULE = "schedule"
    API = "api"
    EVENT_DRIVEN = "event_driven"
    INTERNAL = "internal"


class Mutation(StrEnum):
    """Mutation class of an operation, in increasing order of danger."""

    READ = "R"
    WRITE = "W"
    DELETE = "D"
    IRREVERSIBLE = "IRREVERSIBLE"

    @property
    def severity(self) -> int:
        return _MUTATION_ORDER.index(self)


_MUTATION_ORDER = (Mutation.READ, Mutation.WRITE, Mutation.DELETE, Mutation.IRREVERSIBLE)


class TruthState(StrEnum):
    """Lifecycle of a capability or kernel operation (DATA_CONTRACTS §5)."""

    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    PRODUCTION_ENABLED = "PRODUCTION_ENABLED"
    DEPRECATED = "DEPRECATED"


class RetrySafety(StrEnum):
    SAFE = "safe"
    IDEMPOTENT = "idempotent"
    NEVER = "never"


class GraphType(StrEnum):
    SIMPLE = "simple"
    CHAIN = "chain"
    COMPLEX = "complex"


class PathDecision(StrEnum):
    """Execution path (DATA_CONTRACTS §21). AGENTIC is reserved for M2 and never chosen."""

    FAST = "fast"
    WORKFLOW = "workflow"
    AGENTIC = "agentic"
    CLARIFY = "clarify"
    DENY = "deny"


class ConfirmationStatus(StrEnum):
    """S10 outcome. PENDING suspends the run until the user replies."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    HALF_OPEN = "HALF_OPEN"
    OPEN = "OPEN"


class RecordStatus(StrEnum):
    """Live status of a user, tenant or connection (SECURITY §3)."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    REVOKED = "revoked"
    DELETED = "deleted"
