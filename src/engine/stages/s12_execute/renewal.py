"""Lease renewal during a long provider call (CONF-045, D-5).

A ``RenewingGuard`` wraps ``guard.call``: the provider call and the renewal tick run as two asyncio tasks,
dispatched through ``dispatch.run_alongside``.  Every new token is written into ``state.holder.fence_token``
in place, so every captured reference (recorder, run_attempts, idempotency ledger) posts with the current
token.

On ``LeaseLost`` the renewal task cancels the call, awaits it suppressing ``CancelledError``, and
raises ``LeaseLost``.  The loop catches it next to ``FencedOut`` and writes nothing more.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from adapters.postgres.leases import Lease, LeaseLost
from contracts.adapter_interface import GuardedCall
from contracts.step_execution import AdapterResult
from engine.stages.s12_execute.dispatch import run_alongside

logger = logging.getLogger(__name__)

_RENEW_LATE_MS_RATIO = 0.5


class RenewingGuard:
    """Wraps a guard; while ``call`` runs, a background task renews the lease every ``interval_s``."""

    def __init__(self, wrapped, state, interval_s: float, ttl_s: float) -> None:
        self._wrapped = wrapped
        self._state = state
        self._interval = interval_s
        self._ttl = ttl_s
        self._renewals = 0
        self._last_renew_ms = 0.0
        self._lost = False

    async def call(self, guarded: GuardedCall) -> AdapterResult:
        lease = self._state.lease
        if lease is None:
            return await self._wrapped.call(guarded)

        self._state.log("lease_renewal_started", lease_id=lease.lease_id,
                        interval_s=self._interval, ttl_s=self._ttl, token=lease.fence_token)

        try:
            return await run_alongside(
                self._wrapped.call(guarded),
                lambda main_task: self._renew_loop(lease, main_task),
                timeout_s=guarded.timeout_s,
            )
        except asyncio.CancelledError:
            if self._lost:
                self._state.log("lease_lost_stop", step_id=guarded.step_id,
                                renewals=self._renewals, final_token=self._state.holder.fence_token)
                raise LeaseLost(guarded.step_id)
            raise

    async def _renew_loop(self, lease: Lease, call_task: asyncio.Task) -> None:
        half_ttl_ms = self._ttl * 1000 * _RENEW_LATE_MS_RATIO
        while not self._lost and not call_task.done():
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(self._interval)
            if self._lost or call_task.done():
                break
            elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
            try:
                new = await self._state.deps.leases.renew(
                    lease, runtime_instance_id=self._state.deps.runtime_instance_id, ttl_s=self._ttl)
            except LeaseLost:
                self._lost = True
                logger.warning(json.dumps({
                    "event": "lease_renewal_refused", "lease_id": lease.lease_id,
                    "token": lease.fence_token, "error": "LeaseLost",
                }, sort_keys=True))
                call_task.cancel()
                return
            old = lease.fence_token
            self._state.holder.fence_token = new.fence_token
            self._state.lease = new
            lease = new
            self._renewals += 1
            self._last_renew_ms = elapsed_ms
            self._state.log("lease_renewed", lease_id=lease.lease_id,
                            old_token=old, new_token=new.fence_token,
                            renew_ms=round(elapsed_ms, 1), since_last_ms=round(elapsed_ms, 1))
            if elapsed_ms > half_ttl_ms:
                logger.warning(json.dumps({
                    "event": "lease_renewal_late", "lease_id": lease.lease_id,
                    "old_token": old, "new_token": new.fence_token,
                    "renew_ms": round(elapsed_ms, 1), "since_last_ms": round(elapsed_ms, 1),
                }, sort_keys=True))
