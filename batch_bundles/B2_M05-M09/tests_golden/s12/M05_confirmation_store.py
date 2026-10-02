"""M5 golden — PostgreSQL confirmation store and the C20 entry check (gate commit D part 1). Owner-pinned.

Gate v10: C20, §14 "now in scope", suite 13; S0–S11 ruling R-Z (CONF-003: tenant_id/execution_id reach the store as
required arguments). The store itself is certified S0–S11 code (adapters/postgres/confirmations.py, frozen): its cases
pass already and stay as regression (CONF-010, red-first per file). What M5 builds is C20's S12-side check.

Interface this file fixes:
  * ``adapters.postgres.confirmation_records.PostgresConsumedConfirmationReader(database)`` with
    ``async read(confirmation_id, *, tenant_id) -> ConsumedConfirmation | None`` (tenant-scoped; None when the row is
    not visible to that tenant). ``ConsumedConfirmation`` has ``status``, ``execution_id``, ``plan_hash``, ``user_id``.
  * ``engine.stages.s12_entry.confirmation.confirmation_denial(state, reader) -> str | None``: None when the plan needed
    no confirmation, or when the store row of ``state.confirmation.confirmation`` is ``consumed`` and its
    ``execution_id``, ``plan_hash`` and tenant equal the run being admitted (``state.plan.execution_id``,
    ``state.execution_manifest.plan_hash``, ``execution_context.tenant_id``); ``"confirmation_mismatch"`` otherwise;
    ``"confirmation_unavailable"`` when the reader is missing or raises (fail closed, like ``binding_unavailable``).
    It writes nothing.
  * ``engine.stages.s12_entry.checks.check_entry(..., confirmations=reader)`` applies it and denies with that reason.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from contracts.execution_manifest import Confirmation, ConfirmationOutcome
from engine.stages.s10_confirmation.store import CONSUMED, EXPIRED, MISMATCH, ConfirmationStoreImpl
from tests_golden.fixtures.certified import certified_state
from tests_golden.fixtures.invariants import assert_system_invariants

T, OTHER = "golden-tenant", "golden-other-tenant"
EXEC = "golden-exec"


def _confirmation(cid: str, *, user="golden-user", plan_hash="h" * 64, expires_in=300.0) -> Confirmation:
    return Confirmation(confirmation_id=cid, user_id=user, conversation_id="conv", plan_id="plan", plan_hash=plan_hash,
                        operations=({"op": "x"},), expires_at=time.time() + expires_in)


async def _tenants(schema) -> None:
    for tenant in (T, OTHER):
        await schema.execute(
            "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation,"
            " policy_version_id) VALUES ($1, 'g', 'active', 100, false, 'IRREVERSIBLE', 'p1') ON CONFLICT DO NOTHING",
            tenant, tenant=tenant)


@pytest.fixture
def stores(db_schema, run):
    from adapters.postgres.confirmations import PostgresConfirmationStore
    run(_tenants(db_schema))
    return {"memory": ConfirmationStoreImpl(), "postgres": PostgresConfirmationStore(db_schema.database())}


def _row(schema, run, cid):
    rows = run(schema.fetch("SELECT status, consumed_at, execution_id FROM pending_confirmations"
                            " WHERE confirmation_id = $1", cid, tenant=T))
    return rows[0] if rows else None


# --- the store over both implementations (suite 13; regression of certified S0–S11 behaviour) -----------------

@pytest.mark.parametrize("kind", ["memory", "postgres"])
def test_consume_exactly_once(stores, run, kind):
    store, cid = stores[kind], f"c-once-{kind}"
    run(store.save(_confirmation(cid), T, EXEC))
    assert run(store.consume(cid, tenant_id=T, user_id="golden-user", plan_hash="h" * 64)) == CONSUMED
    assert run(store.consume(cid, tenant_id=T, user_id="golden-user", plan_hash="h" * 64)) == MISMATCH


@pytest.mark.parametrize("kind", ["memory", "postgres"])
@pytest.mark.parametrize("case", ["wrong_user", "wrong_hash", "wrong_tenant", "unknown_id"])
def test_mismatch_consumes_nothing_and_a_genuine_consume_still_works(stores, run, kind, case, db_schema):
    store, cid = stores[kind], f"c-{case}-{kind}"
    run(store.save(_confirmation(cid), T, EXEC))
    args = {"tenant_id": T, "user_id": "golden-user", "plan_hash": "h" * 64}
    target = cid
    if case == "wrong_user":
        args["user_id"] = "someone"
    elif case == "wrong_hash":
        args["plan_hash"] = "x" * 64
    elif case == "wrong_tenant":
        args["tenant_id"] = OTHER
    else:
        target = "no-such-confirmation"
    assert run(store.consume(target, **args)) == MISMATCH
    if kind == "postgres":
        row = _row(db_schema, run, cid)
        assert row["status"] == "pending" and row["consumed_at"] is None
    assert run(store.consume(cid, tenant_id=T, user_id="golden-user", plan_hash="h" * 64)) == CONSUMED


@pytest.mark.parametrize("kind", ["memory", "postgres"])
def test_expired_is_never_consumed(stores, run, kind, db_schema):
    store, cid = stores[kind], f"c-expired-{kind}"
    run(store.save(_confirmation(cid, expires_in=-5), T, EXEC))
    assert run(store.consume(cid, tenant_id=T, user_id="golden-user", plan_hash="h" * 64)) == EXPIRED
    if kind == "postgres":
        row = _row(db_schema, run, cid)
        assert row["status"] != "consumed" and row["consumed_at"] is None


@pytest.mark.parametrize("kind", ["memory", "postgres"])
def test_rejected_cannot_be_consumed(stores, run, kind):
    store, cid = stores[kind], f"c-rejected-{kind}"
    run(store.save(_confirmation(cid), T, EXEC))
    assert run(store.reject(cid, tenant_id=T, user_id="golden-user")) is True
    assert run(store.consume(cid, tenant_id=T, user_id="golden-user", plan_hash="h" * 64)) == MISMATCH


@pytest.mark.parametrize("kind", ["memory", "postgres"])
def test_save_requires_tenant_and_execution(stores, run, kind):
    for tenant, execution in (("", EXEC), (T, "")):
        with pytest.raises(ValueError):
            run(stores[kind].save(_confirmation(f"c-req-{kind}-{tenant}-{execution}"), tenant, execution))


def test_stored_status_is_consumed_with_its_execution(stores, run, db_schema):
    store = stores["postgres"]
    run(store.save(_confirmation("c-stored"), T, EXEC))
    run(store.consume("c-stored", tenant_id=T, user_id="golden-user", plan_hash="h" * 64))
    row = _row(db_schema, run, "c-stored")
    assert (row["status"], row["execution_id"]) == ("consumed", EXEC) and row["consumed_at"] is not None


def test_twenty_concurrent_consumers_one_winner(db_schema, run):
    """Suite 13: real transactions, 20 consumers, exactly one CONSUMED (the certifier repeats this file 5 times)."""
    from adapters.postgres.confirmations import PostgresConfirmationStore
    run(_tenants(db_schema))
    store = PostgresConfirmationStore(db_schema.database())

    async def race(cid: str):
        await store.save(_confirmation(cid), T, EXEC)
        return await asyncio.gather(*(store.consume(cid, tenant_id=T, user_id="golden-user", plan_hash="h" * 64)
                                      for _ in range(20)))

    for i in range(3):
        results = run(race(f"c-race-{i}"))
        assert results.count(CONSUMED) == 1 and results.count(MISMATCH) == 19


def test_no_foreign_key_from_confirmations_to_runs(db_schema, run):
    """C20: the confirmation is saved at S10, before the run row exists."""
    refs = run(db_schema.fetch(
        "SELECT confrelid::regclass::text AS target FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
        " WHERE n.nspname = $1 AND c.contype = 'f' AND c.conrelid = 'pending_confirmations'::regclass", db_schema.name))
    assert all(not r["target"].endswith("execution_runs") for r in refs)


# --- C20: S12 entry checks the consumed confirmation against the run -----------------------------------------------

def _entry_state(confirmation_id: str | None):
    """A certified state (tests_golden/fixtures/certified.py) whose tenant is T, with a confirmation attached."""
    state = certified_state(tenant_id=T)
    if confirmation_id is None:
        return state
    conf = _confirmation(confirmation_id, plan_hash=state.execution_manifest.plan_hash)
    return dataclasses.replace(state, confirmation=ConfirmationOutcome(required=True, confirmation=conf))


def _save_and_consume(schema, run, state, *, execution_id=None, plan_hash=None, tenant=T, consume=True):
    from adapters.postgres.confirmations import PostgresConfirmationStore
    run(_tenants(schema))
    store = PostgresConfirmationStore(schema.database())
    conf = state.confirmation.confirmation
    stored = dataclasses.replace(conf, plan_hash=plan_hash or conf.plan_hash)
    run(store.save(stored, tenant, execution_id or state.plan.execution_id))
    if consume:
        assert run(store.consume(conf.confirmation_id, tenant_id=tenant, user_id=conf.user_id,
                                 plan_hash=stored.plan_hash)) == CONSUMED


def _denial(schema, run, state):
    from adapters.postgres.confirmation_records import PostgresConsumedConfirmationReader
    from engine.stages.s12_entry.confirmation import confirmation_denial
    return run(confirmation_denial(state, PostgresConsumedConfirmationReader(schema.database())))


def test_matching_consumed_confirmation_is_accepted(db_schema, run):
    state = _entry_state("c20-ok")
    _save_and_consume(db_schema, run, state)
    assert _denial(db_schema, run, state) is None
    run(assert_system_invariants(db_schema))


def test_no_confirmation_needed_reads_nothing():
    from engine.stages.s12_entry.confirmation import confirmation_denial

    class Exploding:
        async def read(self, confirmation_id, *, tenant_id):
            raise AssertionError("read without a required confirmation")

    assert asyncio.run(confirmation_denial(_entry_state(None), Exploding())) is None


@pytest.mark.parametrize("case", ["not_consumed", "other_execution", "other_plan_hash", "other_tenant", "missing_row"])
def test_mismatching_confirmation_is_denied(db_schema, run, case):
    state = _entry_state(f"c20-{case}")
    if case == "not_consumed":
        _save_and_consume(db_schema, run, state, consume=False)
    elif case == "other_execution":
        _save_and_consume(db_schema, run, state, execution_id="another-execution")
    elif case == "other_plan_hash":
        _save_and_consume(db_schema, run, state, plan_hash="0" * 64)
    elif case == "other_tenant":
        _save_and_consume(db_schema, run, state, tenant=OTHER)
    assert _denial(db_schema, run, state) == "confirmation_mismatch"


@pytest.mark.parametrize("reader", ["missing", "raising"])
def test_unreadable_store_fails_closed(reader):
    from engine.stages.s12_entry.confirmation import confirmation_denial

    class Raising:
        async def read(self, confirmation_id, *, tenant_id):
            raise ConnectionError("store down")

    state = _entry_state("c20-down")
    assert asyncio.run(confirmation_denial(state, None if reader == "missing" else Raising())) == "confirmation_unavailable"


def test_entry_check_writes_nothing(db_schema, run):
    state = _entry_state("c20-nowrite")
    _save_and_consume(db_schema, run, state)
    before = run(db_schema.fetchval("SELECT count(*) FROM pending_confirmations", tenant=T)), \
        run(db_schema.fetch("SELECT status, consumed_at FROM pending_confirmations WHERE confirmation_id = 'c20-nowrite'",
                            tenant=T))
    _denial(db_schema, run, state)
    after = run(db_schema.fetchval("SELECT count(*) FROM pending_confirmations", tenant=T)), \
        run(db_schema.fetch("SELECT status, consumed_at FROM pending_confirmations WHERE confirmation_id = 'c20-nowrite'",
                            tenant=T))
    assert [before[0], [dict(r) for r in before[1]]] == [after[0], [dict(r) for r in after[1]]]


def test_check_entry_applies_the_confirmation_check(db_schema, run):
    from adapters.postgres.confirmation_records import PostgresConsumedConfirmationReader
    from engine.stages.s12_entry.checks import check_entry
    from tests_golden.fixtures.certified import entry_readers
    state = _entry_state("c20-entry")
    _save_and_consume(db_schema, run, state, execution_id="another-execution")
    readers = entry_readers()
    decision = run(check_entry(state, confirmations=PostgresConsumedConfirmationReader(db_schema.database()), **readers))
    assert (decision.allowed, decision.reason) == (False, "confirmation_mismatch")
    good = _entry_state("c20-entry-ok")
    _save_and_consume(db_schema, run, good)
    decision = run(check_entry(good, confirmations=PostgresConsumedConfirmationReader(db_schema.database()), **readers))
    assert decision.allowed, decision.reason
