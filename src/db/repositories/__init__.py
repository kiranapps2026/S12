"""
Database repositories — data access layer.

Source: DATABASE.md, IDENTITY_AND_TENANCY.md

All queries MUST include tenant_id for RLS enforcement.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import Select

logger = logging.getLogger(__name__)


@dataclass
class TenantFilter:
    """Tenant filter context — injected into every query."""
    tenant_id: UUID
    workspace_id: UUID | None = None
    user_id: UUID | None = None


class BaseRepository(ABC):
    """
    Base repository with tenant isolation.

    CRITICAL: All queries MUST filter by tenant_id.
    RLS provides defense-in-depth, but application-level filtering
    prevents accidental cross-tenant data exposure.
    """

    def __init__(self, db: "AsyncSession") -> None:
        self.db = db

    @abstractmethod
    def get_model_class(self) -> Any:
        """Return the SQLAlchemy model class for this repository."""
        ...

    def _tenant_filter(self, stmt: "Select", tenant: TenantFilter) -> "Select":
        """Apply tenant filter to a query."""
        model = self.get_model_class()
        return stmt.where(model.tenant_id == tenant.tenant_id)


class ExecutionRunRepository(BaseRepository):
    """Repository for execution_runs table."""

    def get_model_class(self) -> Any:
        from db.models.execution import ExecutionRun
        return ExecutionRun

    async def get_by_id(self, execution_id: UUID, tenant: TenantFilter) -> dict | None:
        """Get an execution run by ID with tenant check."""
        from sqlalchemy import select
        from db.models.execution import ExecutionRun

        stmt = select(ExecutionRun).where(
            ExecutionRun.execution_id == execution_id,
            ExecutionRun.tenant_id == tenant.tenant_id,
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.to_dict() if row else None

    async def list_for_tenant(
        self, tenant: TenantFilter, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """List executions for a tenant."""
        from sqlalchemy import select
        from db.models.execution import ExecutionRun

        stmt = (
            select(ExecutionRun)
            .where(ExecutionRun.tenant_id == tenant.tenant_id)
            .order_by(ExecutionRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def create(self, data: dict, tenant: TenantFilter) -> dict:
        """Create a new execution run."""
        from db.models.execution import ExecutionRun

        # Ensure tenant_id is set from context, never from input
        data["tenant_id"] = tenant.tenant_id
        run = ExecutionRun(**data)
        self.db.add(run)
        await self.db.flush()
        return run.to_dict()

    async def update_status(
        self, execution_id: UUID, status: str, tenant: TenantFilter
    ) -> dict | None:
        """Update execution status."""
        from sqlalchemy import select
        from db.models.execution import ExecutionRun

        stmt = (
            select(ExecutionRun)
            .where(
                ExecutionRun.execution_id == execution_id,
                ExecutionRun.tenant_id == tenant.tenant_id,
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            return None

        # Validate state transition
        from contracts.state_validators import STATE_VALIDATOR
        if not STATE_VALIDATOR.validate_transition("execution_run", run.status, status):
            raise ValueError(
                f"Illegal transition: {run.status} → {status}"
            )

        run.status = status
        run.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return run.to_dict()


class WorkerRepository(BaseRepository):
    """Repository for worker identity and state."""

    def get_model_class(self) -> Any:
        from db.models.worker import WorkerIdentity
        return WorkerIdentity

    async def get_available_workers(
        self, tenant: TenantFilter, capability: str | None = None
    ) -> list[dict]:
        """Get available workers for a tenant."""
        from sqlalchemy import select
        from db.models.worker import WorkerIdentity

        stmt = (
            select(WorkerIdentity)
            .where(
                WorkerIdentity.tenant_id == tenant.tenant_id,
                WorkerIdentity.status == "ACTIVE",
                WorkerIdentity.current_load < WorkerIdentity.max_concurrent,
            )
        )

        if capability:
            # Filter workers that support the capability
            stmt = stmt.where(WorkerIdentity.capabilities.contains([capability]))

        stmt = stmt.order_by(WorkerIdentity.locality_score.desc())
        result = await self.db.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]


class CapabilityRepository(BaseRepository):
    """Repository for capabilities and bindings."""

    def get_model_class(self) -> Any:
        from db.models.capability import Capability
        return Capability

    async def discover(
        self, intent: dict, tenant: TenantFilter
    ) -> list[dict]:
        """Discover capabilities matching an intent."""
        # TODO: Implement capability discovery with vector similarity
        pass

    async def get_binding(
        self, binding_id: str, tenant: TenantFilter
    ) -> dict | None:
        """Get a specific binding."""
        from sqlalchemy import select
        from db.models.capability import BindingRow

        stmt = select(BindingRow).where(
            BindingRow.binding_id == binding_id,
            BindingRow.tenant_id == tenant.tenant_id,
            BindingRow.is_active == True,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.to_dict() if row else None


class BudgetRepository(BaseRepository):
    """Repository for budget reservations and tracking."""

    def get_model_class(self) -> Any:
        from db.models.budget import BudgetReservation
        return BudgetReservation

    async def reserve(
        self, tenant: TenantFilter, amount: float, execution_id: str
    ) -> dict:
        """Reserve budget (idempotent)."""
        from db.models.budget import BudgetReservation
        from contracts.billing import BillingUsageRecord

        reservation = BudgetReservation(
            tenant_id=tenant.tenant_id,
            execution_id=execution_id,
            amount=amount,
            status="RESERVED",
        )
        self.db.add(reservation)
        await self.db.flush()
        return reservation.to_dict()

    async def commit(self, reservation_id: str, tenant: TenantFilter) -> dict | None:
        """Commit a budget reservation."""
        # TODO: Atomic commit operation
        pass

    async def release(self, reservation_id: str, tenant: TenantFilter) -> dict | None:
        """Release a budget reservation."""
        # TODO: Atomic release operation
        pass
