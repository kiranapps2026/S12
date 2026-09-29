"""Each PostgreSQL adapter against a real database, as a non-superuser (RLS enforced)."""
from __future__ import annotations

import asyncio
import time

import pytest

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.confirmations import PostgresConfirmationStore
from adapters.postgres.database import Database, LoopBridge
from adapters.postgres.identity import PostgresAuthorizationState, PostgresMutationPolicy
from adapters.postgres.migrate import apply_migrations
from adapters.postgres.registry import PostgresCapabilityRegistry
from adapters.postgres.scope import PostgresRunScopes
from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from contracts.errors import DependencyUnavailable
from contracts.execution_manifest import Confirmation
from contracts.principal import Principal
from engine.stages.s10_confirmation.store import CONSUMED, EXPIRED, MISMATCH

A, B = "tenant-a", "tenant-b"


async def _in_thread(fn, *args):
    return await asyncio.to_thread(fn, *args)


def test_migrations_are_idempotent(database_url):
    async def rerun():
        owner = await Database.connect(database_url)
        try:
            return await apply_migrations(owner)
        finally:
            await owner.close()
    assert asyncio.run(rerun()) == []


def test_rls_hides_other_tenants(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        own = await _in_thread(auth.user_status, "tenant-a.user")
        with pytest.raises(DependencyUnavailable):
            await _in_thread(auth.user_status, "tenant-b.user")
        with pytest.raises(DependencyUnavailable):
            await _in_thread(auth.tenant_status, B)          # bound to one tenant
        async with db.tenant_transaction(A) as c:
            visible = await c.fetchval("SELECT count(*) FROM users")
        async with db.tenant_transaction(None) as c:
            none_visible = await c.fetchval("SELECT count(*) FROM users")
        return own, visible, none_visible
    assert pg(body) == ("active", 1, 0)


def test_bridge_refuses_the_loop_thread(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        with pytest.raises(RuntimeError, match="deadlock"):
            auth.user_status("tenant-a.user")            # called on the loop thread
    pg(body)


def test_authorization_answers(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        status, expires = await _in_thread(auth.connection_status, "tenant-a.conn")
        return (
            await _in_thread(auth.tenant_status, A), status, expires,
            await _in_thread(auth.has_grant, A, "tenant-a.user", "cap.contact.list"),
            await _in_thread(auth.has_grant, A, "tenant-a.user", "cap.nothing"),
            await _in_thread(auth.in_scope, A, "tenant-a.user", "tenant-a.ws"),
            await _in_thread(auth.in_scope, A, "tenant-a.user", "tenant-b.ws"),
            await _in_thread(auth.budget_available, A, 10000),
            await _in_thread(auth.budget_available, A, 10001),
        )
    assert pg(body) == ("active", "active", None, True, False, True, False, True, False)


def test_inactive_and_expired_records(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        return (await _in_thread(auth.user_status, "tenant-a.user"),
                (await _in_thread(auth.connection_status, "tenant-a.conn"))[1] < time.time())
    assert pg(body, "UPDATE users SET status = 'suspended' WHERE tenant_id = 'tenant-a'",
              "UPDATE connections SET expires_at = now() - interval '1 hour' WHERE tenant_id = 'tenant-a'"
              ) == ("suspended", True)


def test_mutation_ceiling(pg):
    async def body(db):
        policy = PostgresMutationPolicy(db, A, LoopBridge.current())        # ceiling 'D'
        return [await _in_thread(policy.permits, m, 0.1) for m in ("R", "W", "D", "IRREVERSIBLE")]
    assert pg(body) == [True, True, True, False]


def test_run_scope_reads_policy_live_and_binds_tenant(pg):
    async def body(db):
        scopes = PostgresRunScopes(db, InProcessCircuitBreaker())
        first = await scopes.for_run(A, "tenant-a.ws")
        async with db.tenant_transaction(A) as c:      # tenant switch flips between runs
            await c.execute("UPDATE tenants SET kill_switch_engaged = true WHERE tenant_id = 'tenant-a'")
        second = await scopes.for_run(A, "tenant-a.ws")
        with pytest.raises(DependencyUnavailable):
            await scopes.for_run(A, "tenant-b.ws")     # workspace of another tenant
        return first, second
    first, second = pg(body)
    assert (first.policy.kill_switch_engaged, second.policy.kill_switch_engaged) == (False, True)
    assert first.policy.risk_deny_threshold == 0.95
    assert first.policy_versions.policy_version_id == "tenant-a.policy-1"


def test_system_kill_switch_engages_every_tenant(pg):
    async def body(db):
        return (await PostgresRunScopes(db, InProcessCircuitBreaker()).for_run(B, "tenant-b.ws")).policy
    assert pg(body, "UPDATE system_settings SET kill_switch_engaged = true").kill_switch_engaged is True


def test_workspace_policy_version_overrides_tenant(pg):
    async def body(db):
        return (await PostgresRunScopes(db, InProcessCircuitBreaker()).for_run(A, "tenant-a.ws")).policy_versions
    v = pg(body, "UPDATE workspaces SET policy_version_id = 'ws-policy-9' WHERE workspace_id = 'tenant-a.ws'")
    assert (v.tenant_policy_version_id, v.workspace_policy_version_id) == ("tenant-a.policy-1", "ws-policy-9")


def test_registry_catalog_and_bindings(pg):
    async def body(db):
        reg = PostgresCapabilityRegistry(db)
        found = await reg.discover({"intent_type": "contact.delete"}, A)
        bindings = await reg.list_bindings("cap.contact.delete")
        return found, bindings, await reg.discover({"intent_type": "nope"}, A)
    found, bindings, none = pg(body)
    assert none == []
    (cap,) = found
    assert (cap.capability_id, cap.mutation_type, cap.risk_floor, cap.estimated_cost_units) == (
        "cap.contact.delete", "D", 0.5, 5)
    (b,) = bindings
    assert (b.kernel_op_id, b.provider, b.capability_version, b.authorization_version) == (
        "crm.contact_delete", "crm", "cap-7", "auth-4")


def test_registry_uses_the_more_severe_mutation_and_higher_floor(pg):
    async def body(db):
        (cap,) = await PostgresCapabilityRegistry(db).discover({"intent_type": "contact.list"}, A)
        return cap
    cap = pg(body, "UPDATE kernel_ops SET mutation = 'IRREVERSIBLE', risk_floor = 0.6"
                   " WHERE kernel_op_id = 'crm.contact_list'")
    assert (cap.mutation_type, cap.risk_floor) == ("IRREVERSIBLE", 0.6)


@pytest.mark.parametrize("break_sql", [
    "UPDATE capabilities SET truth_state = 'DRAFT' WHERE intent = 'contact.list'",
    "UPDATE bindings SET is_active = false WHERE capability_id = 'cap.contact.list'",
    "UPDATE kernel_ops SET truth_state = 'REVIEW' WHERE kernel_op_id = 'crm.contact_list'",
])
def test_registry_offers_only_production_capabilities_with_a_live_binding(pg, break_sql):
    async def body(db):
        reg = PostgresCapabilityRegistry(db)
        return await reg.discover({"intent_type": "contact.list"}, A), await reg.list_bindings("cap.contact.list")
    assert pg(body, break_sql) == ([], [])


def _conf(user="tenant-a.user", plan_hash="h" * 64, ttl=300.0):
    return Confirmation(confirmation_id="c-1", user_id=user, conversation_id="conv", plan_id="p-1",
                        plan_hash=plan_hash, operations=({"step_id": "s1", "mutation": "D"},),
                        expires_at=time.time() + ttl)


def test_confirmation_is_single_use_and_tenant_bound(pg):
    async def body(db):
        store = PostgresConfirmationStore(db)
        await store.save(_conf(), A, "exec-1")
        wrong_tenant = await store.consume("c-1", tenant_id=B, user_id="tenant-a.user", plan_hash="h" * 64)
        wrong_user = await store.consume("c-1", tenant_id=A, user_id="someone", plan_hash="h" * 64)
        wrong_hash = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="0" * 64)
        ok = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="h" * 64)
        again = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="h" * 64)
        return wrong_tenant, wrong_user, wrong_hash, ok, again
    assert pg(body) == (MISMATCH, MISMATCH, MISMATCH, CONSUMED, MISMATCH)


def test_confirmation_expiry_uses_the_database_clock(pg):
    async def body(db):
        store = PostgresConfirmationStore(db)
        await store.save(_conf(ttl=-5.0), A, "exec-1")
        # a caller-supplied "now" in the past must not rescue an expired confirmation
        return await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="h" * 64,
                                   now=time.time() - 3600)
    assert pg(body) == EXPIRED


def test_confirmation_rejects_empty_ids_and_hides_other_tenants(pg):
    async def body(db):
        store = PostgresConfirmationStore(db)
        with pytest.raises(ValueError):
            await store.save(_conf(), A, "")
        await store.save(_conf(), A, "exec-1")
        async with db.tenant_transaction(B) as c:
            return await c.fetchval("SELECT count(*) FROM pending_confirmations")
    assert pg(body) == 0


def test_api_keys(pg):
    principal = Principal(A, "tenant-a.ws", "tenant-a.user", "tenant-a.member", "tenant-a.conn", "scope-1")

    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        key = await auth.issue(principal)
        async with db.transaction() as c:
            stored = await c.fetchval("SELECT key_hash FROM api_keys")
        return (key, stored, await auth.authenticate(key), await auth.authenticate(key + "x"),
                await auth.authenticate("not-a-key"), await auth.authenticate(""))
    key, stored, ok, bad, wrong_prefix, empty = pg(body)
    assert key.startswith("sk_supra_") and key not in stored and len(stored) == 64
    assert ok == principal
    assert bad is None and wrong_prefix is None and empty is None


def test_revoked_api_key_stops_working(pg):
    principal = Principal(A, "tenant-a.ws", "tenant-a.user", "tenant-a.member", "tenant-a.conn", "")

    async def body(db):
        auth = PostgresApiKeyAuthenticator(db)
        key = await auth.issue(principal)
        async with db.transaction() as c:
            await c.execute("UPDATE api_keys SET is_active = false")
        return await auth.authenticate(key)
    assert pg(body) is None


# ---- suspended runs ---------------------------------------------------------------------

def _suspended_state():
    from tests.fixtures.pipeline import run_pipeline
    from tests.fixtures.scenarios import make_scenario
    r = run_pipeline({"message": "x", "connection_id": "c"},
                     make_scenario(mutation="D", risk=0.9, steps=2, graph="chain", confidence=0.8))
    return r.final_state


def test_suspended_run_round_trips_through_jsonb(pg):
    from adapters.postgres.suspended_runs import PostgresSuspendedRunStore
    state = _suspended_state()
    conf = state.confirmation.confirmation

    async def body(db):
        await PostgresConfirmationStore(db).save(conf, "tenant-1", state.plan.execution_id)
        store = PostgresSuspendedRunStore(db)
        await store.save(state, tenant_id="tenant-1", execution_id=state.plan.execution_id,
                         confirmation_id=conf.confirmation_id)
        return await store.load(tenant_id="tenant-1", confirmation_id=conf.confirmation_id)
    assert pg(body, "INSERT INTO tenants (tenant_id, name, policy_version_id) VALUES ('tenant-1','t','p')") == state


def test_suspended_run_is_tenant_scoped_and_needs_its_confirmation(pg):
    from adapters.postgres.suspended_runs import PostgresSuspendedRunStore
    state = _suspended_state()
    conf = state.confirmation.confirmation

    async def body(db):
        await PostgresConfirmationStore(db).save(conf, "tenant-1", "exec-1")
        store = PostgresSuspendedRunStore(db)
        await store.save(state, tenant_id="tenant-1", execution_id="exec-1",
                         confirmation_id=conf.confirmation_id)
        other = await store.load(tenant_id=B, confirmation_id=conf.confirmation_id)
        with pytest.raises(Exception):                       # FK: no confirmation, no suspended run
            await store.save(state, tenant_id="tenant-1", execution_id="exec-1", confirmation_id="ghost")
        with pytest.raises(ValueError):
            await store.save(state, tenant_id="tenant-1", execution_id="", confirmation_id="x")
        return other
    assert pg(body, "INSERT INTO tenants (tenant_id, name, policy_version_id) VALUES ('tenant-1','t','p')") is None


def test_confirmation_reject(pg):
    async def body(db):
        store = PostgresConfirmationStore(db)
        await store.save(_conf(), A, "exec-1")
        wrong = await store.reject("c-1", tenant_id=A, user_id="someone")
        other_tenant = await store.reject("c-1", tenant_id=B, user_id="tenant-a.user")
        ok = await store.reject("c-1", tenant_id=A, user_id="tenant-a.user")
        again = await store.reject("c-1", tenant_id=A, user_id="tenant-a.user")
        late = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="h" * 64)
        return wrong, other_tenant, ok, again, late
    assert pg(body) == (False, False, True, False, MISMATCH)


# ---- S0.1 activation --------------------------------------------------------------------

def test_activation_state_uses_database_time(pg):
    from adapters.postgres.activation import PostgresActivationReader
    state = pg(lambda db: PostgresActivationReader(db).read(A, "tenant-a.ws"),
               "UPDATE workspaces SET paused_until = now() + interval '1 hour' WHERE workspace_id = 'tenant-a.ws'",
               "UPDATE tenants SET scheduled_activation_at = now() + interval '2 hours' WHERE tenant_id = 'tenant-a'")
    assert abs(state.database_now - time.time()) < 60
    assert state.workspace_paused_until - state.database_now == pytest.approx(3600, abs=5)
    assert state.tenant_activation_at - state.database_now == pytest.approx(7200, abs=5)
    assert state.tenant_paused_until is None and state.workspace_activation_at is None


def test_activation_needs_a_real_tenant_workspace_pair(pg):
    from adapters.postgres.activation import PostgresActivationReader

    async def body(db):
        reader = PostgresActivationReader(db)
        for tenant, ws in ((A, "tenant-b.ws"), (B, "tenant-a.ws"), (A, "nope"), ("nope", "tenant-a.ws")):
            with pytest.raises(DependencyUnavailable):
                await reader.read(tenant, ws)
    pg(body)


# ---- stage event log --------------------------------------------------------------------

def _event(tenant=A, stage="S3", status="normal", reason=None):
    from contracts.stage_events import StageEvent
    return StageEvent(stage=stage, status=status, reason=reason, duration_ms=1.5,
                      trace_id="tr-1", request_id="rq-1", tenant_id=tenant)


def test_events_are_stored_and_tenant_isolated(pg):
    from adapters.postgres.events import PostgresEventSink

    async def body(db):
        sink = PostgresEventSink(db)
        await sink.emit(_event(A, "S3"))
        await sink.emit(_event(B, "S4", "deny", "why"))
        async with db.tenant_transaction(A) as c:
            a = [dict(r) for r in await c.fetch("SELECT tenant_id, stage, status, reason FROM pipeline_events")]
        async with db.tenant_transaction(B) as c:
            b = [dict(r) for r in await c.fetch("SELECT tenant_id, stage, status, reason FROM pipeline_events")]
        async with db.tenant_transaction(None) as c:
            none = await c.fetchval("SELECT count(*) FROM pipeline_events")
        return a, b, none
    a, b, none = pg(body)
    assert a == [{"tenant_id": A, "stage": "S3", "status": "normal", "reason": None}]
    assert b == [{"tenant_id": B, "stage": "S4", "status": "deny", "reason": "why"}]
    assert none == 0


def test_an_event_without_a_tenant_is_accepted_but_a_forged_tenant_is_not(pg):
    from adapters.postgres.events import PostgresEventSink

    async def body(db):
        sink = PostgresEventSink(db)
        await sink.emit(_event(None, "S0", "deny", "missing_tenant_id"))      # allowed: S0 stopped early
        async with db.tenant_transaction(A) as c:                               # cannot write another tenant's row
            with pytest.raises(Exception):
                await c.execute("INSERT INTO pipeline_events (tenant_id, stage, status, duration_ms)"
                                " VALUES ('tenant-b', 'S3', 'normal', 1)")
    pg(body)


def test_the_event_log_is_append_only_for_the_application_role(pg):
    from adapters.postgres.events import PostgresEventSink

    async def body(db):
        await PostgresEventSink(db).emit(_event())
        for sql in ("UPDATE pipeline_events SET status = 'deny'", "DELETE FROM pipeline_events"):
            async with db.tenant_transaction(A) as c:
                with pytest.raises(Exception, match="permission denied"):
                    await c.execute(sql)
        async with db.tenant_transaction(A) as c:
            return await c.fetchval("SELECT count(*) FROM pipeline_events")
    assert pg(body) == 1


def test_an_invalid_status_is_rejected_by_the_database(pg):
    from adapters.postgres.events import PostgresEventSink

    async def body(db):
        with pytest.raises(Exception):
            await PostgresEventSink(db).emit(_event(status="approved"))
    pg(body)


def _reserve(tenant, cost, status="reserved", age="0 seconds", rid=[0]):
    rid[0] += 1
    return (f"INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id,"
            f" cost, status, created_at) VALUES ('r{rid[0]}', '{tenant}', 'u', 'e', 's{rid[0]}', {cost},"
            f" '{status}', now() - interval '{age}')")


def test_budget_subtracts_open_reservations_but_not_released_ones(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        return tuple([await _in_thread(auth.budget_available, A, n) for n in (4000, 4001, 9000)])
    assert pg(body, _reserve(A, 3000), _reserve(A, 2000, "locked"), _reserve(A, 1000, "committed"),
              _reserve(A, 9000, "released")) == (True, False, False)


def test_budget_ignores_other_tenants_and_reservations_from_earlier_periods(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        return await _in_thread(auth.budget_available, A, 10000), await _in_thread(auth.budget_available, A, 10001)
    assert pg(body, _reserve("tenant-b", 9000), _reserve(A, 5000, age="400 days")) == (True, False)


def test_budget_period_decides_which_reservations_count(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db, A, LoopBridge.current())
        return await _in_thread(auth.budget_available, A, 10000)
    # a 40-day-old reservation is outside every period: the whole pool is available
    assert pg(body, "UPDATE tenants SET budget_period = 'daily' WHERE tenant_id = 'tenant-a'",
              _reserve(A, 5000, age="40 days")) is True
    # a reservation made just now is inside every period
    assert pg(body, "UPDATE tenants SET budget_period = 'daily' WHERE tenant_id = 'tenant-a'",
              _reserve(A, 5000)) is False


def test_an_unknown_budget_period_cannot_be_stored(pg):
    async def body(db):
        return None
    with pytest.raises(Exception, match="budget_period"):
        pg(body, "UPDATE tenants SET budget_period = 'yearly' WHERE tenant_id = 'tenant-a'")


def test_the_registry_reports_a_kernel_operations_inverse(pg):
    async def body(db):
        from adapters.postgres.registry import PostgresCapabilityRegistry
        registry = PostgresCapabilityRegistry(db)
        return [(b.kernel_op_id, b.inverse_kernel_op_id)
                for cap in ("cap.contact.create", "cap.contact.list")
                for b in await registry.list_bindings(cap)]
    assert pg(body, "UPDATE kernel_ops SET inverse = 'crm.contact_delete' WHERE kernel_op_id = 'crm.contact_create'"
              ) == [("crm.contact_create", "crm.contact_delete"), ("crm.contact_list", None)]


def test_the_binding_reader_returns_the_registry_version_for_active_bindings_only(pg):
    async def body(db):
        from adapters.postgres.registry import PostgresBindingVersionReader
        reader = PostgresBindingVersionReader(db)
        return (await reader.binding_version("bind.contact.list"), await reader.binding_version("bind.nothing"))
    assert pg(body) == ("bind-3", None)


def test_an_inactive_binding_has_no_version(pg):
    async def body(db):
        from adapters.postgres.registry import PostgresBindingVersionReader
        return await PostgresBindingVersionReader(db).binding_version("bind.contact.list")
    assert pg(body, "UPDATE bindings SET is_active = false WHERE binding_id = 'bind.contact.list'") is None
