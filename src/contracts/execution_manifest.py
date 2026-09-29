"""
Execution Manifest — frozen artifact created at S11, consumed by S12.

Written to execution_manifests table at S11 completion.
Read-only for S12 and all subsequent stages. Never updated after creation.

Source: FINAL_ARCHITECTURE.md §13, §38, DATA_CONTRACTS.md
"""

from __future__ import annotations

from constants import MUTATION_READ

import uuid
from dataclasses import dataclass, field



@dataclass(frozen=True)
class Confirmation:
    """
    Human-in-the-loop confirmation — canonical class matching DATA_CONTRACTS §13.

    S10 produces Confirmation. Status (pending/consumed/rejected/expired) lives
    in the confirmation store, not on this contract.
    """
    confirmation_id: str                   # UUID v4
    user_id: str                           # Who approved
    conversation_id: str                   # Conversation context
    plan_id: str                            # Plan identifier
    plan_hash: str                          # SHA-256 of the plan being confirmed
    operations: tuple[dict, ...]            # Human-readable operation descriptions (immutable)
    expires_at: float                       # Unix timestamp
    consumed_at: float | None = None        # When consumed (None if not yet consumed)


@dataclass(frozen=True)
class ExecutionManifest:
    """
    Frozen artifact created at S11, consumed by S12.

    This is the complete execution specification that S12 and all subsequent
    stages operate on. It is immutable after creation.
    """
    execution_id: str                    # UUID v4
    trace_id: str                         # UUID v4
    plan_hash: str                        # SHA-256 of the execution plan
    capability_version: str               # Capability schema version
    binding_version: str                  # Binding version
    policy_version: str                   # Authorization policy version
    risk_policy_version: str              # Risk policy version
    authorization_version: str            # Authorization version
    auth_result_id: str | None = None     # S8 authorization result ID
    worker_runtime_version: str = ""       # Worker runtime version
    model_version: str = ""                # LLM model version
    created_at: float = 0.0                # Server-authoritative timestamp


class ExecutionOutcome:
    """
    Execution result outcome — canonical enum.

    Source: DATA_CONTRACTS.md §4
    """
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    NOT_EXECUTED = "NOT_EXECUTED"
    DEAD_LETTER = "DEAD_LETTER"


class ExecutionStatus:
    """Execution status — used for execution_runs.status."""
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class KernelResult:
    """
    Result from a kernel operation.

    Source: FINAL_ARCHITECTURE.md §38, DATA_CONTRACTS.md §3
    """
    status: str = "PENDING"
    outcome: str = "NOT_EXECUTED"
    data: dict | None = None               # Result payload
    error: str | None = None               # Error message if failed
    trace: list[str] = field(default_factory=list)  # Ledger event IDs


@dataclass(frozen=True)
class RetryDecision:
    """
    Retry decision with mutation-aware rules.

    Source: DATA_CONTRACTS.md §19, RELIABILITY.md
    """
    should_retry: bool = False
    max_attempts: int = 2
    attempt_number: int = 1
    mutation_type: str = MUTATION_READ
    backoff_seconds: float = 0.0
    reason: str | None = None


@dataclass(frozen=True)
class DeadLetter:
    """
    Dead letter record for failed executions.

    Source: DATA_CONTRACTS.md §23, MUTATION_SAFETY.md §8
    """
    dead_letter_id: str                    # UUID v4
    execution_id: str                      # Parent execution
    mutation_type: str                     # READ, IDEMPOTENT_WRITE, DELETE, IRREVERSIBLE
    error_message: str                     # What failed
    step_id: str | None = None             # Failed step
    reservation_id: str | None = None      # Associated budget reservation
    is_idempotent: bool = False            # Whether retry is safe
    trace: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: 0.0)
    retry_count: int = 0
    is_resumable: bool = False             # Computed from state
    plan_hash: str | None = None           # Plan integrity check



@dataclass(frozen=True)
class LedgerEvent:
    """
    Immutable event in the execution ledger.

    Source: FINAL_ARCHITECTURE.md §40
    """
    event_id: str                          # UUID v4
    event_type: str                        # LEDGER_* event type
    execution_id: str                      # Parent execution
    trace_id: str                          # Trace chain
    stage: str                             # Pipeline stage (S0-S15)
    actor_type: str                        # user, worker, system
    actor_id: str                          # user_id, worker_id, or "system"
    timestamp: float = field(default_factory=lambda: 0.0)
    payload: dict = field(default_factory=dict)
