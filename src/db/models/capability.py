"""
Capability and binding models.

Source: DATABASE.md, DATA_CONTRACTS.md
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Index,
    Text, Integer, Float, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase
import enum

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CapabilityLifecycle(enum.Enum):
    DESIGNED = "DESIGNED"
    BUILT = "BUILT"
    CONTRACT_VALIDATED = "CONTRACT_VALIDATED"
    TESTED = "TESTED"
    FAILURE_TESTED = "FAILURE_TESTED"
    CERTIFIED = "CERTIFIED"
    PRODUCTION_ENABLED = "PRODUCTION_ENABLED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class Capability(Base):
    """Registered capability."""
    __tablename__ = "capability_registry"

    capability_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    namespace = Column(String(255), nullable=False)
    input_schema = Column(JSONB, nullable=False, default=dict)
    output_schema = Column(JSONB, nullable=False, default=dict)
    parameters = Column(JSONB, nullable=False, default=dict)
    risk_floor = Column(Float, default=0.0, nullable=False)
    mutation_type = Column(String(32), default="R", nullable=False)
    requires_auth = Column(Boolean, default=False, nullable=False)
    required_provider_types = Column(JSONB, nullable=False, default=list)
    estimated_cost_units = Column(Integer, default=1, nullable=False)
    estimated_duration_seconds = Column(Integer, default=30, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    version = Column(String(32), default="1.0.0", nullable=False)
    certification_status = Column(
        Enum(CapabilityLifecycle), default=CapabilityLifecycle.DESIGNED, nullable=False
    )
    tags = Column(JSONB, nullable=False, default=list)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "namespace", name="uq_capability"),
        Index("ix_capabilities_tenant_active", "tenant_id", "is_active"),
    )


class BindingStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    SUSPENDED = "SUSPENDED"


class BindingRow(Base):
    """Binding between capability and provider adapter."""
    __tablename__ = "binding_registry"

    binding_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    capability_id = Column(UUID(as_uuid=True), ForeignKey("capability_registry.capability_id"), nullable=False)
    provider = Column(String(64), nullable=False, index=True)
    adapter_class = Column(String(255), nullable=False)
    capability_version = Column(String(32), nullable=False)
    binding_version = Column(String(32), nullable=False)
    policy_version = Column(String(32), nullable=False)
    risk_policy_version = Column(String(32), nullable=False)
    authorization_version = Column(String(32), nullable=False)
    effective_risk = Column(Float, nullable=False)
    selection_rank = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(Enum(BindingStatus), default=BindingStatus.ACTIVE, nullable=False)
    metadata = Column(JSONB, nullable=False, default=dict)
    provider_health_score = Column(Float, default=1.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "capability_id", "provider", "adapter_class", name="uq_binding"),
        Index("ix_bindings_capability_active", "capability_id", "is_active"),
    )


class ProviderToken(Base):
    """Provider authentication tokens."""
    __tablename__ = "provider_tokens"

    token_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.connection_id", ondelete="CASCADE"), nullable=False)
    provider_type = Column(String(64), nullable=False, index=True)
    auth_type = Column(String(64), nullable=False)
    encrypted_token = Column(Text, nullable=False)
    token_metadata = Column(JSONB, nullable=False, default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_provider_tokens_connection", "connection_id"),
    )
