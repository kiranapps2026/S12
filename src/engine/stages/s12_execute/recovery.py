"""The recovery sweeper (gate §13, §21 S4; rulings CONF-033, CONF-042, CONF-046).

On each ``sweep`` it asks the database for orphaned runs -- RUNNING or RECONCILING with no usable lease, not
owned by this Worker Runtime (a live in-process loop, CONF-033); a run never leased at all only once its
ownership is older than one lease TTL (its admitting runtime is about to lease it, CONF-046) -- through
``s12_recovery_candidates`` (ids only, CONF-042), and recovers each through ``loop.recover_execution``, whose
takeover skips an ownership row another sweeper holds (``FOR UPDATE SKIP LOCKED``), so several sweepers never
claim the same run.

One run that cannot be recovered (an error, not a crash) is logged at ERROR and left as it is; the sweep goes
on to the others, so one bad run never starves the rest. A simulated crash (a BaseException: the process
dying) is never caught. The log names the run and the error's type only: an error's text or traceback may
carry provider data.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from adapters.postgres.database import Database
from engine.stages.s12_execute.loop import LoopDeps, LoopResult, recover_execution
from engine.stages.s12_execute.settings import RECOVERY_SWEEP_INTERVAL_MAX_S

logger = logging.getLogger(__name__)

_CANDIDATES = "SELECT tenant_id, execution_id FROM s12_recovery_candidates($1, $2, $3)"
RECOVERY_FAILED = "recovery_failed"
SWEEP_FAILED = "sweep_failed"


class RecoverySweeper:
    def __init__(self, database: Database, deps: LoopDeps, *, batch: int = 10) -> None:
        if batch < 1:
            raise ValueError("a sweep takes at least one candidate")
        self._db, self._deps, self._batch = database, deps, batch

    async def candidates(self) -> list[tuple[str, str]]:
        async with self._db.transaction() as c:
            rows = await c.fetch(_CANDIDATES, self._deps.runtime_instance_id, self._batch,
                                 float(self._deps.settings.lease_ttl_s))
        return [(r["tenant_id"], r["execution_id"]) for r in rows]

    async def sweep(self) -> list[tuple[str, str, LoopResult]]:
        results = []
        for tenant_id, execution_id in await self.candidates():
            try:
                result = await recover_execution(self._deps, tenant_id, execution_id)
            except Exception as error:                        # noqa: BLE001 - isolate one run; logged, never lost
                fields = {"tenant_id": tenant_id, "execution_id": execution_id,
                          "runtime_instance_id": self._deps.runtime_instance_id,
                          "error_type": type(error).__name__}
                logger.error(json.dumps({"event": RECOVERY_FAILED, **fields}, sort_keys=True), extra=fields)
                continue
            results.append((tenant_id, execution_id, result))
        return results

    async def run(self, stop: asyncio.Event, *, interval_s: float) -> int:
        """The Worker Runtime's sweeper (§13: started with the runtime, at an interval under 30 seconds): sweep, then
        wait ``interval_s`` or until ``stop`` is set. A sweep that fails (the database briefly unreachable) is logged
        at ERROR and the next one runs: the sweeper lives as long as its runtime. Returns the number of sweeps made."""
        if not 0 < interval_s < RECOVERY_SWEEP_INTERVAL_MAX_S:
            raise ValueError("the sweep interval must be > 0 and < 30 seconds (gate §13)")
        sweeps = 0
        while not stop.is_set():
            try:
                await self.sweep()
            except Exception as error:                        # noqa: BLE001 - e.g. the database briefly unreachable
                fields = {"runtime_instance_id": self._deps.runtime_instance_id, "error_type": type(error).__name__}
                logger.error(json.dumps({"event": SWEEP_FAILED, **fields}, sort_keys=True), extra=fields)
            sweeps += 1
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), interval_s)
        return sweeps
