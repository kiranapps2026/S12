"""
Core database models — tenants, workspaces, users, and memberships.

Source: DATABASE.md §3-6, IDENTITY_AND_TENANCY.md §3-4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Index,
    UniqueConstraint, CheckConstraint, Text, Integer, Float,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Server-authoritative UTC timestamp."""
    return datetime.now(timezone.utc)


class Tenant(Base):
    """Tenant — the top-level isolation boundary."""
    __tablename__ = "tenants"

    tenant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    settings = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    workspaces = relationship("Workspace", back_populates="tenant", cascade="all, delete-orphan")
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    memberships = relationship("Membership", back_populates="tenant", cascade="all, delete-orphan")


class Workspace(Base):
    """Workspace — logical grouping within a tenant."""
    __tablename__ = "workspaces"

    workspace_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    settings = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="workspaces")
    users = relationship("User", back_populates="workspace")
    executions = relationship("ExecutionRun", back_populates="workspace")


class User(Base):
    """User — an identity within a tenant."""
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id", ondelete="SET NULL"), nullable=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(64), nullable=False, default="member")
    is_active = Column(Boolean, default=True, nullable=False)
    preferences = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        Index("ix_users_tenant_active", "tenant_id", "is_active"),
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    workspace = relationship("Workspace", back_populates="users")
    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    """Membership — many-to-many between users and workspaces."""
    __tablename__ = "memberships"

    membership_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False)
    role = Column(String(64), nullable=False, default="member")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "workspace_id", name="uq_membership"),
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class Connection(Base):
    """Connection — external service connection (OAuth, API key, etc.)."""
    __tablename__ = "connections"

    connection_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    provider_type = Column(String(64), nullable=False)  # notion, slack, openai, anthropic, etc.
    auth_type = Column(String(64), nullable=False)      # oauth2, api_key, service_account
    credentials_ref = Column(String(255), nullable=False)  # Reference to provider_tokens
    is_active = Column(Boolean, default=True, nullable=False)
    metadata = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Indexes
    __table_args__ = (
        Index("ix_connections_tenant_active", "tenant_id", "is_active"),
    )
