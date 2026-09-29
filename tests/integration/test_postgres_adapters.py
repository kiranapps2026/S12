"""Each PostgreSQL adapter against a real database, as a non-superuser (RLS enforced)."""
from __future__ import annotations

import asyncio
import time

import pytest

from supragents.adapters.postgres.confirmations import PostgresConfirmationStore
from supragents.adapters.postgres.database import Database
from supragents.adapters.postgres.identity import PostgresActivationReader, PostgresAuthorizationState
from supragents.adapters.postgres.ledger import PostgresEventSink
from supragents.adapters.postgres.migrate import apply_migrations
from supragents.adapters.postgres.policy import PostgresKernelPolicy, PostgresMutationPolicy, PostgresPolicyVersions
from supragents.adapters.postgres.registry import PostgresCapabilityRegistry
from supragents.contracts.errors import DependencyUnavailable
from supragents.contracts.events import StageEvent
from supragents.contracts.outputs import Confirmation
from supragents.contracts.vocabulary import ConfirmationStatus, Mutation, RecordStatus, StageStatus, TruthState

A = "tenant-a"


def test_migrations_are_idempotent(database_url):
    async def rerun():
        owner = await Database.connect(database_url)
        try:
            return await apply_migrations(owner)
        finally:
            await owner.close()
    assert asyncio.run(rerun()) == []


def test_activation_state_uses_database_time(pg):
    state = pg(lambda db: PostgresActivationReader(db).read(A, "tenant-a.ws"),
               "UPDATE workspaces SET paused_until = now() + interval '1 hour' WHERE workspace_id = 'tenant-a.ws'")
    assert abs(state.database_now - time.time()) < 60
    assert state.workspace_paused_until - state.database_now == pytest.approx(3600, abs=5)
    assert state.tenant_paused_until is None


def test_row_level_security_hides_other_tenants(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db)
        own = await auth.user_status(A, "tenant-a.user")
        with pytest.raises(DependencyUnavailable):
            await auth.user_status(A, "tenant-b.user")
        async with db.tenant_transaction(A) as connection:
            visible = await connection.fetchval("SELECT count(*) FROM users")
        return own, visible
    assert pg(body) == (RecordStatus.ACTIVE, 1)


def test_authorization_answers(pg):
    async def body(db):
        auth = PostgresAuthorizationState(db)
        return (await auth.tenant_status(A),
                (await auth.connection_state(A, "tenant-a.conn")).status,
                await auth.has_grant(A, "tenant-a.user", "cap.contact.list"),
                await auth.has_grant(A, "tenant-a.user", "cap.contact.create"),
                await auth.workspace_in_scope(A, "tenant-a.user", "tenant-a.ws", "tenant-a.member"),
                await auth.workspace_in_scope(A, "tenant-a.user", "tenant-a.ws", "tenant-b.member"),
                await auth.budget_available(A, 10000), await auth.budget_available(A, 10001))
    assert pg(body, "UPDATE capability_grants SET expires_at = now() - interval '1 second'"
                    " WHERE capability_grant_id = 'grant.tenant-a.contact.create'") == (
        RecordStatus.ACTIVE, RecordStatus.ACTIVE, True, False, True, False, True, False)


def test_registry_reads(pg):
    async def body(db):
        registry = PostgresCapabilityRegistry(db)
        return (await registry.capabilities_for_intent(A, "contact.delete"),
                await registry.bindings_for(A, "cap.contact.delete"),
                await registry.kernel_operation("crm.contact_delete"),
                await registry.kernel_operation("missing"), await registry.versions())
    caps, bindings, op, missing, versions = pg(body)
    assert (caps[0].mutation, caps[0].risk_floor, caps[0].truth_state) == (Mutation.DELETE, 0.5, TruthState.PRODUCTION_ENABLED)
    assert bindings[0].kernel_op_id == op.kernel_op_id == "crm.contact_delete" and op.cost == 5
    assert missing is None and versions.capability_version == "cap-7"


@pytest.mark.parametrize("setup, engaged", [
    ((), False),
    (("UPDATE system_settings SET kill_switch_engaged = true",), True),
    (("UPDATE tenants SET kill_switch_engaged = true WHERE tenant_id = 'tenant-a'",), True),
])
def test_kill_switch_is_system_or_tenant(pg, setup, engaged):
    assert pg(lambda db: PostgresKernelPolicy(db).current(A), *setup).kill_switch_engaged is engaged


def test_policy_versions_fall_back_to_the_tenant(pg):
    versions = pg(lambda db: PostgresPolicyVersions(db).current(A, "tenant-a.ws"))
    assert versions.policy_version_id == versions.tenant_policy_version_id == "tenant-a.policy-1"


def test_mutation_ceiling(pg):
    async def body(db):
        policy = PostgresMutationPolicy(db)
        return [await policy.permits(A, m, 0.1) for m in Mutation]
    assert pg(body) == [True, True, True, False]


def _confirmation(expires_in: float = 300.0) -> Confirmation:
    return Confirmation("c-1", "tenant-a.user", "conv", "plan-1", "hash-1",
                        ({"step_id": "step-1"},), time.time() + expires_in)


def test_confirmation_single_use_and_tenant_bound(pg):
    async def body(db):
        store = PostgresConfirmationStore(db)
        await store.save(_confirmation(), tenant_id=A, execution_id="exec-1")
        other_tenant = await store.consume("c-1", tenant_id="tenant-b", user_id="tenant-a.user", plan_hash="hash-1")
        wrong_hash = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="x")
        first = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="hash-1")
        second = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="hash-1")
        stored = await store.find(tenant_id=A, execution_id="exec-1")
        hidden = await store.find(tenant_id="tenant-b", execution_id="exec-1")
        return other_tenant, wrong_hash, first, second, stored.status, hidden
    assert pg(body) == (False, False, True, False, ConfirmationStatus.CONSUMED, None)


def test_expired_confirmation_by_database_time(pg):
    async def body(db):
        store = PostgresConfirmationStore(db)
        await store.save(_confirmation(expires_in=-1), tenant_id=A, execution_id="exec-1")
        consumed = await store.consume("c-1", tenant_id=A, user_id="tenant-a.user", plan_hash="hash-1")
        return consumed, (await store.find(tenant_id=A, execution_id="exec-1")).status
    assert pg(body) == (False, ConfirmationStatus.EXPIRED)


def test_confirmation_save_requires_ids(pg):
    async def body(db):
        with pytest.raises(ValueError):
            await PostgresConfirmationStore(db).save(_confirmation(), tenant_id=A, execution_id="")
    pg(body)


def test_ledger_rows_are_tenant_scoped(pg):
    async def body(db):
        sink = PostgresEventSink(db)
        await sink.emit(StageEvent("t-1", "r-1", A, "S0", StageStatus.NORMAL, None, 1.5))
        await sink.emit(StageEvent(None, None, None, "S0", StageStatus.DENY, "identity_missing:tenant_id", 0.2))
        async with db.tenant_transaction("tenant-b") as connection:
            return await connection.fetchval("SELECT count(*) FROM pipeline_events")
    assert pg(body) == 0
