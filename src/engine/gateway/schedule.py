"""When a schedule is due: pure functions over UTC time (no clock reads, no I/O).

Planned fire times: `interval` = anchor + k * interval_seconds; `daily` = every UTC day at `at_seconds`;
`weekly` = every ISO `weekday` at `at_seconds`. After downtime the scheduler fires only the LATEST due
planned time (missed ones are coalesced, never replayed as a burst).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contracts.schedule import KINDS, Schedule

DAY = 86400


def check_schedule(s: Schedule) -> None:
    """Raise ValueError if the schedule cannot produce planned times."""
    if s.kind not in KINDS:
        raise ValueError("unknown schedule kind")
    if s.kind == "interval":
        if s.anchor is None or not isinstance(s.interval_seconds, int) or s.interval_seconds < 60:
            raise ValueError("interval schedules need an anchor and interval_seconds >= 60")
    else:
        if not isinstance(s.at_seconds, int) or not 0 <= s.at_seconds < DAY:
            raise ValueError("at_seconds must be within a day")
        if s.kind == "weekly" and (not isinstance(s.weekday, int) or not 1 <= s.weekday <= 7):
            raise ValueError("weekday must be 1..7")


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def latest_planned(s: Schedule, now: datetime) -> datetime | None:
    """The newest planned fire time <= now (and >= the anchor when there is one), or None."""
    check_schedule(s)
    now = _utc(now)
    if s.kind == "interval":
        anchor = _utc(s.anchor)
        if now < anchor:
            return None
        k = int((now - anchor).total_seconds() // s.interval_seconds)
        return anchor + timedelta(seconds=k * s.interval_seconds)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate = midnight + timedelta(seconds=s.at_seconds)
    if s.kind == "daily":
        planned = candidate if candidate <= now else candidate - timedelta(days=1)
    else:
        planned = candidate - timedelta(days=(candidate.isoweekday() - s.weekday) % 7)
        if planned > now:
            planned -= timedelta(days=7)
    if s.anchor is not None and planned < _utc(s.anchor):
        return None
    return planned


def due(s: Schedule, now: datetime) -> datetime | None:
    """The planned time to fire now, or None if nothing is due (already handled or not yet reached)."""
    planned = latest_planned(s, now)
    if planned is None:
        return None
    if s.last_planned is not None and planned <= _utc(s.last_planned):
        return None
    return planned
