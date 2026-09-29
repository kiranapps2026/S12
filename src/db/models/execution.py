"""
Execution models — execution runs, steps, and leases.

Source: DATABASE.md §7-10, STATE_TRANSITIONS.md §1-2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Index,
    UniqueConstraint, Text, Integer, Float, Enum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import enum

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionRunStatus(enum.Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class ExecutionStepStatus(enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    PENDING_PROBE = "PENDING_PROBE"
    PROBE_FAILED = "PROBE_FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"
    TIME_OUT = "TIME_OUT"


class ExecutionRun(Base):
    """Top-level execution run."""
    __tablename__ = "execution_runs"

    execution_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.connection_id"), nullable=True)
    status = Column(Enum(ExecutionRunStatus), default=ExecutionRunStatus.PENDING, nullable=False)
    outcome = Column(String(64), nullable=True)
    raw_input = Column(JSONB, nullable=False, default=dict)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    plan_hash = Column(String(64), nullable=True)
    manifest_id = Column(UUID(as_uuid=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_execution_runs_tenant_status", "tenant_id", "status"),
        Index("ix_execution_runs_trace", "trace_id"),
    )

    steps = relationship("ExecutionStep", back_populates="execution", cascade="all, delete-orphan")
    leases = relationship("ExecutionLease", back_populates="execution")


class ExecutionStep(Base):
    """Individual step within an execution."""
    __tablename__ = "execution_steps"

    step_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("execution_runs.execution_id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    status = Column(Enum(ExecutionStepStatus), default=ExecutionStepStatus.PENDING, nullable=False)
    stage = Column(String(8), nullable=False)  # S0-S15
    binding_id = Column(UUID(as_uuid=True), nullable=True)
    capability_id = Column(UUID(as_uuid=True), nullable=True)
    provider = Column(String(64), nullable=True)
    input_params = Column(JSONB, nullable=False, default=dict)
    output_data = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    attempt_id = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_execution_steps_execution", "execution_id", "step_number"),
    )

    execution = relationship("ExecutionRun", back_populates="steps")


class ExecutionLease(Base):
    """Execution lease — atomic execution ownership with fencing."""
    __tablename__ = "execution_leases"

    lease_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("execution_runs.execution_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    worker_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(32), default="PENDING", nullable=False)  # PENDING, ACQUIRED, EXPIRED, RELEASED, FENCED
    lease_token = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    acquired_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_execution_leases_worker", "worker_id"),
        Index("ix_execution_leases_token", "lease_token"),
    )

    execution = relationship("ExecutionRun", back_populates="leases")
