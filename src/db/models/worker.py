"""
Worker models — worker identity, versions, deployments.

Source: DATABASE.md, WORKER_LIFECYCLE_VERIFICATION_ADMISSION.md
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Index,
    Integer, Float, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import enum

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerStatus(enum.Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    TERMINATED = "TERMINATED"


class WorkerVersionStatus(enum.Enum):
    REGISTERED = "REGISTERED"
    INACTIVE = "INACTIVE"
    CANARY = "CANARY"
    RAMPING = "RAMPING"
    CURRENT = "CURRENT"
    DEPRECATED = "DEPRECATED"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    RETIRED = "RETIRED"


class WorkerSubscriptionState(enum.Enum):
    IDLE = "IDLE"
    POLLING = "POLLING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ERROR = "ERROR"


class WorkerIdentity(Base):
    """Worker identity — separate from Worker Runtime and Model."""
    __tablename__ = "worker_identities"

    worker_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    endpoint_url = Column(String(512), nullable=False)
    capabilities = Column(JSONB, nullable=False, default=list)
    max_concurrent = Column(Integer, default=10, nullable=False)
    current_load = Column(Integer, default=0, nullable=False)
    locality_score = Column(Float, default=0.0, nullable=False)
    subscription_state = Column(
        Enum(WorkerSubscriptionState), default=WorkerSubscriptionState.IDLE, nullable=False
    )
    status = Column(Enum(WorkerStatus), default=WorkerStatus.REGISTERED, nullable=False)
    metadata = Column(JSONB, default=dict, nullable=False)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_worker_identities_tenant_status", "tenant_id", "status"),
        Index("ix_worker_identities_subscription", "tenant_id", "subscription_state"),
    )


class WorkerVersion(Base):
    """Worker code version with rollout lifecycle."""
    __tablename__ = "worker_versions"

    version_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("worker_identities.worker_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    runtime_image = Column(String(512), nullable=False)
    model_id = Column(String(255), nullable=False)
    canary_percentage = Column(Integer, default=0, nullable=False)
    rollout_status = Column(Enum(WorkerVersionStatus), default=WorkerVersionStatus.REGISTERED, nullable=False)
    contract_hash = Column(String(64), nullable=False)
    is_production_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_worker_versions_worker", "worker_id"),
    )


class WorkerDeployment(Base):
    """Worker deployment tracking."""
    __tablename__ = "worker_deployments"

    deployment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("worker_identities.worker_id", ondelete="CASCADE"), nullable=False)
    version_id = Column(UUID(as_uuid=True), ForeignKey("worker_versions.version_id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    deployment_status = Column(String(32), default="PENDING", nullable=False)
    target_replicas = Column(Integer, default=1, nullable=False)
    current_replicas = Column(Integer, default=0, nullable=False)
    healthy_replicas = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
