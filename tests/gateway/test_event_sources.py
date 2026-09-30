"""Phase C: schedule, MCP and API event sources and per-event-type payload validation (no database)."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from contracts.errors import DependencyUnavailable
from contracts.event_schema import RegisteredSchema
from contracts.principal import Principal
from contracts.schedule import Schedule
from engine.gateway import schema as sc
from engine.gateway import signature
from engine.gateway.schedule import check_schedule, due, latest_planned
from engine.gateway.scheduler import EventScheduler
from engine.gateway.webhook import EventGateway, WebhookRejected
from tests.gateway.test_webhook_gateway import Log, NOW, PRINCIPAL, SECRET, Store

UTC = timezone.utc


class Schemas:
    def __init__(self, table=None, error=None):
        self.table, self.error = table or {}, error

    async def latest(self, tenant_id, source_system, event_type):
        if self.error:
            raise self.error
        return self.table.get((source_system, event_type))


class Permissive:
    async def latest(self, tenant_id, source_system, event_type):
        return RegisteredSchema("1", {"type": "object"})


def gateway(table=None, *, schemas="default", log=None, store=None, clock=NOW):
    if schemas == "default":
        schemas = Permissive() if table is None else Schemas(table)
    return EventGateway(store or Store(), log or Log(), schemas, clock=lambda: clock)


def reg(schema=None, version="1"):
    return RegisteredSchema(version, schema if schema is not None else {"type": "object"})


def run(coro):
    return asyncio.run(coro)


def rejected(coro):
    with pytest.raises(WebhookRejected) as caught:
        run(coro)
    return caught.value.status, caught.value.reason


# ---- the schema subset -----------------------------------------------------------------------------

CONTACT = {"type": "object", "required": ["name", "age"], "additionalProperties": False,
           "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 5},
                          "age": {"type": "integer", "minimum": 0, "maximum": 150},
                          "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
                          "kind": {"enum": ["a", "b"]}}}


@pytest.mark.parametrize("value,ok", [
    ({"name": "Ana", "age": 30}, True),
    ({"name": "Ana", "age": 30, "tags": ["x"], "kind": "a"}, True),
    ({"name": "Ana"}, False),                               # required
    ({"name": "", "age": 1}, False), ({"name": "Anabel", "age": 1}, False),
    ({"name": "Ana", "age": "30"}, False), ({"name": "Ana", "age": 30.5}, False),
    ({"name": "Ana", "age": True}, False),                  # a boolean is not an integer
    ({"name": "Ana", "age": -1}, False), ({"name": "Ana", "age": 151}, False),
    ({"name": "Ana", "age": 1, "extra": 1}, False),         # additionalProperties false
    ({"name": "Ana", "age": 1, "tags": ["a", "b", "c"]}, False),
    ({"name": "Ana", "age": 1, "tags": [1]}, False),
    ({"name": "Ana", "age": 1, "kind": "z"}, False),
    ([], False), ("x", False),
])
def test_the_validator_enforces_each_supported_keyword(value, ok):
    assert (sc.validate(CONTACT, value) is None) is ok


def test_number_null_and_type_lists():
    assert sc.validate({"type": "number"}, 1.5) is None and sc.validate({"type": "number"}, True) is not None
    assert sc.validate({"type": ["string", "null"]}, None) is None and sc.validate({"type": ["string", "null"]}, 1) is not None


@pytest.mark.parametrize("schema", [
    {"pattern": "^a+$"}, {"format": "email"}, {"$ref": "#/x"}, {"oneOf": []}, {"type": "wat"},
    {"properties": []}, {"required": "name"}, {"additionalProperties": {"type": "string"}},
    {"minLength": -1}, {"maxLength": True}, {"enum": []}, {"minimum": "1"}, {"items": []}, "not a schema",
])
def test_a_schema_using_anything_unenforced_is_refused_not_ignored(schema):
    with pytest.raises(sc.SchemaError):
        sc.check_schema(schema)


def test_schemas_are_depth_bounded():
    schema = {"type": "string"}
    for _ in range(12):
        schema = {"type": "object", "properties": {"a": schema}}
    with pytest.raises(sc.SchemaError):
        sc.check_schema(schema)
    deep = "x"
    for _ in range(40):
        deep = {"a": deep}
    assert sc.validate({"type": "object"}, deep) is None or True   # validation terminates on deep values


def test_a_valid_schema_passes_check():
    sc.check_schema(CONTACT)


# ---- registration is required and the payload must fit ---------------------------------------------

BODY = json.dumps({"type": "contact.created", "id": "e1", "name": "Ana", "age": 30}).encode()


def _signed(body=BODY, ts=NOW, secret=SECRET):
    return signature.sign(secret, ts, body)


def test_an_unregistered_event_type_is_refused_and_nothing_is_stored():
    log = Log()
    g = gateway({}, log=log)
    assert rejected(g.receive("ghl", "ep-1", BODY, _signed())) == (422, "event_type_not_registered")
    assert log.rows == {}


def test_a_payload_that_does_not_fit_its_schema_is_refused_and_nothing_is_stored():
    log = Log()
    g = gateway({("ghl", "contact.created"): reg({"type": "object", "required": ["email"]})}, log=log)
    assert rejected(g.receive("ghl", "ep-1", BODY, _signed())) == (422, "payload_invalid")
    assert log.rows == {}


def test_a_matching_payload_is_accepted_and_the_envelope_records_the_schema_version():
    g = gateway({("ghl", "contact.created"): reg({"type": "object", "required": ["name"]}, "7")})
    got = run(g.receive("ghl", "ep-1", BODY, _signed()))
    assert got.envelope.schema_version == "7" and got.duplicate is False


def test_the_registry_is_asked_for_the_authenticated_tenant_and_the_source_system():
    schemas = Schemas({("ghl", "contact.created"): reg()})
    g = EventGateway(Store(), Log(), schemas)
    g._clock = lambda: NOW
    seen = []
    orig = schemas.latest

    async def spy(tenant, system, etype):
        seen.append((tenant, system, etype))
        return await orig(tenant, system, etype)
    schemas.latest = spy
    run(g.receive("ghl", "ep-1", json.dumps({"type": "contact.created", "tenant_id": "tenant-2"}).encode(),
                  _signed(json.dumps({"type": "contact.created", "tenant_id": "tenant-2"}).encode())))
    assert seen == [("tenant-1", "ghl", "contact.created")]


def test_an_unusable_registered_schema_or_an_unreadable_or_missing_registry_fails_closed():
    bad = gateway({("ghl", "contact.created"): reg({"pattern": "x"})})
    assert rejected(bad.receive("ghl", "ep-1", BODY, _signed())) == (422, "event_schema_invalid")
    down = gateway(schemas=Schemas(error=DependencyUnavailable("db")))
    assert rejected(down.receive("ghl", "ep-1", BODY, _signed())) == (503, "event_schemas_unavailable")
    none = gateway(schemas=None)
    assert rejected(none.receive("ghl", "ep-1", BODY, _signed())) == (503, "event_schemas_unavailable")


def test_validation_happens_after_authentication_so_an_unauthenticated_caller_learns_nothing():
    g = gateway({})
    assert rejected(g.receive("ghl", "ep-1", BODY, _signed(secret=b"wrong"))) == (401, "unauthenticated")


# ---- mcp -------------------------------------------------------------------------------------------

MCP = json.dumps({"tool_name": "fs.read", "arguments": {"path": "/a"}}).encode()


def test_a_signed_mcp_tool_call_becomes_an_mcp_event_for_the_credentials_identity():
    g = _mcp_gateway({("mcp", "mcp.tool_call"): reg({"type": "object", "required": ["tool_name"]})})
    got = run(_mcp(g))
    e = got.envelope
    assert (e.source, e.source_system, e.type, e.tenant_id) == ("mcp", "mcp", "mcp.tool_call", "tenant-1")
    assert got.payload == {"tool_name": "fs.read", "arguments": {"path": "/a"}}


def _mcp(g, body=MCP, ts=NOW, secret=SECRET, endpoint="ep-1"):
    return g.receive_mcp(endpoint, body, signature.sign(secret, ts, body))


class McpStore(Store):
    async def endpoint(self, endpoint_id, source_system):
        return await super().endpoint("ep-1" if endpoint_id == "ep-1" and source_system == "mcp" else "nope", "ghl")


def _mcp_gateway(table=None, log=None):
    return EventGateway(McpStore(), log or Log(), Schemas(table if table is not None else
                                                          {("mcp", "mcp.tool_call"): reg()}), clock=lambda: NOW)


def test_mcp_is_authenticated_like_a_webhook_and_uses_the_mcp_credential_only():
    g = _mcp_gateway()
    assert run(_mcp(g)).envelope.source == "mcp"
    assert rejected(_mcp(g, secret=b"wrong")) == (401, "unauthenticated")
    assert rejected(_mcp(g, endpoint="other")) == (401, "unauthenticated")
    assert rejected(_mcp(g, ts=NOW - 400)) == (400, "stale_timestamp")
    # a webhook credential does not authenticate an MCP call, and the mcp source is not a webhook source
    assert rejected(g.receive("mcp", "ep-1", MCP, signature.sign(SECRET, NOW, MCP))) == (401, "unauthenticated")


@pytest.mark.parametrize("body", [b"[]", b"{}", json.dumps({"tool_name": "a b"}).encode(),
                                  json.dumps({"tool_name": "x", "arguments": []}).encode(),
                                  json.dumps({"tool_name": 5}).encode()])
def test_a_malformed_mcp_call_is_refused(body):
    assert rejected(_mcp(_mcp_gateway(), body=body))[0] == 400


def test_mcp_needs_a_registered_schema_for_mcp_tool_call():
    g = _mcp_gateway({})
    assert rejected(_mcp(g)) == (422, "event_type_not_registered")
    g = _mcp_gateway({("mcp", "mcp.tool_call"): reg({"type": "object", "properties": {
        "tool_name": {"enum": ["fs.read"]}}})})
    assert run(_mcp(g)).duplicate is False
    other = json.dumps({"tool_name": "fs.delete"}).encode()
    assert rejected(_mcp(g, body=other)) == (422, "payload_invalid")


def test_a_replayed_signed_mcp_request_is_a_duplicate_but_a_new_signature_is_a_new_call():
    log = Log()
    g = _mcp_gateway(log=log)
    assert run(_mcp(g)).duplicate is False
    assert run(_mcp(g)).duplicate is True                       # captured and replayed within the window
    g2 = EventGateway(McpStore(), log, Schemas({("mcp", "mcp.tool_call"): reg()}), clock=lambda: NOW + 5)
    assert run(_mcp(g2, ts=NOW + 5)).duplicate is False
    keyed = json.dumps({"tool_name": "fs.read", "id": "call-9"}).encode()
    assert run(_mcp(g, body=keyed)).duplicate is False and run(_mcp(g, body=keyed, ts=NOW + 1)).duplicate is True
    assert log.keys[-1] == "mcp:mcp:call-9"


def test_mcp_without_the_key_encryption_key_answers_503():
    g = EventGateway(None, Log(), Schemas({("mcp", "mcp.tool_call"): reg()}), clock=lambda: NOW)
    assert rejected(_mcp(g)) == (503, "webhooks_unavailable")


# ---- api -------------------------------------------------------------------------------------------

def test_an_api_event_runs_as_the_callers_identity_and_the_body_cannot_change_it():
    log = Log()
    g = gateway({("api", "order.placed"): reg({"type": "object", "required": ["sku"]})}, log=log)
    got = run(g.receive_api(PRINCIPAL, {"type": "order.placed", "payload": {"sku": "A", "tenant_id": "tenant-2"}}, "req-1"))
    e = got.envelope
    assert (e.source, e.source_system, e.type, e.tenant_id, e.workspace_id) == \
        ("api", "api", "order.placed", "tenant-1", "ws-1")
    assert got.principal == PRINCIPAL and log.keys == ["api:api:req-1"]


def test_api_events_are_validated_and_must_be_registered():
    g = gateway({("api", "order.placed"): reg({"type": "object", "required": ["sku"]})})
    assert rejected(g.receive_api(PRINCIPAL, {"type": "order.placed", "payload": {}})) == (422, "payload_invalid")
    assert rejected(g.receive_api(PRINCIPAL, {"type": "unknown.type", "payload": {}})) == (422, "event_type_not_registered")


@pytest.mark.parametrize("body,reason", [({"type": ""}, "invalid_event_type"), ({"type": "a b"}, "invalid_event_type"),
                                         ({"payload": {}}, "invalid_event_type"), ({"type": "x", "payload": []}, "invalid_json")])
def test_malformed_api_events_are_refused(body, reason):
    assert rejected(gateway().receive_api(PRINCIPAL, body)) == (400, reason)


def test_an_api_event_without_a_client_key_is_new_every_time_and_with_one_it_deduplicates():
    log = Log()
    g = gateway(log=log)
    body = {"type": "order.placed", "payload": {"sku": "A"}}
    assert [run(g.receive_api(PRINCIPAL, body, f"req-{i}")).duplicate for i in range(3)] == [False] * 3
    keyed = {**body, "idempotency_key": "client-1"}
    assert [run(g.receive_api(PRINCIPAL, keyed, f"req-x{i}")).duplicate for i in range(2)] == [False, True]


def test_an_oversize_api_payload_is_refused():
    big = {"type": "x", "payload": {"blob": "z" * 70000}}
    assert rejected(gateway().receive_api(PRINCIPAL, big)) == (413, "payload_too_large")


def test_the_same_client_key_in_two_tenants_is_two_events():
    log = Log()
    g = gateway(log=log)
    other = Principal("tenant-2", "ws-2", "u", "m", "c", "")
    body = {"type": "x", "payload": {}, "idempotency_key": "k"}
    assert run(g.receive_api(PRINCIPAL, body)).duplicate is False
    assert run(g.receive_api(other, body)).duplicate is False


def test_a_very_long_key_is_replaced_by_its_digest():
    log = Log()
    run(gateway(log=log).receive_api(PRINCIPAL, {"type": "x", "payload": {}, "idempotency_key": "k" * 128}, "r" * 250))
    assert len(log.keys[0]) <= 256


# ---- schedules: planned times ----------------------------------------------------------------------

def sched(kind="interval", **kw):
    base = dict(schedule_id="s1", principal=PRINCIPAL, event_type="schedule.daily_sync")
    if kind == "interval":
        base.update(kind="interval", anchor=datetime(2026, 1, 1, tzinfo=UTC), interval_seconds=3600)
    elif kind == "daily":
        base.update(kind="daily", at_seconds=9 * 3600)
    else:
        base.update(kind="weekly", at_seconds=9 * 3600, weekday=1)
    base.update(kw)
    return Schedule(**base)


def at(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


def test_interval_planned_times_are_anchor_plus_whole_intervals():
    s = sched()
    assert latest_planned(s, at(2026, 1, 1, 0, 59)) == at(2026, 1, 1, 0)
    assert latest_planned(s, at(2026, 1, 1, 1, 0)) == at(2026, 1, 1, 1)
    assert latest_planned(s, at(2026, 1, 1, 3, 30)) == at(2026, 1, 1, 3)
    assert latest_planned(s, at(2025, 12, 31, 23, 59)) is None          # before the anchor


def test_daily_planned_time_is_the_latest_occurrence_not_after_now():
    s = sched("daily")
    assert latest_planned(s, at(2026, 3, 5, 9, 0)) == at(2026, 3, 5, 9)
    assert latest_planned(s, at(2026, 3, 5, 8, 59)) == at(2026, 3, 4, 9)
    assert latest_planned(s, at(2026, 3, 5, 23, 59)) == at(2026, 3, 5, 9)


def test_weekly_planned_time_is_the_latest_matching_weekday():
    s = sched("weekly")                                                  # Mondays 09:00 UTC; 2026-03-02 is a Monday
    assert latest_planned(s, at(2026, 3, 2, 9, 0)) == at(2026, 3, 2, 9)
    assert latest_planned(s, at(2026, 3, 2, 8, 0)) == at(2026, 2, 23, 9)
    assert latest_planned(s, at(2026, 3, 8, 12)) == at(2026, 3, 2, 9)


def test_a_missed_period_is_coalesced_into_the_latest_planned_time_only():
    s = sched(last_planned=at(2026, 1, 1, 1))
    assert due(s, at(2026, 1, 1, 9, 30)) == at(2026, 1, 1, 9)            # 8 missed hours -> one fire
    assert due(sched(last_planned=at(2026, 1, 1, 9)), at(2026, 1, 1, 9, 30)) is None
    assert due(sched(last_planned=at(2026, 1, 1, 10)), at(2026, 1, 1, 9, 30)) is None


def test_a_naive_time_is_treated_as_utc_and_offsets_are_normalised():
    plus2 = timezone(timedelta(hours=2))
    assert latest_planned(sched("daily"), datetime(2026, 3, 5, 11, 0, tzinfo=plus2)) == at(2026, 3, 5, 9)
    assert latest_planned(sched("daily"), datetime(2026, 3, 5, 9, 0)) == at(2026, 3, 5, 9)


@pytest.mark.parametrize("kwargs", [
    {"kind": "hourly"}, {"interval_seconds": 30}, {"anchor": None}, {"interval_seconds": None},
])
def test_a_malformed_interval_schedule_is_rejected(kwargs):
    import dataclasses
    with pytest.raises(ValueError):
        check_schedule(dataclasses.replace(sched(), **kwargs))


@pytest.mark.parametrize("kind,kwargs", [("daily", {"at_seconds": 86400}), ("daily", {"at_seconds": -1}),
                                          ("daily", {"at_seconds": None}), ("weekly", {"weekday": 0}),
                                          ("weekly", {"weekday": 8}), ("weekly", {"weekday": None})])
def test_malformed_daily_and_weekly_schedules_are_rejected(kind, kwargs):
    with pytest.raises(ValueError):
        check_schedule(sched(kind, **kwargs))


# ---- schedule events through the gateway and the scheduler ------------------------------------------

def test_a_schedule_event_uses_the_stored_identity_and_the_planned_time_in_its_key():
    log = Log()
    g = gateway({("cron", "schedule.daily_sync"): reg()}, log=log)
    got = run(g.receive_schedule(sched("daily"), at(2026, 3, 5, 9)))
    e = got.envelope
    assert (e.source, e.source_system, e.type, e.tenant_id, e.timestamp) == \
        ("schedule", "cron", "schedule.daily_sync", "tenant-1", "2026-03-05T09:00:00+00:00")
    assert log.keys == ["schedule:cron:s1:2026-03-05T09:00:00+00:00"]


def test_the_same_planned_time_is_one_event_and_the_next_planned_time_is_another():
    g = gateway({("cron", "schedule.daily_sync"): reg()})
    s = sched("daily")
    assert [run(g.receive_schedule(s, at(2026, 3, 5, 9))).duplicate for _ in range(2)] == [False, True]
    assert run(g.receive_schedule(s, at(2026, 3, 6, 9))).duplicate is False


def test_a_scheduled_event_type_must_be_registered_and_its_payload_valid():
    assert rejected(gateway({}).receive_schedule(sched("daily"), at(2026, 3, 5, 9))) == (422, "event_type_not_registered")
    g = gateway({("cron", "schedule.daily_sync"): reg({"type": "object", "required": ["job"]})})
    assert rejected(g.receive_schedule(sched("daily"), at(2026, 3, 5, 9))) == (422, "payload_invalid")
    assert run(g.receive_schedule(sched("daily", payload={"job": "x"}), at(2026, 3, 5, 9))).duplicate is False


class Store2:
    def __init__(self, schedules, now):
        self.schedules, self._now, self.marked = schedules, now, []

    async def now(self):
        return self._now

    async def active(self):
        return list(self.schedules)

    async def mark_fired(self, schedule_id, planned):
        self.marked.append((schedule_id, planned))


def _scheduler(schedules, now, table=None, run_fn=None):
    ran = []

    async def runner(received):
        ran.append(received.envelope.type)
        if run_fn:
            await run_fn(received)
    g = gateway(table if table is not None else {("cron", "schedule.daily_sync"): reg()})
    store = Store2(schedules, now)
    return EventScheduler(store, g, runner), store, ran


def test_a_tick_fires_each_due_schedule_once_and_marks_it_handled():
    scheduler, store, ran = _scheduler([sched("daily")], at(2026, 3, 5, 9, 1))
    first = run(scheduler.tick())
    assert [(f.outcome, f.planned) for f in first] == [("ran", at(2026, 3, 5, 9))]
    assert ran == ["schedule.daily_sync"] and store.marked == [("s1", at(2026, 3, 5, 9))]


def test_a_second_scheduler_racing_on_the_same_planned_time_runs_nothing():
    g = gateway({("cron", "schedule.daily_sync"): reg()})
    ran = []

    async def runner(received):
        ran.append(1)
    a = EventScheduler(Store2([sched("daily")], at(2026, 3, 5, 9, 1)), g, runner)
    b = EventScheduler(Store2([sched("daily")], at(2026, 3, 5, 9, 1)), g, runner)
    assert [f.outcome for f in run(a.tick())] == ["ran"]
    assert [f.outcome for f in run(b.tick())] == ["duplicate"]
    assert len(ran) == 1


def test_nothing_due_means_nothing_fires():
    scheduler, store, ran = _scheduler([sched("daily", last_planned=at(2026, 3, 5, 9))], at(2026, 3, 5, 9, 30))
    assert run(scheduler.tick()) == [] and ran == [] and store.marked == []


def test_a_refused_event_is_marked_handled_so_it_does_not_refuse_every_tick():
    scheduler, store, ran = _scheduler([sched("daily")], at(2026, 3, 5, 9, 1), table={})
    out = run(scheduler.tick())
    assert [(f.outcome, f.reason) for f in out] == [("refused", "event_type_not_registered")]
    assert store.marked == [("s1", at(2026, 3, 5, 9))] and ran == []


def test_an_unavailable_registry_is_not_marked_so_the_next_tick_retries():
    g = gateway(schemas=Schemas(error=DependencyUnavailable("db")))
    store = Store2([sched("daily")], at(2026, 3, 5, 9, 1))
    out = run(EventScheduler(store, g, lambda r: None).tick())
    assert out[0].outcome == "refused" and out[0].reason == "event_schemas_unavailable" and store.marked == []


def test_a_crashing_run_does_not_stop_the_other_schedules_and_is_not_marked():
    async def boom(received):
        raise RuntimeError("pipeline crashed")
    two = [sched("daily", schedule_id="a"), sched("daily", schedule_id="b")]
    g = gateway({("cron", "schedule.daily_sync"): reg()})
    calls = []

    async def runner(received):
        calls.append(received.envelope.event_id)
        if len(calls) == 1:
            await boom(received)
    store = Store2(two, at(2026, 3, 5, 9, 1))
    out = run(EventScheduler(store, g, runner).tick())
    assert [f.outcome for f in out] == ["failed", "ran"] and store.marked == [("b", at(2026, 3, 5, 9))]


def test_a_malformed_schedule_is_reported_and_skipped():
    bad = sched("daily", at_seconds=None)
    scheduler, store, ran = _scheduler([bad, sched("daily", schedule_id="ok")], at(2026, 3, 5, 9, 1))
    out = run(scheduler.tick())
    assert [(f.schedule_id, f.outcome) for f in out] == [("s1", "refused"), ("ok", "ran")]
