"""Agent tests for M9 (never count for certification): refusals across executions, the fence on the join path, a
race on one step, cost validation, log provenance and the daily period, beyond the pinned golden M09."""
import asyncio

import pytest
from tests_golden.fixtures.db import GoldenSchema, golden_database_url, new_schema_name
from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M09_budget import _holder, _reserve, _reserver, _seed

from contracts.step_execution import FencedOut


@pytest.fixture(scope="module")
def db_schema(request):
    schema = GoldenSchema(golden_database_url(), new_schema_name(request.module.__name__))
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(schema.create())
        loop.run_until_complete(schema.migrate())
        schema.loop = loop
        yield schema
    finally:
        loop.run_until_complete(schema.drop())
        loop.close()


@pytest.fixture
def run(db_schema):
    return db_schema.loop.run_until_complete


def _count(schema, run, tenant):
    return run(schema.fetchval("SELECT count(*) FROM budget_reservations WHERE tenant_id = $1", tenant))


def test_a_step_of_another_execution_is_never_reserved(db_schema, run):
    tenant = "a-cross"
    run(_seed(db_schema, tenant, pool=100, steps=1, execution="e-cross-1"))
    run(_seed(db_schema, tenant, pool=100, steps=1, execution="e-cross-2"))
    with pytest.raises(LookupError):
        run(_reserver(db_schema).reserve(_holder(tenant, "e-cross-1"), user_id=f"u-{tenant}", step_id="e-cross-2:s0",
                                         cost=5))
    with pytest.raises(LookupError):
        run(_reserver(db_schema).reserve(_holder(tenant, "e-cross-1"), user_id=f"u-{tenant}", step_id="no-such-step",
                                         cost=5))
    assert _count(db_schema, run, tenant) == 0


def test_a_reservation_of_another_execution_is_never_moved(db_schema, run):
    tenant = "a-move"
    run(_seed(db_schema, tenant, pool=100, steps=1, execution="e-move-1"))
    run(_seed(db_schema, tenant, pool=100, steps=1, execution="e-move-2"))
    r = run(_reserve(db_schema, tenant, "s0", 5, execution="e-move-2"))
    with pytest.raises(LookupError):
        run(_reserver(db_schema).lock(_holder(tenant, "e-move-1"), r.reservation_id, reason="step_started"))
    assert run(_reserver(db_schema).status(tenant, r.reservation_id)) == "reserved"


def test_joining_a_transaction_still_checks_the_fence(db_schema, run):
    from adapters.postgres.fencing import fenced_write
    tenant = "a-join-fence"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    r = run(_reserve(db_schema, tenant, "s0", 5))

    async def write(c):
        await _reserver(db_schema).lock(_holder(tenant, token=6), r.reservation_id, reason="step_started", connection=c)

    with pytest.raises(FencedOut):
        run(fenced_write(db_schema.database(), _holder(tenant), write))
    assert run(_reserver(db_schema).status(tenant, r.reservation_id)) == "reserved"


def test_one_step_reserved_concurrently_gets_exactly_one_reservation(db_schema, run):
    tenant = "a-same-step"
    run(_seed(db_schema, tenant, pool=100, steps=1))

    async def race():
        return await asyncio.gather(*(_reserve(db_schema, tenant, "s0", 5) for _ in range(8)))

    results = run(race())
    assert len({r.reservation_id for r in results}) == 1 and _count(db_schema, run, tenant) == 1
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("cost", [-1, 2.5, "5", True])
def test_an_invalid_cost_is_refused(db_schema, run, cost):
    with pytest.raises(ValueError):
        run(_reserver(db_schema).reserve(_holder("a-cost"), user_id="u", step_id="s", cost=cost))


def test_a_zero_cost_step_is_reservable_on_an_exhausted_pool(db_schema, run):
    tenant = "a-zero"
    run(_seed(db_schema, tenant, pool=5, steps=2))
    assert run(_reserve(db_schema, tenant, "s0", 5)).reservation_id
    assert run(_reserve(db_schema, tenant, "s1", 0)).reservation_id


def test_every_log_row_names_the_holder(db_schema, run):
    tenant = "a-log"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    r = run(_reserve(db_schema, tenant, "s0", 5))
    run(_reserver(db_schema).lock(_holder(tenant), r.reservation_id, reason="step_started"))
    rows = run(db_schema.fetch("SELECT runtime_instance_id, fence_token, execution_id FROM state_transitions"
                               " WHERE entity_type = 'reservation' AND entity_id = $1", r.reservation_id))
    assert [tuple(x) for x in rows] == [("runtime-A", 7, f"e-{tenant}")] * 2


def test_a_daily_period_forgets_yesterday(db_schema, run):
    tenant = "a-daily"
    run(_seed(db_schema, tenant, pool=10, steps=2, period="daily"))
    run(db_schema.execute(
        "INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status,"
        " created_at) VALUES ('r-yesterday', $1, $2, $3, $4, 10, 'committed',"
        " date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' - interval '1 second')",
        tenant, f"u-{tenant}", f"e-{tenant}", f"e-{tenant}:s0", tenant=tenant))
    assert run(_reserve(db_schema, tenant, "s1", 10)).reservation_id


def test_an_unknown_reservation_is_an_error_and_writes_nothing(db_schema, run):
    tenant = "a-unknown"
    run(_seed(db_schema, tenant, pool=10, steps=1))
    before = run(db_schema.fetchval("SELECT count(*) FROM state_transitions"))
    with pytest.raises(LookupError):
        run(_reserver(db_schema).release(_holder(tenant), "no-such-reservation", reason="preflight_failed"))
    assert run(db_schema.fetchval("SELECT count(*) FROM state_transitions")) == before
