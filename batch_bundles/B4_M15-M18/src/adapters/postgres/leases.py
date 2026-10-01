"""Worker leases and execution ownership (gate C5, C25, C26; WORKER_LIFECYCLE §14; invariants I5, I7, I8).

A lease gives one Worker Runtime the right to work on one execution. Its fence token comes from the one
``fence_token_seq`` and is written to ``execution_ownership``; ``fenced_write`` accepts only the current token, so the
fence is per execution, never per worker (C25). A lease is usable while ``status = active AND expires_at > now()``;
a lapsed lease is moved to ``expired`` by the next acquisition on its worker, and is never renewed (C26).
``workers.current_load`` always equals the worker's ``active`` leases and never exceeds ``capacity`` (C5).

Locks, always in this order: worker row -> lease rows -> ownership row. Nothing holds the ownership row while waiting
for a worker row, so no two operations here, nor ``fenced_write`` (ownership row only), can deadlock. Every token is
taken after the worker and ownership locks and logged in the same transaction, so the log's order is the issue order
per worker and per execution (I8). The usable-lease check runs as its own statement after the ownership lock: under
READ COMMITTED it sees a concurrent acquirer's committed lease, so an execution has one owner at a time. A terminal
run is never leased; the step that makes a run terminal must hold its ownership row lock too (I7), then release its
lease with ``run_terminal``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

import asyncpg

from adapters.postgres.database import Database
from adapters.postgres.fencing import FenceHolder
from adapters.postgres.transition_log import log_transition
from contracts.execution_states import ExecutionStatus, LeaseStatus
from contracts.step_execution import FencedOut
from contracts.worker import WorkerStatus
from engine.stages.s12_execute import transitions

MACHINE = "lease"
ACQUIRED = "acquired"               # Appendix A.4: creation reason
RENEWED = "renewed"                 # active -> active, new token
TTL_ELAPSED = "ttl_elapsed"         # active -> expired
TERMINAL_RUN = frozenset(s.value for s in ExecutionStatus) - frozenset(transitions.RUN)

_LOCK_WORKER = ("SELECT state, capacity FROM workers WHERE tenant_id = $1 AND worker_id = $2 FOR UPDATE")
_EXPIRE_STALE = ("UPDATE worker_leases SET status = $3 WHERE tenant_id = $1 AND worker_id = $2 AND status = $4"
                 " AND expires_at <= now() RETURNING lease_id, execution_id")
_COUNT_ACTIVE = "SELECT count(*) FROM worker_leases WHERE tenant_id = $1 AND worker_id = $2 AND status = $3"
_LOCK_OWNERSHIP = ("SELECT lease_id, runtime_instance_id, fencing_token FROM execution_ownership"
                   " WHERE tenant_id = $1 AND execution_id = $2 FOR UPDATE")
_TRY_LOCK_OWNERSHIP = _LOCK_OWNERSHIP + " SKIP LOCKED"
_OWNERSHIP_EXISTS = "SELECT 1 FROM execution_ownership WHERE tenant_id = $1 AND execution_id = $2"
_EXPIRE_LAPSED_FOR_EXECUTION = ("UPDATE worker_leases SET status = $3 WHERE tenant_id = $1 AND execution_id = $2"
                                " AND status = $4 AND expires_at <= now() RETURNING lease_id, worker_id")
_RUN_STATUS = "SELECT status FROM execution_runs WHERE tenant_id = $1 AND execution_id = $2"
_USABLE_FOR_EXECUTION = ("SELECT 1 FROM worker_leases WHERE tenant_id = $1 AND execution_id = $2 AND status = $3"
                         " AND expires_at > now() LIMIT 1")
_NEXT_TOKEN = "SELECT nextval('fence_token_seq')"
_INSERT_LEASE = ("INSERT INTO worker_leases (lease_id, tenant_id, worker_id, execution_id, fence_token, status,"
                 " expires_at) VALUES ($1, $2, $3, $4, $5, $6, now() + make_interval(secs => $7))")
_SET_LOAD = ("UPDATE workers SET current_load = (SELECT count(*) FROM worker_leases l WHERE l.tenant_id = $1"
             " AND l.worker_id = $2 AND l.status = $3), updated_at = now() WHERE tenant_id = $1 AND worker_id = $2")
_SET_EPOCH = "UPDATE workers SET lease_epoch = $3 WHERE tenant_id = $1 AND worker_id = $2"
_TAKE_OWNERSHIP = ("UPDATE execution_ownership SET worker_id = $3, lease_id = $4, runtime_instance_id = $5,"
                   " fencing_token = $6, updated_at = now() WHERE tenant_id = $1 AND execution_id = $2"
                   " AND fencing_token = $7")
_LOCK_USABLE_LEASE = ("SELECT 1 FROM worker_leases WHERE tenant_id = $1 AND lease_id = $2 AND worker_id = $3"
                      " AND execution_id = $4 AND status = $5 AND expires_at > now() FOR UPDATE")
_RENEW_LEASE = ("UPDATE worker_leases SET fence_token = $3, expires_at = now() + make_interval(secs => $4)"
                " WHERE tenant_id = $1 AND lease_id = $2")
_RELEASE_LEASE = ("UPDATE worker_leases SET status = $4, released_at = now()"
                  " WHERE tenant_id = $1 AND lease_id = $2 AND worker_id = $3 AND status = $5 RETURNING lease_id")


@dataclass(frozen=True)
class Lease:
    """One Worker Runtime's right to work on one execution; ``fence_token`` goes into its ``FenceHolder``."""
    lease_id: str
    tenant_id: str
    worker_id: str
    execution_id: str
    fence_token: int


class LeaseLost(Exception):  # noqa: N818 (name fixed by golden M07, like FencedOut)
    """The lease is no longer usable (lapsed, released or superseded): stop all work on the execution."""


def _ttl(ttl_s: float) -> float:
    if not ttl_s > 0:
        raise ValueError(f"lease ttl must be positive, got {ttl_s!r}")
    return float(ttl_s)


class PostgresLeaseManager:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def acquire(self, *, tenant_id: str, worker_id: str, execution_id: str, runtime_instance_id: str,
                      ttl_s: float, holder: FenceHolder | None = None, skip_locked: bool = False) -> Lease | None:
        """Lease ``execution_id`` on ``worker_id`` in one transaction, or ``None`` (no lease written) when the worker
        is unknown, not ACTIVE or at capacity, the run is terminal, or the execution still has a usable lease.

        With ``holder`` (the in-line loop's next step) the lease continues that holder's ownership: when the
        ownership row, checked under its lock, no longer names the holder, ``FencedOut`` and nothing is written. An
        execution is taken over only without a holder (recovery, M19). With ``skip_locked`` (a recovery sweeper, §21
        S4) an ownership row another transaction holds is skipped: ``None``, nothing written."""
        ttl = _ttl(ttl_s)
        async with self._db.tenant_transaction(tenant_id) as c:
            worker = await c.fetchrow(_LOCK_WORKER, tenant_id, worker_id)
            if worker is None:
                return None
            await _expire_stale(c, tenant_id, worker_id)
            active = await c.fetchval(_COUNT_ACTIVE, tenant_id, worker_id, LeaseStatus.ACTIVE)
            if worker["state"] != WorkerStatus.ACTIVE or active >= worker["capacity"]:
                return None
            owner = await c.fetchrow(_TRY_LOCK_OWNERSHIP if skip_locked else _LOCK_OWNERSHIP, tenant_id, execution_id)
            if owner is None and skip_locked and await c.fetchval(_OWNERSHIP_EXISTS, tenant_id, execution_id):
                return None                                     # another sweeper holds it
            if owner is None:
                raise LookupError(f"execution {execution_id} has no ownership record (not admitted)")
            if holder is not None and (owner["runtime_instance_id"], owner["fencing_token"]) \
                    != (holder.runtime_instance_id, holder.fence_token):
                raise FencedOut(execution_id)
            if await c.fetchval(_RUN_STATUS, tenant_id, execution_id) in TERMINAL_RUN:
                return None
            if await c.fetchval(_USABLE_FOR_EXECUTION, tenant_id, execution_id, LeaseStatus.ACTIVE):
                return None

            transitions.validate(MACHINE, None, LeaseStatus.ACTIVE, reason=ACQUIRED)
            token = await c.fetchval(_NEXT_TOKEN)
            lease = Lease(str(uuid.uuid4()), tenant_id, worker_id, execution_id, token)
            await c.execute(_INSERT_LEASE, lease.lease_id, tenant_id, worker_id, execution_id, token,
                            LeaseStatus.ACTIVE, ttl)
            await log_transition(c, tenant_id=tenant_id, machine=MACHINE, entity_id=lease.lease_id, from_state=None,
                                 to_state=LeaseStatus.ACTIVE, reason=ACQUIRED,
                                 runtime_instance_id=runtime_instance_id, fence_token=token,
                                 execution_id=execution_id)
            await _sync_load(c, tenant_id, worker_id)
            await c.execute(_SET_EPOCH, tenant_id, worker_id, token)
            await _move_ownership(c, lease, runtime_instance_id, previous_token=owner["fencing_token"])
            return lease

    async def expire_lapsed(self, tenant_id: str, execution_id: str) -> int:
        """C26: the execution's lapsed ``active`` leases become ``expired`` (the sweeper observes them first), each
        worker's load follows; returns how many. Lock order worker -> lease, as everywhere."""
        async with self._db.tenant_transaction(tenant_id) as c:
            workers = [r["worker_id"] for r in await c.fetch(
                "SELECT DISTINCT worker_id FROM worker_leases WHERE tenant_id = $1 AND execution_id = $2"
                " AND status = $3 AND expires_at <= now() ORDER BY worker_id", tenant_id, execution_id,
                LeaseStatus.ACTIVE)]
            for worker_id in workers:
                await c.fetchrow(_LOCK_WORKER, tenant_id, worker_id)
            transitions.validate(MACHINE, LeaseStatus.ACTIVE, LeaseStatus.EXPIRED, reason=TTL_ELAPSED)
            expired = await c.fetch(_EXPIRE_LAPSED_FOR_EXECUTION, tenant_id, execution_id, LeaseStatus.EXPIRED,
                                    LeaseStatus.ACTIVE)
            for row in expired:
                await log_transition(c, tenant_id=tenant_id, machine=MACHINE, entity_id=row["lease_id"],
                                     from_state=LeaseStatus.ACTIVE, to_state=LeaseStatus.EXPIRED, reason=TTL_ELAPSED,
                                     runtime_instance_id=None, fence_token=None, execution_id=execution_id)
            for worker_id in {row["worker_id"] for row in expired}:
                await _sync_load(c, tenant_id, worker_id)
            return len(expired)

    async def renew(self, lease: Lease, *, runtime_instance_id: str, ttl_s: float) -> Lease:
        """A new, larger token and a fresh TTL for a lease that is still usable and still owns its execution;
        otherwise ``LeaseLost`` and nothing is written."""
        ttl = _ttl(ttl_s)
        t = lease.tenant_id
        async with self._db.tenant_transaction(t) as c:
            if await c.fetchrow(_LOCK_WORKER, t, lease.worker_id) is None:
                raise LeaseLost(lease.lease_id)
            if not await c.fetchval(_LOCK_USABLE_LEASE, t, lease.lease_id, lease.worker_id, lease.execution_id,
                                    LeaseStatus.ACTIVE):
                raise LeaseLost(lease.lease_id)
            owner = await c.fetchrow(_LOCK_OWNERSHIP, t, lease.execution_id)
            if owner is None or (owner["lease_id"], owner["runtime_instance_id"], owner["fencing_token"]) \
                    != (lease.lease_id, runtime_instance_id, lease.fence_token):
                raise LeaseLost(lease.lease_id)

            transitions.validate(MACHINE, LeaseStatus.ACTIVE, LeaseStatus.ACTIVE, reason=RENEWED)
            renewed = replace(lease, fence_token=await c.fetchval(_NEXT_TOKEN))
            await c.execute(_RENEW_LEASE, t, lease.lease_id, renewed.fence_token, ttl)
            await log_transition(c, tenant_id=t, machine=MACHINE, entity_id=lease.lease_id,
                                 from_state=LeaseStatus.ACTIVE, to_state=LeaseStatus.ACTIVE, reason=RENEWED,
                                 runtime_instance_id=runtime_instance_id, fence_token=renewed.fence_token,
                                 execution_id=lease.execution_id)
            await c.execute(_SET_EPOCH, t, lease.worker_id, renewed.fence_token)
            await _move_ownership(c, renewed, runtime_instance_id, previous_token=lease.fence_token)
            return renewed

    async def release(self, lease: Lease, *, reason: str) -> bool:
        """``active -> released`` with ``reason`` (``work_complete``, ``fenced_out``, ``run_terminal``) and the
        worker's load updated, in one transaction. ``False`` when the lease had already left ``active`` (released
        before, or expired by an acquisition): nothing to release. Ownership is left as it is; only a newer token
        moves it."""
        transitions.validate(MACHINE, LeaseStatus.ACTIVE, LeaseStatus.RELEASED, reason=reason)
        t = lease.tenant_id
        async with self._db.tenant_transaction(t) as c:
            await c.fetchrow(_LOCK_WORKER, t, lease.worker_id)
            if await c.fetchval(_RELEASE_LEASE, t, lease.lease_id, lease.worker_id, LeaseStatus.RELEASED,
                                LeaseStatus.ACTIVE) is None:
                return False
            await log_transition(c, tenant_id=t, machine=MACHINE, entity_id=lease.lease_id,
                                 from_state=LeaseStatus.ACTIVE, to_state=LeaseStatus.RELEASED, reason=reason,
                                 runtime_instance_id=None, fence_token=None, execution_id=lease.execution_id)
            await _sync_load(c, t, lease.worker_id)
            return True


async def _expire_stale(c: asyncpg.Connection, tenant_id: str, worker_id: str) -> None:
    """C26: the worker's lapsed ``active`` leases become ``expired`` and its load follows at once, whether or not the
    acquisition then grants a lease (caller holds the worker lock)."""
    transitions.validate(MACHINE, LeaseStatus.ACTIVE, LeaseStatus.EXPIRED, reason=TTL_ELAPSED)
    expired = await c.fetch(_EXPIRE_STALE, tenant_id, worker_id, LeaseStatus.EXPIRED, LeaseStatus.ACTIVE)
    for row in expired:
        await log_transition(c, tenant_id=tenant_id, machine=MACHINE, entity_id=row["lease_id"],
                             from_state=LeaseStatus.ACTIVE, to_state=LeaseStatus.EXPIRED, reason=TTL_ELAPSED,
                             runtime_instance_id=None, fence_token=None, execution_id=row["execution_id"])
    if expired:
        await _sync_load(c, tenant_id, worker_id)


async def _sync_load(c: asyncpg.Connection, tenant_id: str, worker_id: str) -> None:
    """``current_load`` := the worker's ``active`` leases (caller holds the worker lock); CHECK keeps it <= capacity."""
    await c.execute(_SET_LOAD, tenant_id, worker_id, LeaseStatus.ACTIVE)


async def _move_ownership(c: asyncpg.Connection, lease: Lease, runtime_instance_id: str, *,
                          previous_token: int) -> None:
    """Compare-and-set (WORKER_LIFECYCLE §14): the ownership row still holds ``previous_token`` (caller holds its
    lock) and the new token is strictly greater, the sequence only grows."""
    if lease.fence_token <= previous_token:
        raise RuntimeError(f"fence token {lease.fence_token} not above {previous_token} (C25)")
    moved = await c.execute(_TAKE_OWNERSHIP, lease.tenant_id, lease.execution_id, lease.worker_id, lease.lease_id,
                            runtime_instance_id, lease.fence_token, previous_token)
    if moved != "UPDATE 1":
        raise RuntimeError(f"ownership of {lease.execution_id} changed under its lock")
