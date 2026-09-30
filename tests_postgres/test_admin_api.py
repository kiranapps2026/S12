"""Admin API over real PostgreSQL: who may administer, tenant isolation, role ceiling, once-only secrets,
audit in the same transaction, and that what an administrator creates really works."""
from __future__ import annotations

import json
import time
from datetime import timedelta

import asyncpg
import httpx
import pytest

from adapters.postgres.admin import AdminService
from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.event_log import PostgresEventLog
from adapters.postgres.event_schemas import PostgresEventSchemas
from adapters.postgres.schedules import PostgresScheduleStore
from adapters.postgres.webhook_credentials import Kek, PostgresWebhookCredentials
from app import create_app
from bootstrap import build_runner
from contracts.principal import Principal
from engine.gateway import signature
from engine.gateway.run import run_received_event
from engine.gateway.scheduler import EventScheduler
from engine.gateway.webhook import EventGateway
from tests_postgres.test_event_sources import EventModel

A, B = "tenant-a", "tenant-b"
KEK = Kek(bytes(range(32)), 1)


def _member(tenant, name, role):
    """SQL: a user with a membership of `role` and an active connection (ids: {tenant}.{name}[.member|.conn])."""
    user, member, conn = f"{tenant}.{name}", f"{tenant}.{name}.member", f"{tenant}.{name}.conn"
    return [
        f"INSERT INTO users (user_id, tenant_id) VALUES ('{user}', '{tenant}')",
        f"INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role) VALUES"
        f" ('{member}', '{tenant}', '{user}', '{tenant}.ws', '{role}')",
        f"INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id) VALUES"
        f" ('{conn}', '{tenant}', '{user}', '{tenant}.ws')",
    ]


WORLD = (
    "UPDATE memberships SET role = 'admin' WHERE membership_id = 'tenant-a.member'",     # tenant-a's caller
    "UPDATE memberships SET role = 'admin' WHERE membership_id = 'tenant-b.member'",
    *_member(A, "svc", "member"), *_member(A, "boss", "owner"), *_member(A, "peer", "admin"),
    *_member(A, "viewer", "viewer"), *_member(B, "svc", "member"),
    # the service identity may use the same capabilities the seed grants tenant-a's own user
    "INSERT INTO capability_grants SELECT 'g.svc.' || capability_id, tenant_id, workspace_id, 'tenant-a.svc',"
    " capability_id, true, NULL FROM capability_grants WHERE user_id = 'tenant-a.user'",
)


def _principal(tenant, name=None):
    if name is None:
        return Principal(tenant, f"{tenant}.ws", f"{tenant}.user", f"{tenant}.member", f"{tenant}.conn", "")
    return Principal(tenant, f"{tenant}.ws", f"{tenant}.{name}", f"{tenant}.{name}.member", f"{tenant}.{name}.conn", "")


class Env:
    """An app with the admin service; `call(tenant_or_key, method, path, json)`."""
    def __init__(self, db, app, auth, keys):
        self.db, self.app, self.auth, self.keys = db, app, auth, keys

    async def call(self, who, method, path, body=None, headers=None):
        key = self.keys.get(who, who)
        hdr = {"authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t") as client:
            return await client.request(method, f"/api/v1/admin{path}", json=body, headers={**hdr, **(headers or {})})


async def _env(db, *, kek=True, admins=(A, B)):
    creds = PostgresWebhookCredentials(db, KEK) if kek else None
    service = AdminService(db, creds)
    auth = PostgresApiKeyAuthenticator(db)
    keys = {A: await auth.issue(_principal(A)), B: await auth.issue(_principal(B)),
            "member-a": await auth.issue(_principal(A, "svc")), "owner-a": await auth.issue(_principal(A, "boss")),
            "viewer-a": await auth.issue(_principal(A, "viewer")), "peer-a": await auth.issue(_principal(A, "peer"))}
    app = create_app(authenticator=auth, admin=service, webhooks=EventGateway(creds, PostgresEventLog(db), PostgresEventSchemas(db)),
                     pipeline=build_runner(db, EventModel()))
    return Env(db, app, auth, keys)


async def _audit(db, tenant):
    async with db.tenant_transaction(tenant) as c:
        return [dict(r) for r in await c.fetch("SELECT * FROM admin_audit ORDER BY audit_id")]


SVC = {"membership_id": "tenant-a.svc.member", "connection_id": "tenant-a.svc.conn"}


# ---- who may administer ------------------------------------------------------------------------------------

def test_only_an_active_owner_or_admin_may_administer(pg):
    async def body(db):
        e = await _env(db)
        results = {}
        for who in ("member-a", "viewer-a", A, "owner-a", "peer-a"):
            results[who] = (await e.call(who, "GET", "/api-keys")).status_code
        results["nokey"] = (await e.call(None, "GET", "/api-keys")).status_code
        results["badkey"] = (await e.call("sk_supra_nope", "GET", "/api-keys")).status_code
        return results
    r = pg(body, *WORLD)
    assert r == {"member-a": 403, "viewer-a": 403, A: 200, "owner-a": 200, "peer-a": 200, "nokey": 401, "badkey": 401}


@pytest.mark.parametrize("change", [
    "UPDATE memberships SET role = 'member' WHERE membership_id = 'tenant-a.member'",          # role downgraded
    "UPDATE memberships SET is_active = false WHERE membership_id = 'tenant-a.member'",
    "UPDATE memberships SET revoked_at = now() WHERE membership_id = 'tenant-a.member'",
    "UPDATE users SET status = 'suspended' WHERE user_id = 'tenant-a.user'",
    "UPDATE tenants SET status = 'suspended' WHERE tenant_id = 'tenant-a'",
])
def test_admin_rights_are_checked_live_on_every_request(pg, change):
    async def body(db):
        e = await _env(db)
        before = (await e.call(A, "GET", "/api-keys")).status_code
        async with db.tenant_transaction(A) as c:
            await c.execute(change)
        return before, (await e.call(A, "GET", "/api-keys")).status_code
    assert pg(body, *WORLD) == (200, 403)


def test_the_admin_api_answers_503_when_it_is_not_configured(pg):
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        key = await auth.issue(_principal(A))
        app = create_app(authenticator=auth)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return (await c.get("/api/v1/admin/api-keys", headers={"authorization": f"Bearer {key}"})).status_code
    assert pg(body, *WORLD) == 503


# ---- API keys ----------------------------------------------------------------------------------------------

def test_an_issued_key_is_shown_once_works_for_the_target_identity_and_can_be_revoked(pg):
    async def body(db):
        e = await _env(db)
        r = await e.call(A, "POST", "/api-keys", {**SVC, "label": "ci"})
        key, key_id = r.json()["api_key"], r.json()["key_id"]
        who = await e.auth.authenticate(key)
        listing = await e.call(A, "GET", "/api-keys")
        revoke = await e.call(A, "DELETE", f"/api-keys/{key_id}")
        after = await e.auth.authenticate(key)
        again = await e.call(A, "DELETE", f"/api-keys/{key_id}")
        return r, key, key_id, who, listing, revoke.status_code, after, again.status_code, await _audit(db, A)
    r, key, key_id, who, listing, revoke, after, again, audit = pg(body, *WORLD)
    assert r.status_code == 201 and key.startswith("sk_supra_")
    assert (who.tenant_id, who.user_id, who.membership_id, who.connection_id) == \
        (A, "tenant-a.svc", "tenant-a.svc.member", "tenant-a.svc.conn")
    row = next(k for k in listing.json()["api_keys"] if k["key_id"] == key_id)
    assert row["label"] == "ci" and row["created_by"] == "tenant-a.user" and row["is_active"] is True
    assert key not in listing.text and "key_hash" not in listing.text and '"api_key"' not in listing.text
    assert (revoke, after, again) == (204, None, 404)
    assert [(a["action"], a["target_id"]) for a in audit if a["action"].startswith("api_key")] == \
        [("api_key.issue", key_id), ("api_key.revoke", key_id)]
    assert key not in json.dumps([a["details"] for a in audit])


def test_an_administrator_cannot_mint_a_key_for_a_higher_role_but_can_for_an_equal_or_lower_one(pg):
    async def body(db):
        e = await _env(db)
        owner = await e.call(A, "POST", "/api-keys", {"membership_id": "tenant-a.boss.member", "connection_id": "tenant-a.boss.conn"})
        peer = await e.call(A, "POST", "/api-keys", {"membership_id": "tenant-a.peer.member", "connection_id": "tenant-a.peer.conn"})
        viewer = await e.call(A, "POST", "/api-keys", {"membership_id": "tenant-a.viewer.member", "connection_id": "tenant-a.viewer.conn"})
        by_owner = await e.call("owner-a", "POST", "/api-keys", {"membership_id": "tenant-a.boss.member", "connection_id": "tenant-a.boss.conn"})
        return owner.status_code, owner.json()["detail"], peer.status_code, viewer.status_code, by_owner.status_code
    assert pg(body, *WORLD) == (403, "role_exceeds_yours", 201, 201, 201)


@pytest.mark.parametrize("payload,status,reason", [
    ({"membership_id": "nope", "connection_id": "tenant-a.svc.conn"}, 404, "membership_not_found"),
    ({"membership_id": "tenant-a.svc.member", "connection_id": "nope"}, 404, "connection_not_found"),
    ({"membership_id": "tenant-a.svc.member", "connection_id": "tenant-a.peer.conn"}, 409, "connection_mismatch"),
    ({"membership_id": "tenant-b.member", "connection_id": "tenant-b.conn"}, 404, "membership_not_found"),   # another tenant
    ({**SVC, "label": "  "}, 422, "label_invalid"),
    ({**SVC, "tenant_id": "tenant-b"}, 422, None), ({**SVC, "user_id": "x"}, 422, None),                      # no identity fields
    ({"membership_id": "tenant-a.svc.member"}, 422, None),
])
def test_bad_or_hostile_key_requests_are_refused_and_create_nothing(pg, payload, status, reason):
    async def body(db):
        e = await _env(db)
        r = await e.call(A, "POST", "/api-keys", payload)
        async with db.transaction() as c:
            keys = await c.fetchval("SELECT count(*) FROM api_keys")
        return r, keys
    r, keys = pg(body, *WORLD)
    assert r.status_code == status and (reason is None or r.json()["detail"] == reason)
    assert keys == 6                                                       # only the six keys the test created


def test_inactive_identities_cannot_receive_credentials(pg):
    async def body(db):
        e = await _env(db)
        outs = []
        for sql in ("UPDATE memberships SET is_active = false WHERE membership_id = 'tenant-a.svc.member'",
                    "UPDATE memberships SET is_active = true, revoked_at = now() WHERE membership_id = 'tenant-a.svc.member'",
                    "UPDATE memberships SET revoked_at = NULL WHERE membership_id = 'tenant-a.svc.member'",
                    "UPDATE users SET status = 'suspended' WHERE user_id = 'tenant-a.svc'",
                    "UPDATE users SET status = 'active' WHERE user_id = 'tenant-a.svc'",
                    "UPDATE connections SET status = 'revoked' WHERE connection_id = 'tenant-a.svc.conn'",
                    "UPDATE connections SET status = 'active', expires_at = now() - interval '1 hour' WHERE connection_id = 'tenant-a.svc.conn'"):
            async with db.tenant_transaction(A) as c:
                await c.execute(sql)
            r = await e.call(A, "POST", "/api-keys", SVC)
            outs.append((r.status_code, r.json().get("detail")))
        return outs
    assert pg(body, *WORLD) == [(409, "membership_inactive"), (409, "membership_inactive"), (409, "user_inactive")
                                if False else (201, None), (409, "user_inactive"), (201, None),
                                (409, "connection_inactive"), (409, "connection_inactive")]


def test_one_tenants_administrator_sees_and_revokes_nothing_of_another_tenant(pg):
    async def body(db):
        e = await _env(db)
        a_key = (await e.call(A, "POST", "/api-keys", SVC)).json()
        b_list = await e.call(B, "GET", "/api-keys")
        b_revoke = await e.call(B, "DELETE", f"/api-keys/{a_key['key_id']}")
        still = await e.auth.authenticate(a_key["api_key"])
        return b_list.json()["api_keys"], b_revoke.status_code, still
    b_keys, b_revoke, still = pg(body, *WORLD)
    assert all(k["workspace_id"] == "tenant-b.ws" for k in b_keys) and b_revoke == 404 and still is not None


def test_a_change_and_its_audit_row_are_one_transaction(pg, database_url):
    async def body(db):
        e = await _env(db)
        owner = await asyncpg.connect(database_url)                 # DDL needs the schema owner, not the app role
        await owner.execute("CREATE FUNCTION boom() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit down'; END $$")
        await owner.execute("CREATE TRIGGER audit_down BEFORE INSERT ON admin_audit FOR EACH ROW EXECUTE FUNCTION boom()")
        actor = await e.app.state.admin.authorize(_principal(A))
        try:
            with pytest.raises(asyncpg.PostgresError):
                await e.app.state.admin.issue_api_key(actor, SVC["membership_id"], SVC["connection_id"])
            async with db.transaction() as c:
                keys = await c.fetchval("SELECT count(*) FROM api_keys WHERE tenant_id = 'tenant-a'")
        finally:
            await owner.execute("DROP TRIGGER audit_down ON admin_audit; DROP FUNCTION boom()")
            await owner.close()
        return keys
    assert pg(body, *WORLD) == 5                                            # the five setup keys of tenant-a only


# ---- endpoints and secrets ---------------------------------------------------------------------------------

async def _register(e, who, source, event_type, schema=None):
    return await e.call(who, "PUT", f"/event-schemas/{source}/{event_type}", {"schema": schema or {"type": "object"}})


def _webhook(e, endpoint, secret, body, path="webhooks/ghl", ts=None):
    raw = json.dumps(body).encode()
    return e.app, f"/api/v1/{path}/{endpoint}", raw, signature.sign(secret.encode(), ts or int(time.time()), raw)


async def _post(e, endpoint, secret, body, path="webhooks/ghl"):
    app, url, raw, header = _webhook(e, endpoint, secret, body, path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(url, content=raw, headers={"x-signature": header})


def test_an_issued_endpoint_receives_signed_events_through_the_whole_pipeline(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "ghl", "contact.created", {"type": "object", "required": ["name"]})
        r = await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "ghl", "label": "crm"})
        j = r.json()
        ok = await _post(e, j["endpoint_id"], j["signing_secret"], {"type": "contact.created", "id": "e1", "name": "Ana"})
        wrong = await _post(e, j["endpoint_id"], "whsec_wrong", {"type": "contact.created", "id": "e2", "name": "Ana"})
        return r, j, ok, wrong, await e.call(A, "GET", "/endpoints"), await _audit(db, A)
    r, j, ok, wrong, listing, audit = pg(body, *WORLD)
    assert r.status_code == 201 and j["url_path"] == f"/api/v1/webhooks/ghl/{j['endpoint_id']}"
    assert (ok.status_code, ok.json()["final_stage"]) == (200, "S11") and wrong.status_code == 401
    ep = listing.json()["endpoints"][0]
    assert (ep["source_system"], ep["status"], ep["label"], ep["user_id"]) == ("ghl", "active", "crm", "tenant-a.svc")
    assert j["signing_secret"] not in listing.text and "secret" not in json.dumps(list(ep))
    assert j["signing_secret"] not in json.dumps([a["details"] for a in audit], default=str)


def test_an_mcp_endpoint_is_issued_with_its_own_path_and_works(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "mcp", "mcp.tool_call", {"type": "object", "required": ["tool_name"]})
        j = (await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "mcp"})).json()
        ok = await _post(e, j["endpoint_id"], j["signing_secret"], {"tool_name": "fs.read"}, path="mcp")
        return j, ok
    j, ok = pg(body, *WORLD)
    assert j["url_path"] == f"/api/v1/mcp/{j['endpoint_id']}" and (ok.status_code, ok.json()["final_stage"]) == (200, "S11")


def test_rotation_keeps_the_old_secret_for_the_grace_period_and_revocation_kills_everything(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "ghl", "x")
        j = (await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "ghl"})).json()
        rot = await e.call(A, "POST", f"/endpoints/{j['endpoint_id']}/rotate", {"grace": "2 hours"})
        new = rot.json()["signing_secret"]
        old_ok = await _post(e, j["endpoint_id"], j["signing_secret"], {"type": "x", "id": "1"})
        new_ok = await _post(e, j["endpoint_id"], new, {"type": "x", "id": "2"})
        revoke = await e.call(A, "DELETE", f"/endpoints/{j['endpoint_id']}")
        old_after = await _post(e, j["endpoint_id"], j["signing_secret"], {"type": "x", "id": "3"})
        new_after = await _post(e, j["endpoint_id"], new, {"type": "x", "id": "4"})
        again = await e.call(A, "DELETE", f"/endpoints/{j['endpoint_id']}")
        return rot.status_code, new != j["signing_secret"], old_ok.status_code, new_ok.status_code, revoke.status_code, \
            old_after.status_code, new_after.status_code, again.status_code, await e.call(A, "GET", "/endpoints")
    rot, different, old_ok, new_ok, revoke, old_after, new_after, again, listing = pg(body, *WORLD)
    assert (rot, different, old_ok, new_ok, revoke, old_after, new_after, again) == (200, True, 200, 200, 204, 401, 401, 404)
    assert listing.json()["endpoints"] == []


@pytest.mark.parametrize("body,status", [({"grace": "forever"}, 422), ({"grace": "0 seconds"}, 422), ({"extra": 1}, 422)])
def test_a_bad_rotation_request_is_refused(pg, body, status):
    async def scenario(db):
        e = await _env(db)
        j = (await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "ghl"})).json()
        return (await e.call(A, "POST", f"/endpoints/{j['endpoint_id']}/rotate", body)).status_code
    assert pg(scenario, *WORLD) == status


def test_endpoint_administration_is_tenant_scoped_role_capped_and_validated(pg):
    async def body(db):
        e = await _env(db)
        j = (await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "ghl"})).json()
        other = [await e.call(B, "POST", f"/endpoints/{j['endpoint_id']}/rotate"),
                 await e.call(B, "DELETE", f"/endpoints/{j['endpoint_id']}")]
        b_list = await e.call(B, "GET", "/endpoints")
        owner = await e.call(A, "POST", "/endpoints", {"membership_id": "tenant-a.boss.member",
                                                       "connection_id": "tenant-a.boss.conn", "source_system": "ghl"})
        bad = await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "slack"})
        return [r.status_code for r in other], b_list.json()["endpoints"], owner.status_code, bad.status_code
    other, b_list, owner, bad = pg(body, *WORLD)
    assert other == [404, 404] and b_list == [] and owner == 403 and bad == 422


def test_endpoints_answer_503_without_the_key_encryption_key_but_other_admin_calls_still_work(pg):
    async def body(db):
        e = await _env(db, kek=False)
        endpoint = await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "ghl"})
        rotate = await e.call(A, "POST", "/endpoints/x/rotate")
        keys = await e.call(A, "POST", "/api-keys", SVC)
        return endpoint.status_code, rotate.status_code, keys.status_code
    assert pg(body, *WORLD) == (503, 503, 201)


# ---- event schemas -----------------------------------------------------------------------------------------

def test_schemas_are_versioned_listed_read_and_deactivated(pg):
    async def body(db):
        e = await _env(db)
        v1 = await _register(e, A, "api", "order.placed", {"type": "object"})
        v2 = await _register(e, A, "api", "order.placed", {"type": "object", "required": ["sku"]})
        await _register(e, A, "cron", "schedule.sync")
        listing = await e.call(A, "GET", "/event-schemas")
        one = await e.call(A, "GET", "/event-schemas/api/order.placed")
        drop2 = await e.call(A, "DELETE", "/event-schemas/api/order.placed/2")
        latest_after = await PostgresEventSchemas(db).latest(A, "api", "order.placed")
        drop_again = await e.call(A, "DELETE", "/event-schemas/api/order.placed/2")
        drop1 = await e.call(A, "DELETE", "/event-schemas/api/order.placed/1")
        gone = await PostgresEventSchemas(db).latest(A, "api", "order.placed")
        return v1, v2, listing, one, drop2.status_code, latest_after, drop_again.status_code, drop1.status_code, gone, \
            await e.call(A, "GET", "/event-schemas/api/never.registered"), await e.call(B, "GET", "/event-schemas")
    v1, v2, listing, one, drop2, latest_after, drop_again, drop1, gone, missing, b_listing = pg(body, *WORLD)
    assert (v1.status_code, v1.json()["version"], v2.json()["version"]) == (201, 1, 2)
    assert [(s["source_system"], s["event_type"], s["schema_version"]) for s in listing.json()["event_schemas"]] == \
        [("api", "order.placed", 2), ("cron", "schedule.sync", 1)]
    assert [v["schema_version"] for v in one.json()["versions"]] == [2, 1] and one.json()["versions"][0]["schema"]["required"] == ["sku"]
    assert (drop2, latest_after.version, drop_again, drop1, gone, missing.status_code) == (204, "1", 404, 204, None, 404)
    assert b_listing.json()["event_schemas"] == []


@pytest.mark.parametrize("path,body,status", [
    ("/event-schemas/api/t", {"schema": {"pattern": "^a+$"}}, 422),
    ("/event-schemas/api/t", {"schema": {"format": "email"}}, 422),
    ("/event-schemas/api/t", {"schema": "no"}, 422),
    ("/event-schemas/api/t", {"schema": {"type": "object"}, "extra": 1}, 422),
    ("/event-schemas/api/t", {"schema": {"enum": ["x" * 40000]}}, 413),
    ("/event-schemas/slack/t", {"schema": {"type": "object"}}, 422),
    ("/event-schemas/api/bad type", {"schema": {"type": "object"}}, 422),
])
def test_unusable_schemas_and_keys_are_refused_and_register_nothing(pg, path, body, status):
    async def scenario(db):
        e = await _env(db)
        r = await e.call(A, "PUT", path, body)
        return r.status_code, await e.call(A, "GET", "/event-schemas")
    code, listing = pg(scenario, *WORLD)
    assert code == status and listing.json()["event_schemas"] == []


def test_a_schema_registered_through_the_api_is_enforced_by_the_gateway(pg):
    async def body(db):
        e = await _env(db)
        key = e.keys[A]
        await _register(e, A, "api", "order.placed", {"type": "object", "required": ["sku"], "additionalProperties": False,
                                            "properties": {"sku": {"type": "string"}}})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=e.app), base_url="http://t") as c:
            headers = {"authorization": f"Bearer {key}"}
            ok = await c.post("/api/v1/events", headers=headers, json={"type": "order.placed", "payload": {"sku": "A"}})
            bad = await c.post("/api/v1/events", headers=headers, json={"type": "order.placed", "payload": {"sku": "A", "x": 1}})
            await e.call(A, "DELETE", "/event-schemas/api/order.placed/1")
            gone = await c.post("/api/v1/events", headers=headers, json={"type": "order.placed", "payload": {"sku": "A"}})
        return ok.json()["final_stage"], bad.status_code, gone.status_code, gone.json()["detail"]
    assert pg(body, *WORLD) == ("S11", 422, 422, "event_type_not_registered")


# ---- schedules ---------------------------------------------------------------------------------------------

INTERVAL = {"event_type": "schedule.sync", "kind": "interval", "interval_seconds": 3600,
            "anchor": "2026-01-01T00:00:00Z", "payload": {"job": "sync"}, **SVC}


def test_a_schedule_needs_a_registered_cron_schema_and_a_valid_payload_and_shape(pg):
    async def body(db):
        e = await _env(db)
        results = [(await e.call(A, "POST", "/schedules", INTERVAL)).json()]                    # unregistered
        await _register(e, A, "cron", "schedule.sync", {"type": "object", "required": ["job"]})
        results.append((await e.call(A, "POST", "/schedules", {**INTERVAL, "payload": {}})).json())
        results.append((await e.call(A, "POST", "/schedules", {**INTERVAL, "interval_seconds": 30})).json())
        results.append((await e.call(A, "POST", "/schedules", {**INTERVAL, "kind": "hourly"})).json())
        results.append((await e.call(A, "POST", "/schedules", {**INTERVAL, "payload": {"job": "x" * 20000}})).json())
        results.append((await e.call(A, "POST", "/schedules", {**INTERVAL, "tenant_id": B})).json())
        return results, (await e.call(A, "GET", "/schedules")).json()
    results, listing = pg(body, *WORLD)
    details = [r["detail"] if isinstance(r["detail"], str) else "validation" for r in results]
    assert details[0] == "event_type_not_registered" and details[1] == "payload_invalid"
    assert details[2].startswith("schedule_invalid") and details[3].startswith("schedule_invalid")
    assert details[4] == "payload_too_large" and details[5] == "validation"
    assert listing["schedules"] == []


def test_a_created_schedule_runs_as_its_identity_and_fires_through_the_pipeline(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "cron", "schedule.sync")
        r = await e.call(A, "POST", "/schedules", {**INTERVAL, "label": "nightly"})
        listing = await e.call(A, "GET", "/schedules")
        store = PostgresScheduleStore(db)
        schemas = PostgresEventSchemas(db)
        gateway = EventGateway(None, PostgresEventLog(db), schemas)
        pipeline = build_runner(db, EventModel())
        now = await store.now()
        out = await EventScheduler(store, gateway, lambda x: run_received_event(pipeline, gateway, x)).tick(now + timedelta(hours=2))
        async with db.tenant_transaction(A) as c:
            events = [dict(x) for x in await c.fetch("SELECT * FROM event_log")]
        return r, listing, out, events
    r, listing, out, events = pg(body, *WORLD)
    sid = r.json()["schedule_id"]
    row = listing.json()["schedules"][0]
    assert r.status_code == 201 and (row["schedule_id"], row["user_id"], row["label"], row["created_by"], row["is_active"]) == \
        (sid, "tenant-a.svc", "nightly", "tenant-a.user", True)
    assert [f.outcome for f in out] == ["ran"] and events[0]["auth_principal"] == sid and events[0]["source"] == "schedule"


def test_deactivating_a_schedule_stops_it_and_other_tenants_cannot_touch_it(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "cron", "schedule.sync")
        sid = (await e.call(A, "POST", "/schedules", INTERVAL)).json()["schedule_id"]
        other = await e.call(B, "DELETE", f"/schedules/{sid}")
        b_list = await e.call(B, "GET", "/schedules")
        drop = await e.call(A, "DELETE", f"/schedules/{sid}")
        again = await e.call(A, "DELETE", f"/schedules/{sid}")
        active = await PostgresScheduleStore(db).active()
        second = (await e.call(A, "POST", "/schedules", INTERVAL)).json()["schedule_id"]
        return sid, second, other.status_code, b_list.json()["schedules"], drop.status_code, again.status_code, active
    sid, second, other, b_list, drop, again, active = pg(body, *WORLD)
    assert (other, b_list, drop, again, active) == (404, [], 204, 404, []) and sid != second


def test_a_schedule_cannot_run_as_a_higher_role_than_its_creator(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "cron", "schedule.sync")
        r = await e.call(A, "POST", "/schedules", {**INTERVAL, "membership_id": "tenant-a.boss.member",
                                                   "connection_id": "tenant-a.boss.conn"})
        return r.status_code, r.json()["detail"]
    assert pg(body, *WORLD) == (403, "role_exceeds_yours")


# ---- audit -------------------------------------------------------------------------------------------------

def test_every_administrative_action_is_audited_append_only_and_tenant_scoped(pg):
    async def body(db):
        e = await _env(db)
        await _register(e, A, "api", "t")
        k = (await e.call(A, "POST", "/api-keys", SVC)).json()
        ep = (await e.call(A, "POST", "/endpoints", {**SVC, "source_system": "ghl"})).json()
        await e.call(A, "POST", f"/endpoints/{ep['endpoint_id']}/rotate")
        await e.call(A, "DELETE", f"/endpoints/{ep['endpoint_id']}")
        await e.call(A, "DELETE", f"/api-keys/{k['key_id']}")
        await e.call(A, "DELETE", "/event-schemas/api/t/1")
        trail = await e.call(A, "GET", "/audit?limit=50")
        b_trail = await e.call(B, "GET", "/audit")
        member = await e.call("member-a", "GET", "/audit")
        errors = []
        for sql in ("UPDATE admin_audit SET action = 'x'", "DELETE FROM admin_audit"):
            try:
                async with db.tenant_transaction(A) as c:
                    await c.execute(sql)
                errors.append(None)
            except asyncpg.PostgresError as exc:
                errors.append(str(exc))
        return trail, b_trail, member.status_code, errors, k, ep
    trail, b_trail, member, errors, k, ep = pg(body, *WORLD)
    actions = [a["action"] for a in reversed(trail.json()["audit"])]
    assert actions == ["event_schema.put", "api_key.issue", "endpoint.issue", "endpoint.rotate", "endpoint.revoke",
                       "api_key.revoke", "event_schema.deactivate"]
    assert all(a["actor_user_id"] == "tenant-a.user" for a in trail.json()["audit"])
    assert b_trail.json()["audit"] == [] and member == 403
    assert "append-only" in (errors[0] or "") and errors[1] is not None          # UPDATE: trigger; DELETE: no privilege
    text = trail.text
    assert k["api_key"] not in text and ep["signing_secret"] not in text and "whsec_" not in text and "sk_supra_" not in text
