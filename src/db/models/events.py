"""
Budget, confirmation, dead letter, and event models.

Source: DATABASE.md, DATA_CONTRACTS.md
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Index,
    Text, Integer, Float, Enum, Numeric, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase
import enum

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --- Budget Models ---

class BudgetReservationStatus(enum.Enum):
    RESERVED = "RESERVED"
    LOCKED = "LOCKED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class BudgetReservation(Base):
    """Budget reservation — tracks budget hold/commit/release lifecycle."""
    __tablename__ = "budget_reservations"

    reservation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), nullable=True)
    amount = Column(Numeric(18, 6), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    status = Column(Enum(BudgetReservationStatus), default=BudgetReservationStatus.RESERVED, nullable=False)
    idempotency_key = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    committed_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_budget_reservations_tenant_status", "tenant_id", "status"),
        Index("ix_budget_reservations_execution", "execution_id"),
    )


class BudgetTracker(Base):
    """Budget tracker — aggregate budget state for a tenant."""
    __tablename__ = "budget_tracker"

    tracker_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    total_budget = Column(Numeric(18, 6), nullable=False, default=0)
    reserved = Column(Numeric(18, 6), nullable=False, default=0)
    committed = Column(Numeric(18, 6), nullable=False, default=0)
    available = Column(Numeric(18, 6), nullable=False, default=0)
    currency = Column(String(3), default="USD", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


# --- Confirmation Model ---

class PendingConfirmationStatus(enum.Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PendingConfirmationRow(Base):
    """Human-in-the-loop confirmation row."""
    __tablename__ = "pending_confirmations"

    confirmation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    plan_hash = Column(String(64), nullable=False)
    status = Column(Enum(PendingConfirmationStatus), default=PendingConfirmationStatus.PENDING, nullable=False)
    user_response = Column(String(32), nullable=True)  # YES, NO, MODIFY
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_pending_confirmations_execution", "execution_id"),
    )


# --- Dead Letter Model ---

class DeadLetterStatus(enum.Enum):
    PENDING_RETRY = "PENDING_RETRY"
    RETRYING = "RETRYING"
    RESOLVED = "RESOLVED"
    ABANDONED = "ABANDONED"


class DeadLetter(Base):
    """Dead letter queue for failed executions."""
    __tablename__ = "dead_letters"

    dead_letter_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), nullable=True)
    reservation_id = Column(UUID(as_uuid=True), nullable=True)
    mutation_type = Column(String(32), nullable=False)
    is_idempotent = Column(Boolean, default=False, nullable=False)
    is_resumable = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=False)
    trace = Column(JSONB, nullable=False, default=list)
    retry_count = Column(Integer, default=0, nullable=False)
    status = Column(Enum(DeadLetterStatus), default=DeadLetterStatus.PENDING_RETRY, nullable=False)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dead_letters_tenant_status", "tenant_id", "status"),
        Index("ix_dead_letters_next_retry", "next_retry_at"),
    )


# --- Retry Log ---

class RetryLog(Base):
    """Retry attempt log."""
    __tablename__ = "retry_log"

    retry_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    step_id = Column(UUID(as_uuid=True), nullable=True)
    attempt_id = Column(String(64), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    mutation_type = Column(String(32), nullable=False)
    error_type = Column(String(64), nullable=False)
    error_message = Column(Text, nullable=True)
    will_retry = Column(Boolean, default=False, nullable=False)
    backoff_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


# --- Event Models ---

class OutboxStatus(enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class Outbox(Base):
    """Outbox pattern for reliable event delivery."""
    __tablename__ = "outbox"

    outbox_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    aggregate_id = Column(String(64), nullable=False, index=True)
    aggregate_type = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    headers = Column(JSONB, nullable=False, default=dict)
    destination = Column(String(255), nullable=True)
    status = Column(Enum(OutboxStatus), default=OutboxStatus.PENDING, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_outbox_status", "status", "created_at"),
    )


class AuditLog(Base):
    """Append-only audit log."""
    __tablename__ = "audit_log"

    audit_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    actor_type = Column(String(32), nullable=False)  # user, worker, system
    actor_id = Column(String(255), nullable=False)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(255), nullable=True)
    changes = Column(JSONB, nullable=False, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_audit_log_tenant_action", "tenant_id", "action", "created_at"),
    )
