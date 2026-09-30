"""Schedules that fire events (EVENT_GATEWAY receive_schedule): a fixed identity, an event type and payload,
and when to fire. The scheduler decides WHEN; the gateway authenticates, validates, dedups and records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from contracts.principal import Principal

KINDS = ("interval", "daily", "weekly")


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    principal: Principal                     # the fixed identity the fired event runs as (a service user)
    event_type: str
    payload: dict = field(default_factory=dict)
    kind: str = "interval"                   # interval | daily | weekly
    anchor: datetime | None = None           # UTC; the first planned time of an interval schedule
    interval_seconds: int | None = None      # interval
    at_seconds: int | None = None            # daily/weekly: seconds after UTC midnight
    weekday: int | None = None               # weekly: ISO weekday 1 (Mon) .. 7 (Sun)
    last_planned: datetime | None = None     # newest planned fire time already handled


class ScheduleStore(Protocol):
    async def now(self) -> datetime:
        """Authoritative (database) time, UTC."""

    async def active(self) -> list[Schedule]:
        """Every active schedule, across tenants (a system component)."""

    async def mark_fired(self, schedule_id: str, planned: datetime) -> None:
        """Record that `planned` was handled (fired, or already fired by another scheduler)."""
