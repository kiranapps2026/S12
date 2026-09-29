"""Event Gateway: signing-secret authentication, replay window, tenant from the credential."""
import asyncio
import json

import pytest

from contracts.principal import Principal
from contracts.webhook_credentials import SigningSecret, StoredEvent, WebhookEndpoint
from engine.gateway import signature
from engine.gateway.webhook import MAX_BODY_BYTES, WebhookGateway, WebhookRejected, event_message

NOW = 1_800_000_000
SECRET = b"whsec_test_secret"
PRINCIPAL = Principal("tenant-1", "ws-1", "user-1", "member-1", "conn-1", "")


class Store:
    def __init__(self, secrets=None, principal=PRINCIPAL):
        self.secrets = secrets if secrets is not None else [("cred-1", "active", SECRET)]
        self.principal = principal
        self.verified = []
        self.asked = []

    async def endpoint(self, endpoint_id, source_system):
        self.asked.append((endpoint_id, source_system))
        if endpoint_id != "ep-1" or source_system != "ghl":
            return None
        return WebhookEndpoint(self.principal, tuple(
            SigningSecret(c, st, bytearray(v)) for c, st, v in self.secrets))

    async def mark_verified(self, credential_id):
        self.verified.append(credential_id)


class Log:
    def __init__(self):
        self.rows = {}
        self.finished = []

    async def record(self, *, envelope, principal, idempotency_key, raw_body):
        key = (envelope.tenant_id, idempotency_key)
        duplicate = key in self.rows
        self.rows.setdefault(key, (envelope, raw_body))
        return StoredEvent(duplicate)

    async def finish(self, tenant_id, event_id, status):
        self.finished.append((tenant_id, event_id, status))


def _receive(body, header="AUTO", *, store=None, log=None, now=NOW, source="ghl", endpoint="ep-1", ts=NOW,
             secret=SECRET):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    if header == "AUTO":
        header = signature.sign(secret, ts, body)
    gateway = WebhookGateway(store or Store(), log or Log(), clock=lambda: now)
    return asyncio.run(gateway.receive(source, endpoint, body, header))


def _reason(**kw):
    with pytest.raises(WebhookRejected) as caught:
        _receive(**kw)
    return caught.value.status, caught.value.reason


EVENT = {"type": "contact.created", "id": "evt-1", "data": {"name": "Ana"}}


def test_a_correctly_signed_event_becomes_an_envelope_for_the_credentials_identity():
    store = Store()
    got = _receive(EVENT, store=store)
    e = got.envelope
    assert (e.tenant_id, e.workspace_id, e.type, e.source, e.source_system) == \
        ("tenant-1", "ws-1", "contact.created", "webhook", "ghl")
    assert got.principal == PRINCIPAL and not got.duplicate
    assert e.payload_ref == f"pg:event_log.{e.event_id}" and len(e.payload_checksum) == 64
    assert store.verified == ["cred-1"]


def test_tenant_and_user_in_the_payload_are_ignored():
    hostile = {**EVENT, "tenant_id": "tenant-2", "workspace_id": "ws-2", "user_id": "admin",
               "data": {"tenant_id": "tenant-2"}}
    got = _receive(hostile)
    assert (got.envelope.tenant_id, got.envelope.workspace_id, got.principal.user_id) == \
        ("tenant-1", "ws-1", "user-1")


def test_event_and_trace_identifiers_are_generated_not_taken_from_the_payload():
    got = _receive({**EVENT, "event_id": "mine", "correlation_id": "mine", "trace_id": "mine"})
    assert "mine" not in (got.envelope.event_id, got.envelope.correlation_id)


@pytest.mark.parametrize("header", [None, "", "garbage", "t=1,v1=zz", f"t={NOW}", f"v1={'a' * 64}",
                                    f"t={NOW},v1={'a' * 64}", f"t={NOW},v1={'A' * 64}"])
def test_missing_malformed_or_wrong_signatures_are_401(header):
    assert _reason(body=EVENT, header=header) == (401, "unauthenticated")


def test_a_signature_made_with_another_secret_or_over_another_body_is_401():
    assert _reason(body=EVENT, secret=b"other") == (401, "unauthenticated")
    tampered = signature.sign(SECRET, NOW, json.dumps(EVENT).encode())
    assert _reason(body={**EVENT, "data": {"name": "Eve"}}, header=tampered) == (401, "unauthenticated")


def test_the_timestamp_is_part_of_the_signature():
    body = json.dumps(EVENT).encode()
    good = signature.sign(SECRET, NOW, body)
    shifted = good.replace(f"t={NOW}", f"t={NOW + 1}")
    assert _reason(body=body, header=shifted) == (401, "unauthenticated")


def test_unknown_endpoint_wrong_source_and_bad_signature_look_identical():
    a = _reason(body=EVENT, endpoint="nope")
    b = _reason(body=EVENT, source="stripe")
    c = _reason(body=EVENT, source="not-a-source")
    d = _reason(body=EVENT, secret=b"wrong")
    assert a == b == c == d == (401, "unauthenticated")


def test_the_replay_window_is_five_minutes_both_ways():
    assert _receive(EVENT, ts=NOW - 300).envelope
    assert _receive(EVENT, ts=NOW + 300).envelope
    assert _reason(body=EVENT, ts=NOW - 301) == (400, "stale_timestamp")
    assert _reason(body=EVENT, ts=NOW + 301) == (400, "stale_timestamp")


def test_a_stale_timestamp_is_only_reported_after_the_signature_is_proven():
    assert _reason(body=EVENT, ts=NOW - 10_000, secret=b"wrong") == (401, "unauthenticated")


def test_a_retiring_secret_still_verifies_during_its_grace_period():
    store = Store([("cred-2", "active", b"new"), ("cred-1", "retiring", SECRET)])
    assert _receive(EVENT, store=store).envelope
    assert store.verified == ["cred-1"]
    assert _reason(body=EVENT, store=Store([("cred-2", "active", b"new")])) == (401, "unauthenticated")


def test_secrets_are_wiped_after_verification():
    seen = []

    class Spy(Store):
        async def endpoint(self, endpoint_id, source_system):
            endpoint = await super().endpoint(endpoint_id, source_system)
            seen.extend(s.value for s in endpoint.secrets)
            return endpoint
    _receive(EVENT, store=Spy())
    assert seen and all(set(v) == {0} for v in seen)


def test_the_body_must_be_a_json_object_with_a_sane_type():
    for body in (b"not json", b"[1,2]", b'"x"', b"null"):
        assert _reason(body=body) == (400, "invalid_json")
    for bad in ({}, {"type": 5}, {"type": ""}, {"type": "a b"}, {"type": "x" * 65}, {"type": "a\nb"}):
        assert _reason(body=bad) == (400, "invalid_event_type"), bad


def test_oversize_bodies_are_refused_before_anything_is_looked_up():
    store = Store()
    body = b"x" * (MAX_BODY_BYTES + 1)
    with pytest.raises(WebhookRejected) as caught:
        _receive(body, store=store)
    assert caught.value.status == 413 and store.asked == []


def test_a_repeat_delivery_with_the_same_source_event_id_is_a_duplicate():
    log = Log()
    first = _receive(EVENT, log=log)
    second = _receive(EVENT, log=log, now=NOW + 60, ts=NOW + 60)    # a provider retry: new timestamp
    assert (first.duplicate, second.duplicate) == (False, True)
    assert _receive({**EVENT, "id": "evt-2"}, log=log).duplicate is False


def test_without_a_source_id_an_exact_replay_is_a_duplicate_but_a_new_signature_is_not():
    log = Log()
    body = {"type": "ping"}
    assert _receive(body, log=log).duplicate is False
    assert _receive(body, log=log).duplicate is True
    assert _receive(body, log=log, now=NOW + 5, ts=NOW + 5).duplicate is False


def test_the_same_event_id_in_two_tenants_is_not_a_duplicate():
    log = Log()
    other = Principal("tenant-2", "ws-2", "user-2", "m", "c", "")
    assert _receive(EVENT, log=log).duplicate is False
    assert _receive(EVENT, log=log, store=Store(principal=other)).duplicate is False


def test_the_event_text_carries_type_source_and_payload():
    text = event_message(_receive(EVENT))
    assert text == 'Event contact.created from ghl: {"type":"contact.created","id":"evt-1","data":{"name":"Ana"}}'


def test_s0_uses_the_event_id_as_task_id_and_s2_keeps_it():
    from engine.stages.s0_entry.handler import handle as s0
    from tests.fixtures.pipeline import make_entry, run_pipeline
    from tests.fixtures.scenarios import make_scenario
    entry = make_entry({"message": "contact.list"})
    from dataclasses import replace
    state = asyncio.run(s0(replace(entry, event_id="evt-42")))
    assert state.execution_context.task_id == "evt-42"
    result = run_pipeline({"message": "contact.list", "connection_id": "conn-1"}, make_scenario())
    assert result.final_state.execution_context.task_id            # a normal run still gets one at S2
