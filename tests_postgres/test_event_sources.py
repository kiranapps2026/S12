"""Phase C over real PostgreSQL: API, MCP and scheduled events, registered payload schemas, dedup,
tenant isolation, and the scheduler firing through the ONE pipeline."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.event_log import PostgresEventLog
from adapters.postgres.event_schemas import PostgresEventSchemas
from adapters.postgres.schedules import PostgresScheduleStore
from adapters.postgres.webhook_credentials import Kek, PostgresWebhookCredentials
from app import create_app
from bootstrap import build_runner
from contracts.principal import Principal
from contracts.schedule import Schedule
from engine.gateway import signature
from engine.gateway.run import run_received_event
from engine.gateway.scheduler import EventScheduler
from engine.gateway.schema import SchemaError
from engine.gateway.webhook import EventGateway

A, B = "tenant-a", "tenant-b"
KEK = Kek(bytes(range(32)), 1)
UTC = timezone.utc


class EventModel:
    """Recognises every event as a read of contacts (like a real model would recognise a known event)."""
    async def complete(self, text, intents, feedback):
        from contracts.intent_model import IntentCompletion
        return IntentCompletion(text=json.dumps({"intent": "contact.list", "confidence": 0.95, "parameters": {}}),
                                model="m", total_tokens=1)


def _principal(tenant):
    return Principal(tenant, f"{tenant}.ws", f"{tenant}.user", f"{tenant}.member", f"{tenant}.conn", "")


async def _stack(db, *, register=(("api", "order.placed", {"type": "object", "required": ["sku"]}),
                                   ("mcp", "mcp.tool_call", {"type": "object", "required": ["tool_name"]}),
                                   ("cron", "schedule.daily_sync", {"type": "object"})), tenants=(A, B)):
    schemas = PostgresEventSchemas(db)
    for tenant in tenants:
        for system, event_type, schema in register:
            await schemas.register(tenant, system, event_type, schema)
    store = PostgresWebhookCredentials(db, KEK)
    gateway = EventGateway(store, PostgresEventLog(db), schemas)
    auth = PostgresApiKeyAuthenticator(db)
    pipeline = build_runner(db, EventModel())
    return store, gateway, auth, pipeline


async def _log(db, tenant):
    async with db.tenant_transaction(tenant) as c:
        return [dict(r) for r in await c.fetch(
            "SELECT event_id, source, source_system, event_type, auth_method, auth_principal, processing_status,"
            " schema_version, idempotency_key, payload FROM event_log ORDER BY received_at")]


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


# ---- registered schemas ----------------------------------------------------------------------------

def test_schemas_are_versioned_the_newest_active_one_wins_and_tenants_cannot_see_each_other(pg):
    async def body(db):
        s = PostgresEventSchemas(db)
        v1 = await s.register(A, "api", "t", {"type": "object"})
        v2 = await s.register(A, "api", "t", {"type": "object", "required": ["k"]})
        latest = await s.latest(A, "api", "t")
        async with db.tenant_transaction(A) as c:
            await c.execute("UPDATE event_schemas SET is_active = false WHERE schema_version = 2")
        after_deactivate = await s.latest(A, "api", "t")
        return v1, v2, latest, after_deactivate, await s.latest(B, "api", "t"), await s.latest(A, "api", "other")
    v1, v2, latest, after, other_tenant, other_type = pg(body)
    assert (v1, v2) == (1, 2) and latest.version == "2" and latest.schema["required"] == ["k"]
    assert after.version == "1" and other_tenant is None and other_type is None


def test_a_schema_using_something_unenforced_cannot_be_registered(pg):
    async def body(db):
        with pytest.raises(SchemaError):
            await PostgresEventSchemas(db).register(A, "api", "t", {"pattern": "^a+$"})
        return await PostgresEventSchemas(db).latest(A, "api", "t")
    assert pg(body) is None


# ---- api source ------------------------------------------------------------------------------------

def test_an_api_event_runs_the_pipeline_as_the_keys_identity_and_is_logged(pg):
    async def body(db):
        _, gateway, auth, pipeline = await _stack(db)
        key = await auth.issue(_principal(A))
        app = create_app(pipeline=pipeline, authenticator=auth, webhooks=gateway)
        async with _client(app) as c:
            r = await c.post("/api/v1/events", headers={"authorization": f"Bearer {key}"},
                             json={"type": "order.placed", "payload": {"sku": "A-1", "tenant_id": B}})
        return r, await _log(db, A), await _log(db, B)
    r, a_log, b_log = pg(body)
    assert (r.status_code, r.json()["status"], r.json()["final_stage"]) == (200, "NORMAL", "S11"), r.text
    assert len(a_log) == 1 and b_log == []
    row = a_log[0]
    assert (row["source"], row["source_system"], row["event_type"], row["auth_method"], row["processing_status"],
            row["schema_version"]) == ("api", "api", "order.placed", "api_key", "processed", "1")
    assert row["auth_principal"] == "tenant-a.conn" and json.loads(row["payload"]) == {"sku": "A-1", "tenant_id": B}


def test_an_api_event_needs_a_key_a_registered_type_and_a_valid_payload(pg):
    async def body(db):
        _, gateway, auth, pipeline = await _stack(db)
        key = await auth.issue(_principal(A))
        app = create_app(pipeline=pipeline, authenticator=auth, webhooks=gateway)
        headers = {"authorization": f"Bearer {key}"}
        async with _client(app) as c:
            no_key = await c.post("/api/v1/events", json={"type": "order.placed", "payload": {"sku": "A"}})
            wrong = await c.post("/api/v1/events", headers={"authorization": "Bearer sk_supra_nope"},
                                 json={"type": "order.placed", "payload": {"sku": "A"}})
            unregistered = await c.post("/api/v1/events", headers=headers, json={"type": "nope.type", "payload": {}})
            invalid = await c.post("/api/v1/events", headers=headers, json={"type": "order.placed", "payload": {}})
            identity = await c.post("/api/v1/events", headers=headers,
                                    json={"type": "order.placed", "payload": {"sku": "A"}, "tenant_id": B})
        return (no_key.status_code, wrong.status_code, unregistered.status_code, unregistered.json()["detail"],
                invalid.status_code, invalid.json()["detail"], identity.status_code), await _log(db, A)
    codes, rows = pg(body)
    assert codes == (401, 401, 422, "event_type_not_registered", 422, "payload_invalid", 422)   # extra field refused
    assert rows == []                                           # nothing stored for any refused event


def test_an_api_event_with_a_client_key_is_acknowledged_once_and_without_one_runs_each_time(pg):
    async def body(db):
        _, gateway, auth, pipeline = await _stack(db)
        key = await auth.issue(_principal(A))
        app = create_app(pipeline=pipeline, authenticator=auth, webhooks=gateway)
        headers = {"authorization": f"Bearer {key}"}
        keyed = {"type": "order.placed", "payload": {"sku": "A"}, "idempotency_key": "client-1"}
        plain = {"type": "order.placed", "payload": {"sku": "A"}}
        async with _client(app) as c:
            first = await c.post("/api/v1/events", headers=headers, json=keyed)
            second = await c.post("/api/v1/events", headers=headers, json=keyed)
            plains = [await c.post("/api/v1/events", headers=headers, json=plain) for _ in range(2)]
        return first, second, plains, await _log(db, A)
    first, second, plains, rows = pg(body)
    assert first.json()["final_stage"] == "S11" and second.json()["reason"] == "duplicate_event"
    assert all(p.json()["final_stage"] == "S11" for p in plains) and len(rows) == 3


# ---- mcp source ------------------------------------------------------------------------------------

def test_a_signed_mcp_tool_call_runs_and_a_replay_does_not(pg):
    async def body(db):
        store, gateway, auth, pipeline = await _stack(db)
        endpoint, secret = await store.issue(_principal(A), "mcp")
        app = create_app(pipeline=pipeline, authenticator=auth, webhooks=gateway)
        raw = json.dumps({"tool_name": "fs.read", "arguments": {"path": "/a"}}).encode()
        header = signature.sign(secret.encode(), int(time.time()), raw)
        async with _client(app) as c:
            first = await c.post(f"/api/v1/mcp/{endpoint}", content=raw, headers={"x-signature": header})
            replay = await c.post(f"/api/v1/mcp/{endpoint}", content=raw, headers={"x-signature": header})
            bad = await c.post(f"/api/v1/mcp/{endpoint}", content=raw,
                               headers={"x-signature": signature.sign(b"wrong", int(time.time()), raw)})
            as_webhook = await c.post(f"/api/v1/webhooks/mcp/{endpoint}", content=raw, headers={"x-signature": header})
        return first, replay, bad, as_webhook, await _log(db, A)
    first, replay, bad, as_webhook, rows = pg(body)
    assert (first.status_code, first.json()["final_stage"]) == (200, "S11"), first.text
    assert replay.json()["reason"] == "duplicate_event" and bad.status_code == 401 and as_webhook.status_code == 401
    assert len(rows) == 1 and (rows[0]["source"], rows[0]["source_system"], rows[0]["event_type"]) == ("mcp", "mcp", "mcp.tool_call")
    assert rows[0]["auth_method"] == "hmac_sha256" and rows[0]["processing_status"] == "processed"


def test_an_mcp_credential_of_another_tenant_or_a_webhook_credential_does_not_authenticate(pg):
    async def body(db):
        store, gateway, auth, pipeline = await _stack(db)
        ep_a, _ = await store.issue(_principal(A), "mcp")
        _, secret_b = await store.issue(_principal(B), "mcp")
        ep_g, secret_g = await store.issue(_principal(A), "ghl")
        app = create_app(pipeline=pipeline, authenticator=auth, webhooks=gateway)
        raw = json.dumps({"tool_name": "fs.read"}).encode()
        async with _client(app) as c:
            other = await c.post(f"/api/v1/mcp/{ep_a}", content=raw, headers={
                "x-signature": signature.sign(secret_b.encode(), int(time.time()), raw)})
            ghl = await c.post(f"/api/v1/mcp/{ep_g}", content=raw, headers={
                "x-signature": signature.sign(secret_g.encode(), int(time.time()), raw)})
        return other.status_code, ghl.status_code
    assert pg(body) == (401, 401)


def test_the_event_endpoints_answer_503_when_the_gateway_is_not_configured(pg):
    async def body(db):
        _, _, auth, pipeline = await _stack(db)
        key = await auth.issue(_principal(A))
        app = create_app(pipeline=pipeline, authenticator=auth)
        async with _client(app) as c:
            api = await c.post("/api/v1/events", headers={"authorization": f"Bearer {key}"},
                               json={"type": "order.placed", "payload": {"sku": "A"}})
            mcp = await c.post("/api/v1/mcp/x", content=b"{}", headers={"x-signature": "t=1,v1=" + "a" * 64})
        return api.status_code, mcp.status_code
    assert pg(body) == (503, 503)


# ---- schedule source -------------------------------------------------------------------------------

def _interval(schedule_id="s1", tenant=A, anchor_ago=timedelta(hours=2), seconds=3600, event_type="schedule.daily_sync",
              payload=None, db_now=None):
    return Schedule(schedule_id=schedule_id, principal=_principal(tenant), event_type=event_type,
                    payload=payload or {"job": "sync"}, kind="interval", anchor=db_now - anchor_ago,
                    interval_seconds=seconds)


def test_creating_a_schedule_never_fires_an_old_planned_time_and_the_next_planned_time_fires_once(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db)
        store = PostgresScheduleStore(db)
        now = await store.now()
        await store.create(_interval(db_now=now))
        scheduler = EventScheduler(store, gateway, lambda r: run_received_event(pipeline, gateway, r))
        immediate = await scheduler.tick(now)                          # nothing due: history starts now
        later = now + timedelta(seconds=3700)
        fired = await scheduler.tick(later)
        again = await scheduler.tick(later)
        return immediate, fired, again, await _log(db, A), (await store.active())[0]
    immediate, fired, again, rows, stored = pg(body)
    assert immediate == [] and [f.outcome for f in fired] == ["ran"] and again == []
    assert len(rows) == 1
    row = rows[0]
    assert (row["source"], row["source_system"], row["event_type"], row["auth_method"], row["processing_status"]) == \
        ("schedule", "cron", "schedule.daily_sync", "schedule_internal", "processed")
    assert row["auth_principal"] == "s1" and row["idempotency_key"].startswith("schedule:cron:s1:")
    assert stored.last_planned == fired[0].planned


def test_downtime_is_coalesced_into_one_run_of_the_latest_planned_time(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db)
        store = PostgresScheduleStore(db)
        now = await store.now()
        await store.create(_interval(db_now=now, seconds=3600))
        scheduler = EventScheduler(store, gateway, lambda r: run_received_event(pipeline, gateway, r))
        out = await scheduler.tick(now + timedelta(hours=10, minutes=5))    # ten planned times missed
        return out, await _log(db, A)
    out, rows = pg(body)
    assert [f.outcome for f in out] == ["ran"] and len(rows) == 1


def test_two_schedulers_racing_on_one_planned_time_run_it_once(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db)
        store = PostgresScheduleStore(db)
        now = await store.now()
        await store.create(_interval(db_now=now))
        run = lambda r: run_received_event(pipeline, gateway, r)
        a, b = EventScheduler(store, gateway, run), EventScheduler(store, gateway, run)
        later = now + timedelta(seconds=3700)
        outs = await asyncio.gather(a.tick(later), b.tick(later))
        return sorted(f.outcome for out in outs for f in out), await _log(db, A)
    outcomes, rows = pg(body)
    assert outcomes == ["duplicate", "ran"] and len(rows) == 1


def test_each_tenants_schedule_fires_under_its_own_identity_and_stays_in_its_own_log(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db)
        store = PostgresScheduleStore(db)
        now = await store.now()
        await store.create(_interval("sa", A, db_now=now))
        await store.create(_interval("sb", B, db_now=now))
        scheduler = EventScheduler(store, gateway, lambda r: run_received_event(pipeline, gateway, r))
        out = await scheduler.tick(now + timedelta(seconds=3700))
        return sorted((f.schedule_id, f.outcome) for f in out), await _log(db, A), await _log(db, B)
    out, a_log, b_log = pg(body)
    assert out == [("sa", "ran"), ("sb", "ran")]
    assert [r["auth_principal"] for r in a_log] == ["sa"] and [r["auth_principal"] for r in b_log] == ["sb"]


def test_a_paused_tenants_scheduled_event_is_stopped_at_s0_1_like_any_run(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db)
        store = PostgresScheduleStore(db)
        now = await store.now()
        await store.create(_interval(db_now=now))
        async with db.tenant_transaction(A) as c:
            await c.execute("UPDATE tenants SET paused_until = now() + interval '1 day'")
        results = []

        async def run(received):
            results.append(await run_received_event(pipeline, gateway, received))
        await EventScheduler(store, gateway, run).tick(now + timedelta(seconds=3700))
        async with db.tenant_transaction(A) as c:
            stages = [r["stage"] for r in await c.fetch("SELECT stage FROM pipeline_events ORDER BY event_id")]
        return results, stages
    results, stages = pg(body)
    assert (results[0].status.value, results[0].reason) == ("DENY", "tenant_paused") and stages == ["S0", "S0.1"]


def test_a_scheduled_event_whose_type_is_not_registered_is_refused_once_and_not_retried(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db, register=())
        store = PostgresScheduleStore(db)
        now = await store.now()
        await store.create(_interval(db_now=now))
        scheduler = EventScheduler(store, gateway, lambda r: run_received_event(pipeline, gateway, r))
        later = now + timedelta(seconds=3700)
        first, second = await scheduler.tick(later), await scheduler.tick(later)
        return first, second, await _log(db, A)
    first, second, rows = pg(body)
    assert [(f.outcome, f.reason) for f in first] == [("refused", "event_type_not_registered")]
    assert second == [] and rows == []


def test_daily_and_weekly_schedules_are_stored_and_fire_at_their_planned_time(pg):
    async def body(db):
        _, gateway, _, pipeline = await _stack(db)
        store = PostgresScheduleStore(db)
        now = await store.now()
        d = Schedule("daily1", _principal(A), "schedule.daily_sync", {"job": "d"}, "daily", at_seconds=9 * 3600)
        w = Schedule("weekly1", _principal(A), "schedule.daily_sync", {"job": "w"}, "weekly", at_seconds=9 * 3600, weekday=1)
        await store.create(d)
        await store.create(w)
        scheduler = EventScheduler(store, gateway, lambda r: run_received_event(pipeline, gateway, r))
        return await scheduler.tick(now + timedelta(days=8)), await _log(db, A)
    out, rows = pg(body)
    assert sorted(f.schedule_id for f in out) == ["daily1", "weekly1"] and len(rows) == 2


def test_a_malformed_schedule_cannot_be_stored(pg):
    async def body(db):
        store = PostgresScheduleStore(db)
        for bad in (Schedule("x", _principal(A), "t", {}, "daily", at_seconds=99999),
                    Schedule("y", _principal(A), "t", {}, "interval", interval_seconds=30,
                             anchor=datetime.now(UTC))):
            with pytest.raises(ValueError):
                await store.create(bad)
        return await store.active()
    assert pg(body) == []


def test_the_scheduler_task_starts_with_the_app_and_is_cancelled_with_it(pg):
    """`run_forever` ticks repeatedly and stops cleanly when cancelled (the lifespan does exactly this)."""
    from engine.gateway.scheduler import run_forever

    class Counting:
        def __init__(self):
            self.ticks = 0

        async def tick(self):
            self.ticks += 1
            if self.ticks == 2:
                raise RuntimeError("one bad tick must not stop the loop")

    async def body(db):
        counter = Counting()
        task = asyncio.create_task(run_forever(counter, 0.01))
        await asyncio.sleep(0.15)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return counter.ticks, task.cancelled()
    ticks, cancelled = pg(body)
    assert ticks >= 3 and cancelled
