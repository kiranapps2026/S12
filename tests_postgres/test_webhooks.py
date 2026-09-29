"""Event gateway over real PostgreSQL: encrypted signing secrets, rotation, dedup, RLS, HTTP."""
from __future__ import annotations

import base64
import json
import os
import time

import asyncpg
import httpx
import pytest

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.event_log import PostgresEventLog
from adapters.postgres.webhook_credentials import Kek, PostgresWebhookCredentials
from app import create_app
from bootstrap import build_runner
from contracts.errors import DependencyUnavailable
from contracts.principal import Principal
from engine.gateway import signature
from engine.gateway.webhook import WebhookGateway
from tests_postgres.test_end_to_end import EchoIntentModel

A, B = "tenant-a", "tenant-b"
KEK = Kek(bytes(range(32)), 1)


def _principal(tenant):
    return Principal(tenant, f"{tenant}.ws", f"{tenant}.user", f"{tenant}.member", f"{tenant}.conn", "")


def _post(pg, body, *, tenant=A, source="ghl", setup=None, mutate=None, sign_with=None, ts=None,
          endpoint_from=None, extra_sql=()):
    """One webhook through HTTP. `mutate(store, endpoint, secret)` may rotate etc. first."""
    async def scenario(db):
        store = PostgresWebhookCredentials(db, KEK)
        endpoints = {t: await store.issue(_principal(t), "ghl") for t in (A, B)}
        endpoint, secret = endpoints[endpoint_from or tenant]
        if mutate:
            secret = await mutate(store, endpoint, secret) or secret
        gateway = WebhookGateway(store, PostgresEventLog(db))
        app = create_app(pipeline=build_runner(db, EchoIntentModel()), webhooks=gateway)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        header = signature.sign((sign_with or secret).encode(), ts or int(time.time()), raw)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            first = await client.post(f"/api/v1/webhooks/{source}/{endpoint}", content=raw,
                                      headers={"x-signature": header})
            second = await client.post(f"/api/v1/webhooks/{source}/{endpoint}", content=raw,
                                       headers={"x-signature": header})
        rows = {}
        for t in (A, B):
            async with db.tenant_transaction(t) as c:
                rows[t] = [dict(r) for r in await c.fetch(
                    "SELECT event_id, tenant_id, event_type, processing_status, payload FROM event_log")]
        return first, second, rows, endpoints
    return pg(scenario_wrap(scenario), *extra_sql)


def scenario_wrap(scenario):
    async def body(db):
        return await scenario(db)
    return body


def test_a_signed_event_runs_the_pipeline_as_the_credentials_identity(pg):
    first, second, rows, _ = _post(pg, {"type": "x", "id": "e1"})
    # the EchoIntentModel does not recognise the event text: unknown intent -> CLARIFY at S2,
    # but it proves the run went through S0..S2 for the credential's tenant
    assert first.status_code == 200 and first.json()["final_stage"] == "S2", first.text
    assert first.json()["reason"] == "intent_unclear"
    assert [r["processing_status"] for r in rows[A]] == ["processed"] and rows[B] == []
    assert json.loads(rows[A][0]["payload"]) == {"type": "x", "id": "e1"}


def test_a_repeat_delivery_is_acknowledged_and_not_run_again(pg):
    first, second, rows, _ = _post(pg, {"type": "x", "id": "e1"})
    assert second.status_code == 200 and second.json()["reason"] == "duplicate_event"
    assert len(rows[A]) == 1


def test_an_event_can_drive_a_capability_end_to_end(pg):
    """A model that recognises the event text (like a real one would) reaches S11."""
    class EventModel:
        async def complete(self, text, intents, feedback):
            from contracts.intent_model import IntentCompletion
            return IntentCompletion(text=json.dumps(
                {"intent": "contact.list", "confidence": 0.9, "parameters": {}}), model="m", total_tokens=1)

    async def body(db):
        store = PostgresWebhookCredentials(db, KEK)
        endpoint, secret = await store.issue(_principal(A), "ghl")
        app = create_app(pipeline=build_runner(db, EventModel()),
                         webhooks=WebhookGateway(store, PostgresEventLog(db)))
        raw = json.dumps({"type": "contact.created", "id": "e9", "tenant_id": B}).encode()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.post(f"/api/v1/webhooks/ghl/{endpoint}", content=raw, headers={
                "x-signature": signature.sign(secret.encode(), int(time.time()), raw)})
        async with db.tenant_transaction(A) as c:
            events = [dict(x) for x in await c.fetch(
                "SELECT stage, status FROM pipeline_events ORDER BY event_id")]
            task = None
        return r, events
    r, events = pg(body)
    assert (r.json()["status"], r.json()["final_stage"]) == ("NORMAL", "S11"), r.text
    assert [e["stage"] for e in events][-1] == "S11"


def test_wrong_secret_wrong_endpoint_and_other_tenants_secret_are_all_401(pg):
    for kwargs in ({"sign_with": "whsec_wrong"}, {"source": "stripe"}):
        first, _, rows, _ = _post(pg, {"type": "x", "id": "e1"}, **kwargs)
        assert first.status_code == 401 and first.json() == {"detail": "unauthenticated"}, kwargs
        assert rows[A] == rows[B] == []


def test_another_tenants_secret_does_not_work_on_this_tenants_endpoint(pg):
    async def scenario(db):
        store = PostgresWebhookCredentials(db, KEK)
        ep_a, _ = await store.issue(_principal(A), "ghl")
        _, secret_b = await store.issue(_principal(B), "ghl")
        app = create_app(pipeline=build_runner(db, EchoIntentModel()),
                         webhooks=WebhookGateway(store, PostgresEventLog(db)))
        raw = b'{"type":"x","id":"1"}'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.post(f"/api/v1/webhooks/ghl/{ep_a}", content=raw, headers={
                "x-signature": signature.sign(secret_b.encode(), int(time.time()), raw)})
    assert pg(scenario).status_code == 401


def test_stale_timestamps_are_400_and_nothing_is_stored(pg):
    first, _, rows, _ = _post(pg, {"type": "x", "id": "e1"}, ts=int(time.time()) - 1000)
    assert first.status_code == 400 and first.json()["detail"] == "stale_timestamp"
    assert rows[A] == []


def test_the_body_cannot_choose_the_tenant(pg):
    first, _, rows, _ = _post(pg, {"type": "x", "id": "e1", "tenant_id": B, "workspace_id": "tenant-b.ws"})
    assert len(rows[A]) == 1 and rows[B] == []


def test_secrets_are_stored_encrypted_and_only_the_right_kek_opens_them(pg):
    async def body(db):
        store = PostgresWebhookCredentials(db, KEK)
        endpoint, secret = await store.issue(_principal(A), "ghl")
        async with db.transaction() as c:
            row = dict(await c.fetchrow("SELECT * FROM webhook_credentials WHERE endpoint_id = $1", endpoint))
        stored = b"".join(v for v in row.values() if isinstance(v, (bytes, bytearray, memoryview)))
        opened = await store.endpoint(endpoint, "ghl")
        wrong = PostgresWebhookCredentials(db, Kek(bytes(reversed(range(32))), 1))
        try:
            await wrong.endpoint(endpoint, "ghl")
            wrong_result = "opened"
        except DependencyUnavailable:
            wrong_result = "refused"
        return secret, stored, opened, wrong_result, row
    secret, stored, opened, wrong_result, row = pg(body)
    assert secret.encode() not in stored and secret not in json.dumps(row, default=str)
    assert bytes(opened.secrets[0].value) == secret.encode()
    assert wrong_result == "refused" and row["kek_version"] == 1


def test_rotation_keeps_the_old_secret_for_the_grace_period_then_retires_it(pg):
    async def body(db):
        store = PostgresWebhookCredentials(db, KEK)
        endpoint, old = await store.issue(_principal(A), "ghl")
        new = await store.rotate(endpoint, "ghl")
        during = [(s.status, bytes(s.value)) for s in (await store.endpoint(endpoint, "ghl")).secrets]
        async with db.transaction() as c:
            await c.execute("UPDATE webhook_credentials SET retiring_until = now() - interval '1 second'"
                            " WHERE status = 'retiring'")
        after = [(s.status, bytes(s.value)) for s in (await store.endpoint(endpoint, "ghl")).secrets]
        third = await store.rotate(endpoint, "ghl")
        async with db.transaction() as c:
            states = sorted(r["status"] for r in await c.fetch(
                "SELECT status FROM webhook_credentials WHERE endpoint_id = $1", endpoint))
        return old, new, third, during, after, states
    old, new, third, during, after, states = pg(body)
    assert during == [("active", new.encode()), ("retiring", old.encode())]
    assert after == [("active", new.encode())]
    assert states == ["active", "retired", "retiring"] and third != new


def test_http_rotation_old_secret_works_in_grace_and_fails_after(pg):
    async def rotate(store, endpoint, secret):
        await store.rotate(endpoint, "ghl")
        return None                       # keep signing with the OLD secret
    first, _, rows, _ = _post(pg, {"type": "x", "id": "e1"}, mutate=rotate)
    assert first.status_code == 200 and len(rows[A]) == 1

    async def rotate_and_expire(store, endpoint, secret):
        await store.rotate(endpoint, "ghl")
        async with store._db.transaction() as c:
            await c.execute("UPDATE webhook_credentials SET retiring_until = now() - interval '1 second'"
                            " WHERE status = 'retiring'")
    first, _, rows, _ = _post(pg, {"type": "x", "id": "e2"}, mutate=rotate_and_expire)
    assert first.status_code == 401


def test_expired_and_unknown_credentials_are_refused(pg):
    async def body(db):
        store = PostgresWebhookCredentials(db, KEK)
        endpoint, _ = await store.issue(_principal(A), "ghl")
        async with db.transaction() as c:
            await c.execute("UPDATE webhook_credentials SET expires_at = now() - interval '1 second'")
        return await store.endpoint(endpoint, "ghl"), await store.endpoint("nope", "ghl")
    assert pg(body) == (None, None)


def test_the_event_log_is_isolated_per_tenant_and_dedups_per_tenant(pg):
    async def body(db):
        store = PostgresWebhookCredentials(db, KEK)
        log = PostgresEventLog(db)
        gw = WebhookGateway(store, log)
        got = []
        for tenant in (A, B, A):
            ep, secret = await store.issue(_principal(tenant), "ghl") if tenant != A or not got else (ep_a, sec_a)
            if tenant == A and not got:
                ep_a, sec_a = ep, secret
            raw = b'{"type":"x","id":"same"}'
            got.append((await gw.receive("ghl", ep, raw, signature.sign(secret.encode(), int(time.time()), raw))).duplicate)
        async with db.tenant_transaction(B) as c:
            b_rows = await c.fetchval("SELECT count(*) FROM event_log")
        return got, b_rows
    got, b_rows = pg(body)
    assert got == [False, False, True] and b_rows == 1


def test_a_kek_must_be_32_bytes_and_never_prints():
    with pytest.raises(ValueError):
        Kek(b"short")
    with pytest.raises(ValueError, match="base64"):
        Kek.from_base64("not base64!!")
    assert "0" not in repr(Kek.from_base64(base64.b64encode(bytes(32)).decode(), 3)).replace("version=3", "")


def test_the_app_starts_without_a_kek_and_webhooks_answer_503(pg):
    async def body(db):
        app = create_app(pipeline=build_runner(db, EchoIntentModel()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.post("/api/v1/webhooks/ghl/x", content=b"{}", headers={"x-signature": "t=1,v1=" + "a" * 64})
    r = pg(body)
    assert r.status_code == 503 and r.json()["detail"] == "webhooks_unavailable"
