"""Schedules (a system table, read across tenants by the scheduler) and the database clock."""
from __future__ import annotations

import json
from datetime import datetime

from adapters.postgres.database import Database
from contracts.principal import Principal
from contracts.schedule import Schedule
from engine.gateway.schedule import check_schedule, latest_planned


class PostgresScheduleStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def now(self) -> datetime:
        async with self._db.transaction() as c:
            return await c.fetchval("SELECT now()")

    async def active(self) -> list[Schedule]:
        async with self._db.transaction() as c:
            rows = await c.fetch("SELECT * FROM event_schedules WHERE is_active ORDER BY schedule_id")
        return [Schedule(
            schedule_id=r["schedule_id"],
            principal=Principal(r["tenant_id"], r["workspace_id"], r["user_id"], r["membership_id"],
                                r["connection_id"], r["resource_scope"]),
            event_type=r["event_type"], payload=json.loads(r["payload"]), kind=r["kind"], anchor=r["anchor"],
            interval_seconds=r["interval_seconds"], at_seconds=r["at_seconds"], weekday=r["weekday"],
            last_planned=r["last_planned"]) for r in rows]

    async def mark_fired(self, schedule_id: str, planned: datetime) -> None:
        async with self._db.transaction() as c:
            await c.execute(
                "UPDATE event_schedules SET last_planned = $2 WHERE schedule_id = $1"
                " AND (last_planned IS NULL OR last_planned < $2)", schedule_id, planned)

    async def create(self, schedule: Schedule) -> None:
        """Store a schedule. Its history starts now: the newest planned time already in the past is
        marked handled, so creating a schedule never fires an old planned time."""
        check_schedule(schedule)
        p = schedule.principal
        now = await self.now()
        handled = latest_planned(schedule, now)
        async with self._db.transaction() as c:
            await c.execute(
                "INSERT INTO event_schedules (schedule_id, tenant_id, workspace_id, user_id, membership_id,"
                " connection_id, resource_scope, event_type, payload, kind, anchor, interval_seconds, at_seconds,"
                " weekday, last_planned) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15)",
                schedule.schedule_id, p.tenant_id, p.workspace_id, p.user_id, p.membership_id, p.connection_id,
                p.resource_scope, schedule.event_type, json.dumps(schedule.payload), schedule.kind,
                schedule.anchor, schedule.interval_seconds, schedule.at_seconds, schedule.weekday, handled)
