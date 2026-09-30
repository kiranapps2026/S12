"""The event scheduler: on every tick, fire each due schedule through the gateway and the ONE pipeline.

Safe to run in more than one process: the planned fire time is part of the idempotency key, so a
planned time is fired once however many schedulers race (the others see `duplicate`). A failing
schedule never stops the others."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from contracts.schedule import ScheduleStore
from engine.gateway.schedule import due
from engine.gateway.webhook import EventGateway, Received, WebhookRejected

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fired:
    schedule_id: str
    planned: datetime
    outcome: str                        # "ran" | "duplicate" | "refused" | "failed"
    reason: str | None = None


class EventScheduler:
    def __init__(self, store: ScheduleStore, gateway: EventGateway,
                 run: Callable[[Received], Awaitable[object]]) -> None:
        self._store, self._gateway, self._run = store, gateway, run

    async def tick(self, now: datetime | None = None) -> list[Fired]:
        now = now or await self._store.now()
        results: list[Fired] = []
        for schedule in await self._store.active():
            try:
                planned = due(schedule, now)
            except ValueError:
                logger.error("schedule %s is malformed; skipped", schedule.schedule_id)
                results.append(Fired(schedule.schedule_id, now, "refused", "schedule_invalid"))
                continue
            if planned is None:
                continue
            try:
                received = await self._gateway.receive_schedule(schedule, planned)
                if received.duplicate:
                    results.append(Fired(schedule.schedule_id, planned, "duplicate"))
                else:
                    await self._run(received)
                    results.append(Fired(schedule.schedule_id, planned, "ran"))
                await self._store.mark_fired(schedule.schedule_id, planned)
            except WebhookRejected as rejected:
                # a refused event (unregistered type, payload no longer valid) is not retried for this
                # planned time: it is marked handled so it does not refuse again every tick
                logger.warning("scheduled event %s refused: %s", schedule.schedule_id, rejected.reason)
                results.append(Fired(schedule.schedule_id, planned, "refused", rejected.reason))
                if rejected.status < 500:
                    await self._store.mark_fired(schedule.schedule_id, planned)
            except Exception:  # noqa: BLE001 — one schedule never stops the others; not marked, so it retries
                logger.exception("scheduled event %s failed", schedule.schedule_id)
                results.append(Fired(schedule.schedule_id, planned, "failed", "error"))
        return results


async def run_forever(scheduler: EventScheduler, interval_seconds: float) -> None:
    """Tick until cancelled."""
    while True:
        try:
            await scheduler.tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed")
        await asyncio.sleep(interval_seconds)
