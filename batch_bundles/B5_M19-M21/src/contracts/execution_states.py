"""
Persisted S12–S15 enums: the one source for state values and closed code sets (gate C28).

Stored values are always the enum ``.value``. Every CHECK constraint on the columns below lists exactly these values
(migration 015 and earlier; the golden schema test compares them):

    execution_runs.status              ExecutionStatus        (DATA_CONTRACTS §7)
    execution_steps.status             StepState              (DATA_CONTRACTS §19)
    execution_steps.terminal_reason    StepTerminalReason     (gate C22)
    budget_reservations.status         ReservationState       (DATA_CONTRACTS §16; ``pending`` exists only in memory, C3)
    step_reconciliations.status        ReconciliationStatus   (DATA_CONTRACTS §22; ``none`` is never stored, C18)
    step_reconciliations.kind          ReconciliationKind     (C18)
    step_reconciliations.outcome       ReconciliationOutcome  (C18)
    worker_leases.status               LeaseStatus            (C26)
    dead_letters.status                DeadLetterStatus       (C21)
    dead_letters.error_type            DeadLetterErrorType    (C21)
    dead_letters.retry_mode            RetryMode              (C21, D5)
    dead_letters.resolution_outcome    ResolutionOutcome      (C21, D4)
    dead_letters.origin                DeadLetterOrigin       (C27)
    pending_confirmations.status       ConfirmationStatus     (C20)
    workers.runtime_type               RuntimeType            (C39, DATA_CONTRACTS §50)

Not persisted: CircuitBreakerState (in memory, C37).

Worker lifecycle states are ``contracts.worker.WorkerStatus`` (S0–S11, unchanged).
"""
from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class ConsolidationOutcome(StrEnum):
    """``execution_runs.consolidation`` (gate §10)."""
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"


class StepState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"            # no outgoing edge; never produced (C6)
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"            # never written in this phase (C24)
    PENDING_PROBE = "pending_probe"
    DEAD_LETTER = "dead_letter"


class StepTerminalReason(StrEnum):
    USER_CANCELLED = "user_cancelled"
    ADMISSION_REJECTED = "admission_rejected"
    ADMISSION_EXHAUSTED = "admission_exhausted"
    NO_WORKER = "no_worker"
    LEASE_UNAVAILABLE = "lease_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PREFLIGHT_FAILED = "preflight_failed"
    NOT_EXECUTED_NO_RETRY = "not_executed_no_retry"
    DEPENDENCY_FAILED = "dependency_failed"
    RUN_DEAD_LETTERED = "run_dead_lettered"
    AUTHORIZATION_REVOKED = "authorization_revoked"
    KILL_SWITCH_ENGAGED = "kill_switch_engaged"
    BINDING_INVALID = "binding_invalid"
    CREDENTIAL_INVALID = "credential_invalid"


class ReservationState(StrEnum):
    RESERVED = "reserved"
    LOCKED = "locked"
    COMMITTED = "committed"
    RELEASED = "released"


class ReconciliationStatus(StrEnum):
    NONE = "none"
    PENDING_PROBE = "pending_probe"
    RECONCILING = "reconciling"
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_FAILURE = "confirmed_failure"


class ReconciliationKind(StrEnum):
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"


class ReconciliationOutcome(StrEnum):
    EXECUTED_SUCCESS = "EXECUTED_SUCCESS"
    EXECUTED_FAILURE = "EXECUTED_FAILURE"
    NOT_EXECUTED = "NOT_EXECUTED"
    LEDGER_HIT = "LEDGER_HIT"
    VERIFIED_PASS = "VERIFIED_PASS"
    VERIFIED_FAIL = "VERIFIED_FAIL"
    EXHAUSTED = "EXHAUSTED"


class LeaseStatus(StrEnum):
    PENDING = "pending"            # only inside the acquisition transaction (C26)
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"


class DeadLetterStatus(StrEnum):
    PENDING = "pending"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class DeadLetterErrorType(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    DATA = "data"
    UNKNOWN_UNRESOLVED = "unknown_unresolved"


class RetryMode(StrEnum):
    PROBE = "PROBE"
    VERIFY = "VERIFY"
    NONE = "NONE"


class ResolutionOutcome(StrEnum):
    EXECUTED = "EXECUTED"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNDETERMINED = "UNDETERMINED"


class DeadLetterOrigin(StrEnum):
    EXECUTION = "execution"
    ROLLBACK = "rollback"


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RuntimeType(StrEnum):
    LLM = "llm"
    RULES = "rules"
    VISION = "vision"
    BROWSER = "browser"
    RPA = "rpa"
    DATA = "data"
    RAG = "rag"
    CODE = "code"
    HUMAN = "human"


class CircuitBreakerState(StrEnum):
    """Per-provider breaker (gate Appendix A.9, C37). In-memory in this phase (ADR-5: persistence deferred).
    S8 reads the member NAME (``CLOSED``/``OPEN``/``HALF_OPEN``) through the S0–S11 CircuitBreaker protocol."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
