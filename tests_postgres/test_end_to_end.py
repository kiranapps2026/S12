"""HTTP -> API key -> real runner -> real PostgreSQL adapters (RLS enforced), no fixtures
standing in for a dependency except the LLM (whose port has no production adapter yet)."""
from __future__ import annotations

import asyncio

import httpx

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from app import create_app
from contracts.principal import Principal
from bootstrap import build_runner


class EchoIntentModel:
    """Test IntentModel: the message text IS the intent name (e.g. "contact.list"); if the
    registry does not offer it, the answer is "unknown" like a real constrained model."""

    async def complete(self, text, intents, feedback):
        import json
        from contracts.intent_model import IntentCompletion
        intent = text if text in intents else "unknown"
        return IntentCompletion(
            text=json.dumps({"intent": intent, "confidence": 0.95, "parameters": {}}),
            model="echo", total_tokens=1)


def _principal(tenant):
    return Principal(tenant, f"{tenant}.ws", f"{tenant}.user", f"{tenant}.member", f"{tenant}.conn", "")


def _scenario(pg, intent, *setup_sql, tenant="tenant-a", key_of=None, headers=None):
    """Run one HTTP request; returns (status_code, json, pending_confirmation_rows)."""
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        keys = {t: await auth.issue(_principal(t)) for t in ("tenant-a", "tenant-b")}
        runner = build_runner(db, EchoIntentModel())
        app = create_app(pipeline=runner, authenticator=auth)
        h = headers if headers is not None else {"authorization": f"Bearer {keys[key_of or tenant]}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.post("/api/v1/execute", json={"input_data": {"message": intent}}, headers=h)
        rows = []
        for t in ("tenant-a", "tenant-b"):      # what was persisted, per tenant (RLS applies)
            async with db.tenant_transaction(t) as c:
                rows += [dict(x) for x in await c.fetch("SELECT tenant_id, status FROM pending_confirmations")]
        return r.status_code, r.json(), rows
    return pg(body, *setup_sql)


def test_read_run_completes_with_registry_versions(pg):
    code, j, _ = _scenario(pg, "contact.list")
    assert code == 200 and (j["status"], j["final_stage"]) == ("NORMAL", "S11"), j
    assert j["execution_id"] and j["trace_id"]


def test_high_impact_delete_persists_a_pending_confirmation(pg):
    code, j, rows = _scenario(pg, "contact.delete",
                              "UPDATE kernel_ops SET cost = 6 WHERE kernel_op_id = 'crm.contact_delete'")
    assert (j["status"], j["final_stage"], j["reason"]) == ("CLARIFY", "S10", "confirmation_required"), j
    assert j["confirmation_id"]
    assert rows == [{"tenant_id": "tenant-a", "status": "pending"}]


def test_kill_switch_denies_at_s8_and_takes_effect_on_the_next_run(pg):
    _, j, _ = _scenario(pg, "contact.list", "UPDATE tenants SET kill_switch_engaged = true WHERE tenant_id = 'tenant-a'")
    assert (j["status"], j["final_stage"], j["reason"]) == ("DENY", "S8", "kill_switch")


def test_system_kill_switch(pg):
    _, j, _ = _scenario(pg, "contact.list", "UPDATE system_settings SET kill_switch_engaged = true")
    assert (j["final_stage"], j["reason"]) == ("S8", "kill_switch")


def test_suspended_tenant_is_denied(pg):
    _, j, _ = _scenario(pg, "contact.list", "UPDATE tenants SET status = 'suspended' WHERE tenant_id = 'tenant-a'")
    assert (j["status"], j["final_stage"], j["reason"]) == ("DENY", "S8", "tenant_active_inactive")


def test_missing_grant_is_denied(pg):
    _, j, _ = _scenario(pg, "contact.list", "DELETE FROM capability_grants WHERE tenant_id = 'tenant-a'")
    assert (j["final_stage"], j["reason"]) == ("S8", "capability_granted_denied")


def test_mutation_above_the_tenant_ceiling_is_denied(pg):
    _, j, _ = _scenario(pg, "contact.delete", "UPDATE tenants SET max_mutation = 'W' WHERE tenant_id = 'tenant-a'")
    assert (j["final_stage"], j["reason"]) == ("S8", "mutation_safety_denied")


def test_expired_connection_is_denied(pg):
    _, j, _ = _scenario(pg, "contact.list",
                        "UPDATE connections SET expires_at = now() - interval '1 minute' WHERE tenant_id = 'tenant-a'")
    assert (j["final_stage"], j["reason"]) == ("S8", "connection_active_expired")


def test_risk_above_threshold_is_denied_at_s7(pg):
    _, j, _ = _scenario(pg, "contact.list", "UPDATE kernel_ops SET risk_floor = 0.99 WHERE kernel_op_id = 'crm.contact_list'")
    assert (j["final_stage"], j["reason"]) == ("S7", "risk_above_threshold")


def test_unknown_intent_asks_for_clarification(pg):
    _, j, _ = _scenario(pg, "contact.teleport")
    assert (j["status"], j["final_stage"], j["reason"]) == ("CLARIFY", "S2", "intent_unclear")


def test_intent_of_a_disabled_capability_is_not_offered_to_the_model(pg):
    _, j, _ = _scenario(pg, "contact.list", "UPDATE capabilities SET truth_state = 'DRAFT' WHERE intent = 'contact.list'")
    assert (j["final_stage"], j["reason"]) == ("S2", "intent_unclear")


def test_bad_or_missing_key_is_401(pg):
    assert _scenario(pg, "contact.list", headers={"authorization": "Bearer sk_supra_nope"})[0] == 401
    assert _scenario(pg, "contact.list", headers={})[0] == 401


def test_database_outage_fails_closed(pg):
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        key = await auth.issue(_principal("tenant-a"))
        runner = build_runner(db, EchoIntentModel())
        app = create_app(pipeline=runner, authenticator=auth)
        await db.close()                                   # the database goes away
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.post("/api/v1/execute", json={"input_data": {"message": "contact.list"}},
                                     headers={"authorization": f"Bearer {key}"})
    r = pg(body)
    assert r.status_code == 503 and r.json()["detail"] == "authentication_unavailable"


def test_pool_failure_after_authentication_never_runs_the_pipeline(pg):
    """The database goes away after authentication: S0's event cannot be recorded, so the run
    ends in ERROR at S0 and nothing after S0 ran."""
    async def body(db):
        runner = build_runner(db, EchoIntentModel())
        from tests.fixtures.pipeline import make_entry
        entry = make_entry({"message": "contact.list", "tenant_id": "tenant-a", "workspace_id": "tenant-a.ws",
                            "connection_id": "tenant-a.conn"})
        await db.close()
        return await runner.run(entry)
    result = pg(body)
    assert (result.status.value, result.reason, result.stages_run) == (
        "ERROR", "ledger_unavailable", ("S0",))


# ---- confirmation reply over HTTP, real database ----------------------------------------------

OTHER_USER_SQL = (
    "INSERT INTO users (user_id, tenant_id) VALUES ('tenant-a.other', 'tenant-a')",
    "INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id)"
    " VALUES ('tenant-a.other.m', 'tenant-a', 'tenant-a.other', 'tenant-a.ws')",
    "INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id)"
    " VALUES ('tenant-a.other.c', 'tenant-a', 'tenant-a.other', 'tenant-a.ws')",
    "UPDATE kernel_ops SET cost = 6 WHERE kernel_op_id = 'crm.contact_delete'",
)


def _flow(pg, steps, *setup_sql):
    """steps: async fn(client, keys, db, make_client) -> anything. Runs against the real DB."""
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        keys = {t: await auth.issue(_principal(t)) for t in ("tenant-a", "tenant-b")}
        keys["other"] = await auth.issue(Principal("tenant-a", "tenant-a.ws", "tenant-a.other",
                                                   "tenant-a.other.m", "tenant-a.other.c", ""))

        def make_client():          # a fresh app/runner: nothing carried in memory ("restart")
            app = create_app(pipeline=build_runner(db, EchoIntentModel()), authenticator=auth)
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        return await steps(keys, db, make_client)
    return pg(body, *OTHER_USER_SQL, *setup_sql)


def _auth(key):
    return {"authorization": f"Bearer {key}"}


async def _start(client, key, intent="contact.delete"):
    r = await client.post("/api/v1/execute", json={"input_data": {"message": intent}}, headers=_auth(key))
    return r.json()


def test_full_confirmation_flow_survives_a_restart_and_is_single_use(pg):
    async def steps(keys, db, make_client):
        async with make_client() as first:
            j = await _start(first, keys["tenant-a"])
        cid = j["confirmation_id"]
        async with db.tenant_transaction("tenant-a") as c:
            stored = [dict(r) for r in await c.fetch("SELECT confirmation_id, tenant_id FROM suspended_runs")]
        async with make_client() as second:                      # a new process
            ok = await second.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
            again = await second.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
        return j, stored, ok, again
    j, stored, ok, again = _flow(pg, steps)
    assert (j["status"], j["final_stage"]) == ("CLARIFY", "S10")
    assert stored == [{"confirmation_id": j["confirmation_id"], "tenant_id": "tenant-a"}]
    assert (ok.status_code, ok.json()["status"], ok.json()["final_stage"]) == (200, "NORMAL", "S11")
    assert again.json()["reason"] == "confirmation_mismatch"


def test_another_user_or_tenant_cannot_answer(pg):
    async def steps(keys, db, make_client):
        async with make_client() as client:
            cid = (await _start(client, keys["tenant-a"]))["confirmation_id"]
            other_user = await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["other"]))
            other_tenant = await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-b"]))
            owner = await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
        return other_user, other_tenant, owner
    other_user, other_tenant, owner = _flow(pg, steps)
    assert (other_user.json()["status"], other_user.json()["reason"]) == ("DENY", "confirmation_mismatch")
    assert other_tenant.status_code == 404                      # RLS: tenant-b cannot even see it
    assert owner.json()["status"] == "NORMAL"                   # the wrong replies did not burn it


def test_rejection_over_http(pg):
    async def steps(keys, db, make_client):
        async with make_client() as client:
            cid = (await _start(client, keys["tenant-a"]))["confirmation_id"]
            no = await client.post(f"/api/v1/confirmations/{cid}", json={"approved": False}, headers=_auth(keys["tenant-a"]))
            late = await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
        return no, late
    no, late = _flow(pg, steps)
    assert (no.json()["status"], no.json()["reason"]) == ("DENY", "confirmation_rejected")
    assert late.json()["reason"] == "confirmation_mismatch"


def test_kill_switch_engaged_while_the_run_waits(pg):
    async def steps(keys, db, make_client):
        async with make_client() as client:
            cid = (await _start(client, keys["tenant-a"]))["confirmation_id"]
            async with db.tenant_transaction("tenant-a") as c:
                await c.execute("UPDATE tenants SET kill_switch_engaged = true")
            return await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
    r = _flow(pg, steps)
    assert (r.json()["status"], r.json()["final_stage"], r.json()["reason"]) == ("DENY", "S8", "kill_switch")


def test_user_suspended_while_the_run_waits(pg):
    async def steps(keys, db, make_client):
        async with make_client() as client:
            cid = (await _start(client, keys["tenant-a"]))["confirmation_id"]
            async with db.tenant_transaction("tenant-a") as c:
                await c.execute("UPDATE users SET status = 'suspended' WHERE user_id = 'tenant-a.user'")
            return await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
    r = _flow(pg, steps)
    assert (r.json()["final_stage"], r.json()["reason"]) == ("S8", "user_active_inactive")


def test_expired_confirmation_over_http(pg):
    async def steps(keys, db, make_client):
        async with make_client() as client:
            cid = (await _start(client, keys["tenant-a"]))["confirmation_id"]
            async with db.tenant_transaction("tenant-a") as c:
                await c.execute("UPDATE pending_confirmations SET expires_at = now() - interval '1 second'")
            return await client.post(f"/api/v1/confirmations/{cid}", json={"approved": True}, headers=_auth(keys["tenant-a"]))
    assert _flow(pg, steps).json()["reason"] == "confirmation_expired"


def test_paused_workspace_is_denied_at_s0_over_http(pg):
    _, j, _ = _scenario(pg, "contact.list",
                        "UPDATE workspaces SET paused_until = now() + interval '1 hour' WHERE workspace_id = 'tenant-a.ws'")
    assert (j["status"], j["final_stage"], j["reason"]) == ("DENY", "S0", "workspace_paused")


def test_paused_tenant_and_scheduled_activation_over_http(pg):
    _, paused, _ = _scenario(pg, "contact.list", "UPDATE tenants SET paused_until = now() + interval '1 hour' WHERE tenant_id = 'tenant-a'")
    _, future, _ = _scenario(pg, "contact.list", "UPDATE tenants SET scheduled_activation_at = now() + interval '1 hour' WHERE tenant_id = 'tenant-a'")
    _, over, _ = _scenario(pg, "contact.list", "UPDATE tenants SET paused_until = now() - interval '1 hour' WHERE tenant_id = 'tenant-a'")
    assert paused["reason"] == "tenant_paused" and future["reason"] == "not_yet_active"
    assert (over["status"], over["final_stage"]) == ("NORMAL", "S11")


def test_a_pause_on_another_tenant_does_not_affect_this_one(pg):
    _, j, _ = _scenario(pg, "contact.list", "UPDATE tenants SET paused_until = now() + interval '1 hour' WHERE tenant_id = 'tenant-b'")
    assert j["status"] == "NORMAL"


def test_a_run_leaves_an_ordered_event_trail_per_tenant(pg):
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        keys = {t: await auth.issue(_principal(t)) for t in ("tenant-a", "tenant-b")}
        app = create_app(pipeline=build_runner(db, EchoIntentModel()), authenticator=auth)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            ok = (await _start(client, keys["tenant-a"], "contact.list"))
            bad = (await _start(client, keys["tenant-b"], "contact.teleport"))
        rows = {}
        for t in ("tenant-a", "tenant-b"):
            async with db.tenant_transaction(t) as c:
                rows[t] = [dict(r) for r in await c.fetch(
                    "SELECT stage, status, reason, trace_id FROM pipeline_events ORDER BY event_id")]
        return ok, bad, rows
    ok, bad, rows = pg(body)
    assert [r["stage"] for r in rows["tenant-a"]] == ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]
    assert {r["status"] for r in rows["tenant-a"]} == {"normal"}
    assert len({r["trace_id"] for r in rows["tenant-a"]}) == 1 and ok["trace_id"] == rows["tenant-a"][0]["trace_id"]
    assert [(r["stage"], r["status"], r["reason"]) for r in rows["tenant-b"]][-1] == ("S2", "clarify", "intent_unclear")
    assert not any(r["stage"] == "S3" for r in rows["tenant-b"])



def _reservation(tenant, cost):
    return ("INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost)"
            f" VALUES ('r-{tenant}', '{tenant}', 'u', 'e', 's', {cost})")


def test_open_reservations_shrink_the_budget_a_run_may_use(pg):
    """The pool is 10000; a contact.list costs 1. With 10000 already reserved nothing is left."""
    code, j, _ = _scenario(pg, "contact.list", _reservation("tenant-a", 10000))
    assert (j["status"], j["final_stage"], j["reason"]) == ("DENY", "S8", "budget_available_denied"), j
    # another tenant's reservations do not matter
    code, j, _ = _scenario(pg, "contact.list", _reservation("tenant-b", 10000))
    assert (j["status"], j["final_stage"]) == ("NORMAL", "S11"), j
