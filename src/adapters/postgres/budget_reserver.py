"""BudgetReserver (gate C3, C31): the one component that reserves, locks, commits and releases a
step's budget. Per step; every move follows STATE_TRANSITIONS §3; all in tenant-scoped transactions.

reserve: lock the tenant row (FOR UPDATE), compute availability for the current period, insert the
reservation only if available >= cost, and set execution_steps.reservation_id in the same transaction.
Reserving again for a step that already has a live reservation returns that one (idempotent)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from adapters.postgres.budget import AVAILABLE_SQL
from adapters.postgres.database import Database
from contracts.execution_states import ReservationState
from engine.stages.s12_execute import transitions


@dataclass(frozen=True)
class Reservation:
    reservation_id: str | None           # None when the budget is exhausted
    status: str | None                   # "reserved" | "locked" ... | None when exhausted


class PostgresBudgetReserver:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def reserve(self, *, tenant_id: str, user_id: str, execution_id: str, step_id: str,
                      cost: int) -> Reservation:
        async with self._db.tenant_transaction(tenant_id) as c:
            await c.fetchval("SELECT 1 FROM tenants WHERE tenant_id = $1 FOR UPDATE", tenant_id)
            live = await c.fetchrow(
                "SELECT reservation_id, status FROM budget_reservations"
                " WHERE tenant_id = $1 AND step_id = $2 AND status <> 'released'", tenant_id, step_id)
            if live is not None:
                return Reservation(live["reservation_id"], live["status"])
            available = await c.fetchval(AVAILABLE_SQL, tenant_id)
            if available is None or available < cost:
                return Reservation(None, None)
            reservation_id = str(uuid.uuid4())
            await c.execute(
                "INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status)"
                " VALUES ($1,$2,$3,$4,$5,$6,'reserved')", reservation_id, tenant_id, user_id, execution_id, step_id, cost)
            await c.execute("UPDATE execution_steps SET reservation_id = $3 WHERE tenant_id = $1 AND step_id = $2",
                            tenant_id, step_id, reservation_id)
            return Reservation(reservation_id, ReservationState.RESERVED.value)

    async def status(self, tenant_id: str, reservation_id: str) -> str | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            return await c.fetchval("SELECT status FROM budget_reservations WHERE tenant_id = $1 AND reservation_id = $2",
                                    tenant_id, reservation_id)

    async def lock(self, tenant_id: str, reservation_id: str) -> None:
        await self._move(tenant_id, reservation_id, ReservationState.LOCKED.value, "locked_at")

    async def commit(self, tenant_id: str, reservation_id: str) -> None:
        await self._move(tenant_id, reservation_id, ReservationState.COMMITTED.value, "committed_at")

    async def release(self, tenant_id: str, reservation_id: str) -> None:
        await self._move(tenant_id, reservation_id, ReservationState.RELEASED.value, "released_at")

    async def _move(self, tenant_id: str, reservation_id: str, to: str, stamp: str) -> None:
        async with self._db.tenant_transaction(tenant_id) as c:
            current = await c.fetchval(
                "SELECT status FROM budget_reservations WHERE tenant_id = $1 AND reservation_id = $2 FOR UPDATE",
                tenant_id, reservation_id)
            if current is None:
                raise transitions.StateTransitionError(f"unknown reservation {reservation_id}")
            transitions.check_budget(current, to)
            await c.execute(f"UPDATE budget_reservations SET status = $3, {stamp} = now()"
                            " WHERE tenant_id = $1 AND reservation_id = $2", tenant_id, reservation_id, to)
