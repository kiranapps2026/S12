"""BudgetReserver (gate C3, C14, C31, C33; Appendix A.3; invariants I1, I2, I12): the only writer of budget state.

Budget is reserved per step. Every operation is one ``fenced_write`` for the holder's execution and one legal
Appendix A.3 transition with its reason, validated and logged in the same transaction; an illegal move raises
``IllegalStateTransition`` and a stale holder ``FencedOut``, and neither writes anything.

``reserve`` locks the tenant row (FOR UPDATE), so concurrent reservations of the tenant are serialised; checks for the
step's live reservation (idempotent); computes availability for the current period with S8's shared arithmetic
(``budget.AVAILABLE_SQL``: pool minus reserved + locked + committed created since the period start in database UTC,
C33); and inserts ``reserved`` only if ``available >= cost``, setting ``execution_steps.reservation_id`` in the same
transaction (the circular step <-> reservation link, C33). Exhausted: nothing is written.

``lock`` / ``commit`` / ``release`` with ``connection`` join the caller's transaction (Appendix A.2: the step's
``pending -> running`` and its reservation's ``reserved -> locked`` are one transaction, I-3); the fence is checked
again on that connection. Step guards of A.3 (``step_completed`` only for a completed step, the dead-letter reasons
only for a dead-lettered one) belong to the caller, which holds the step's state. Nothing here releases a LOCKED
reservation on a timer (C14): only the outcome that settles the step does.

Lock order: ownership row (FOR SHARE, the fence) -> tenant row -> step row -> reservation row.
"""
from __future__ import annotations

import types
import uuid
from dataclasses import dataclass

import asyncpg

from adapters.postgres.budget import AVAILABLE_SQL
from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder, check_fence, fenced_write
from adapters.postgres.transition_log import log_transition
from contracts.execution_states import ReservationState, StepTerminalReason
from engine.stages.s12_execute import transitions

MACHINE = "reservation"
RESERVED_REASON = ReservationState.RESERVED.value   # Appendix A.3 creation reason, spelled like the state (C28)
LIVE = (ReservationState.RESERVED, ReservationState.LOCKED, ReservationState.COMMITTED)

_LOCK_TENANT = "SELECT 1 FROM tenants WHERE tenant_id = $1 FOR UPDATE"
_LOCK_STEP = "SELECT 1 FROM execution_steps WHERE tenant_id = $1 AND step_id = $2 AND execution_id = $3 FOR UPDATE"
_LIVE = ("SELECT reservation_id, status FROM budget_reservations WHERE tenant_id = $1 AND step_id = $2"
         " AND status = ANY($3::text[])")
_INSERT = ("INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status)"
           " VALUES ($1, $2, $3, $4, $5, $6, $7)")
_LINK = "UPDATE execution_steps SET reservation_id = $3 WHERE tenant_id = $1 AND step_id = $2"
_LOCK_RESERVATION = ("SELECT status, execution_id FROM budget_reservations WHERE tenant_id = $1 AND reservation_id = $2"
                     " FOR UPDATE")
_STATUS = "SELECT status FROM budget_reservations WHERE tenant_id = $1 AND reservation_id = $2"
# The time column each target state stamps (constants only; never built from input).
_MOVE = types.MappingProxyType({
    ReservationState.LOCKED: ("UPDATE budget_reservations SET status = $3, locked_at = now()"
                              " WHERE tenant_id = $1 AND reservation_id = $2"),
    ReservationState.COMMITTED: ("UPDATE budget_reservations SET status = $3, committed_at = now()"
                                 " WHERE tenant_id = $1 AND reservation_id = $2"),
    ReservationState.RELEASED: ("UPDATE budget_reservations SET status = $3, released_at = now()"
                                " WHERE tenant_id = $1 AND reservation_id = $2"),
})


@dataclass(frozen=True)
class Reservation:
    reservation_id: str | None           # None when the budget is exhausted
    status: str | None                   # a ReservationState value; None when exhausted
    reason: str | None = None            # budget_exhausted when exhausted


class PostgresBudgetReserver:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def reserve(self, holder: FenceHolder, *, user_id: str, step_id: str, cost: int) -> Reservation:
        if type(cost) is not int or cost < 0:
            raise ValueError(f"reservation cost must be a non-negative integer, got {cost!r}")
        t = holder.tenant_id

        async def write(c: asyncpg.Connection) -> Reservation:
            if await c.fetchval(_LOCK_TENANT, t) is None:
                raise LookupError(f"tenant {t} not found")
            if await c.fetchval(_LOCK_STEP, t, step_id, holder.execution_id) is None:
                raise LookupError(f"step {step_id} is not a step of execution {holder.execution_id}")
            live = await c.fetchrow(_LIVE, t, step_id, list(LIVE))
            if live is not None:
                return Reservation(live["reservation_id"], live["status"])
            available = await c.fetchval(AVAILABLE_SQL, t)
            if available < cost:
                return Reservation(None, None, StepTerminalReason.BUDGET_EXHAUSTED)
            transitions.validate(MACHINE, None, ReservationState.RESERVED, reason=RESERVED_REASON)
            reservation_id = str(uuid.uuid4())
            await c.execute(_INSERT, reservation_id, t, user_id, holder.execution_id, step_id, cost,
                            ReservationState.RESERVED)
            await c.execute(_LINK, t, step_id, reservation_id)
            await _log(c, holder, reservation_id, None, ReservationState.RESERVED, RESERVED_REASON)
            return Reservation(reservation_id, ReservationState.RESERVED)

        return await fenced_write(self._db, holder, write)

    async def lock(self, holder: FenceHolder, reservation_id: str, *, reason: str,
                   connection: asyncpg.Connection | None = None) -> None:
        await self._move(holder, reservation_id, ReservationState.LOCKED, reason, connection)

    async def commit(self, holder: FenceHolder, reservation_id: str, *, reason: str,
                     connection: asyncpg.Connection | None = None) -> None:
        await self._move(holder, reservation_id, ReservationState.COMMITTED, reason, connection)

    async def release(self, holder: FenceHolder, reservation_id: str, *, reason: str,
                      connection: asyncpg.Connection | None = None) -> None:
        await self._move(holder, reservation_id, ReservationState.RELEASED, reason, connection)

    async def status(self, tenant_id: str, reservation_id: str) -> str | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            return await c.fetchval(_STATUS, tenant_id, reservation_id)

    async def _move(self, holder: FenceHolder, reservation_id: str, to: ReservationState, reason: str,
                    connection: asyncpg.Connection | None) -> None:
        async def write(c: asyncpg.Connection) -> None:
            row = await c.fetchrow(_LOCK_RESERVATION, holder.tenant_id, reservation_id)
            if row is None or row["execution_id"] != holder.execution_id:
                raise LookupError(f"reservation {reservation_id} is not a reservation of execution"
                                  f" {holder.execution_id}")
            transitions.validate(MACHINE, row["status"], to, reason=reason)
            await c.execute(_MOVE[to], holder.tenant_id, reservation_id, to)
            await _log(c, holder, reservation_id, row["status"], to, reason)

        if connection is None:
            await fenced_write(self._db, holder, write)
            return
        await check_fence(connection, holder)
        await write(connection)


async def _log(c: asyncpg.Connection, holder: FenceHolder, reservation_id: str, from_state: str | None,
               to_state: str, reason: str) -> None:
    await log_transition(c, tenant_id=holder.tenant_id, machine=MACHINE, entity_id=reservation_id,
                         from_state=from_state, to_state=to_state, reason=reason,
                         runtime_instance_id=holder.runtime_instance_id, fence_token=holder.fence_token,
                         execution_id=holder.execution_id)
