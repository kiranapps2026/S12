"""HTTP -> API key -> real runner -> real PostgreSQL adapters (RLS enforced), no fixtures
standing in for a dependency except the LLM (whose port has no production adapter yet)."""
from __future__ import annotations

import asyncio

import httpx

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.confirmations import PostgresConfirmationStore
from adapters.postgres.registry import PostgresCapabilityRegistry
from adapters.postgres.scope import PostgresRunScopes
from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from app import create_app
from contracts.principal import Principal
from contracts.stage_outputs import IntentResult
from engine.control_plane.pipeline_state_runner import PipelineDependencies, build_pipeline


class EchoIntentLLM:
    """Test LLM: the message text IS the intent name (e.g. "contact.list")."""

    async def analyze_intent(self, sanitized_input):
        intent = sanitized_input.get("message", "")
        return IntentResult(intent_type=intent, target_entities=("default",), operations=(intent,),
                            parameters={"steps": 1}, is_workflow=False, confidence=0.95)


def _principal(tenant):
    return Principal(tenant, f"{tenant}.ws", f"{tenant}.user", f"{tenant}.member", f"{tenant}.conn", "")


def _scenario(pg, intent, *setup_sql, tenant="tenant-a", key_of=None, headers=None):
    """Run one HTTP request; returns (status_code, json, pending_confirmation_rows)."""
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        keys = {t: await auth.issue(_principal(t)) for t in ("tenant-a", "tenant-b")}
        deps = PipelineDependencies(
            llm=EchoIntentLLM(), registry=PostgresCapabilityRegistry(db),
            scopes=PostgresRunScopes(db, InProcessCircuitBreaker()),
            confirmation_store=PostgresConfirmationStore(db))
        app = create_app(pipeline=build_pipeline(deps), authenticator=auth)
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
    assert (j["status"], j["final_stage"], j["reason"]) == ("CLARIFY", "S3", "no_capability")


def test_bad_or_missing_key_is_401(pg):
    assert _scenario(pg, "contact.list", headers={"authorization": "Bearer sk_supra_nope"})[0] == 401
    assert _scenario(pg, "contact.list", headers={})[0] == 401


def test_database_outage_fails_closed(pg):
    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        key = await auth.issue(_principal("tenant-a"))
        deps = PipelineDependencies(
            llm=EchoIntentLLM(), registry=PostgresCapabilityRegistry(db),
            scopes=PostgresRunScopes(db, InProcessCircuitBreaker()),
            confirmation_store=PostgresConfirmationStore(db))
        app = create_app(pipeline=build_pipeline(deps), authenticator=auth)
        await db.close()                                   # the database goes away
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.post("/api/v1/execute", json={"input_data": {"message": "contact.list"}},
                                     headers={"authorization": f"Bearer {key}"})
    r = pg(body)
    assert r.status_code == 503 and r.json()["detail"] == "authentication_unavailable"


def test_pool_failure_after_authentication_never_runs_the_pipeline(pg):
    """Key resolves, then the scope read fails: ERROR at S0, nothing after S0 ran."""
    async def body(db):
        deps = PipelineDependencies(
            llm=EchoIntentLLM(), registry=PostgresCapabilityRegistry(db),
            scopes=PostgresRunScopes(db, InProcessCircuitBreaker()),
            confirmation_store=PostgresConfirmationStore(db))
        runner = build_pipeline(deps)
        from tests.fixtures.pipeline import make_entry
        entry = make_entry({"message": "contact.list", "tenant_id": "tenant-a", "workspace_id": "tenant-a.ws",
                            "connection_id": "tenant-a.conn"})
        await db.close()
        return await runner.run(entry)
    result = pg(body)
    assert (result.status.value, result.reason, result.stages_run) == ("ERROR", "scope_unavailable", ("S0",))
