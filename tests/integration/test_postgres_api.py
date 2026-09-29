"""API keys on PostgreSQL, and the HTTP API end to end on the real adapters."""
from __future__ import annotations

import httpx

from supragents.adapters.postgres.api_keys import PostgresApiKeyAuthenticator, hash_key
from supragents.api.app import create_app
from supragents.bootstrap import build_runner
from supragents.ports.authentication import Principal
from tests.fakes.ports import ScriptedIntentModel, intent_json

PRINCIPAL = Principal("tenant-a", "tenant-a.ws", "tenant-a.user", "tenant-a.member", "tenant-a.conn", "tenant-a.ws/*")


def test_issued_key_authenticates_and_only_its_hash_is_stored(pg):
    async def body(db):
        authenticator = PostgresApiKeyAuthenticator(db)
        key = await authenticator.issue(PRINCIPAL)
        async with db.transaction() as connection:
            stored = await connection.fetchval("SELECT key_hash FROM api_keys")
        return key, stored, await authenticator.authenticate(key), await authenticator.authenticate(key + "x")
    key, stored, found, wrong = pg(body)
    assert key.startswith("sk_supra_") and stored == hash_key(key) and key not in stored
    assert found == PRINCIPAL and wrong is None


def test_http_flow_on_postgres(pg):
    async def body(db):
        key = await PostgresApiKeyAuthenticator(db).issue(PRINCIPAL)
        model = ScriptedIntentModel(intent_json("contact.delete", id="c-1"))
        app = create_app(build_runner(db, model), PostgresApiKeyAuthenticator(db))
        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
            confirm = (await client.post("/v1/runs", headers=headers,
                                         json={"text": "delete contact c-1", "conversation_id": "c"})).json()
            done = (await client.post(f"/v1/confirmations/{confirm['data']['confirmation_id']}",
                                      json={"approved": True}, headers=headers)).json()
        return confirm, done
    confirm, done = pg(body)
    assert confirm["status"] == "confirm" and done["status"] == "ok"
    assert done["data"]["manifest"]["tenant_id"] == "tenant-a"
