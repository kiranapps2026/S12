"""Agent tests for M7 (never count for certification): races, negative paths and tenant isolation of the lease
manager that the pinned golden M07 does not fix. Needs TEST_DATABASE_URL (a superuser), like the golden tests."""
import asyncio

import pytest
from tests_golden.fixtures.db import GoldenSchema, golden_database_url, new_schema_name
from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M07_leases import TTL, T, _acquire, _load, _manager, _seed, _write_ok

from adapters.postgres.leases import LeaseLost
from engine.stages.s12_execute.transitions import IllegalStateTransition


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


def _lease_log(schema, run, lease_id):
    rows = run(schema.fetch("SELECT from_state, to_state, reason FROM state_transitions WHERE entity_type = 'lease'"
                            " AND entity_id = $1 ORDER BY transition_id", lease_id))
    return [tuple(r) for r in rows]


# --- races ---------------------------------------------------------------------------------------------------------

def test_one_execution_raced_on_many_workers_gets_exactly_one_owner(db_schema, run):
    workers = {f"w-race-{i}": 1 for i in range(6)}
    run(_seed(db_schema, workers=workers, executions=["e-race"]))
    async def race():
        return await asyncio.gather(*(_acquire(db_schema, w, "e-race", runtime=f"rt-{w}") for w in workers))

    leases = run(race())
    granted = [lease for lease in leases if lease is not None]
    assert len(granted) == 1
    owner = run(db_schema.fetch("SELECT worker_id, lease_id, fencing_token FROM execution_ownership"
                                " WHERE execution_id = 'e-race'"))[0]
    assert tuple(owner) == (granted[0].worker_id, granted[0].lease_id, granted[0].fence_token)
    run(assert_system_invariants(db_schema))


def test_renewals_and_acquisitions_on_one_worker_interleave_without_deadlock(db_schema, run):
    executions = [f"e-mix-{i}" for i in range(6)]
    run(_seed(db_schema, workers={"w-mix": 2, "w-mix-other": 2}, executions=executions))
    held = run(_acquire(db_schema, "w-mix", executions[0]))
    m = _manager(db_schema)

    async def churn():
        lease = held
        for i in range(1, len(executions)):
            lease, taken, stolen = await asyncio.gather(
                m.renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL),
                _acquire(db_schema, "w-mix", executions[i]),
                _acquire(db_schema, "w-mix-other", executions[0]))   # still live on w-mix: refused
            assert taken is not None and stolen is None
            await m.release(taken, reason="work_complete")
        return lease

    last = run(asyncio.wait_for(churn(), timeout=30))
    assert run(_write_ok(db_schema, last))
    assert run(_load(db_schema, "w-mix-other"))[:2] == (0, 0)
    run(assert_system_invariants(db_schema))


def test_the_same_lease_renewed_twice_at_once_succeeds_once(db_schema, run):
    run(_seed(db_schema, workers={"w-twice": 1}, executions=["e-twice"]))
    lease = run(_acquire(db_schema, "w-twice", "e-twice"))
    m = _manager(db_schema)
    async def race():
        return await asyncio.gather(*(m.renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL) for _ in range(2)),
                                    return_exceptions=True)

    results = run(race())
    assert sorted(type(r).__name__ for r in results) == ["Lease", "LeaseLost"]
    renewed = next(r for r in results if not isinstance(r, Exception))
    assert run(_write_ok(db_schema, renewed)) and not run(_write_ok(db_schema, lease))
    run(assert_system_invariants(db_schema))


# --- renewal is only for the current owner ---------------------------------------------------------------------------

def test_renewal_from_another_runtime_is_rejected_and_writes_nothing(db_schema, run):
    run(_seed(db_schema, workers={"w-rt": 1}, executions=["e-rt"]))
    lease = run(_acquire(db_schema, "w-rt", "e-rt"))
    with pytest.raises(LeaseLost):
        run(_manager(db_schema).renew(lease, runtime_instance_id="runtime-intruder", ttl_s=TTL))
    assert run(db_schema.fetchval("SELECT fencing_token FROM execution_ownership WHERE execution_id = 'e-rt'")) \
        == lease.fence_token
    assert _lease_log(db_schema, run, lease.lease_id) == [(None, "active", "acquired")]


def test_a_superseded_lease_cannot_be_renewed_after_takeover(db_schema, run):
    run(_seed(db_schema, workers={"w-sup-old": 1, "w-sup-new": 1}, executions=["e-sup"]))
    old = run(_acquire(db_schema, "w-sup-old", "e-sup", runtime="runtime-old", ttl=1))
    run(asyncio.sleep(1.3))
    new = run(_acquire(db_schema, "w-sup-new", "e-sup", runtime="runtime-new"))
    with pytest.raises(LeaseLost):
        run(_manager(db_schema).renew(old, runtime_instance_id="runtime-old", ttl_s=TTL))
    assert run(_write_ok(db_schema, new, runtime="runtime-new"))
    # The fenced-out holder releases its lapsed lease; the old worker's capacity comes back.
    assert run(_manager(db_schema).release(old, reason="fenced_out")) is True
    assert run(_load(db_schema, "w-sup-old"))[:2] == (0, 0)
    run(assert_system_invariants(db_schema))


def test_a_draining_worker_still_renews_its_in_flight_lease(db_schema, run):
    run(_seed(db_schema, workers={"w-drain": 1}, executions=["e-drain"]))
    lease = run(_acquire(db_schema, "w-drain", "e-drain"))
    run(db_schema.execute("UPDATE workers SET state = 'DRAINING' WHERE worker_id = 'w-drain'"))
    renewed = run(_manager(db_schema).renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL))
    assert renewed.fence_token > lease.fence_token and run(_write_ok(db_schema, renewed))


def test_an_acquisition_on_a_draining_worker_still_expires_its_lapsed_leases(db_schema, run):
    run(_seed(db_schema, workers={"w-drain-exp": 1}, executions=["e-drain-exp-1", "e-drain-exp-2"]))
    stale = run(_acquire(db_schema, "w-drain-exp", "e-drain-exp-1", ttl=1))
    run(db_schema.execute("UPDATE workers SET state = 'DRAINING' WHERE worker_id = 'w-drain-exp'"))
    run(asyncio.sleep(1.3))
    assert run(_acquire(db_schema, "w-drain-exp", "e-drain-exp-2")) is None
    assert run(_load(db_schema, "w-drain-exp"))[:2] == (0, 0)
    assert _lease_log(db_schema, run, stale.lease_id)[-1] == ("active", "expired", "ttl_elapsed")
    run(assert_system_invariants(db_schema))


# --- release ---------------------------------------------------------------------------------------------------------

def test_release_happens_once(db_schema, run):
    run(_seed(db_schema, workers={"w-once": 1}, executions=["e-once"]))
    lease = run(_acquire(db_schema, "w-once", "e-once"))
    m = _manager(db_schema)
    assert run(m.release(lease, reason="work_complete")) is True
    assert run(m.release(lease, reason="work_complete")) is False
    assert _lease_log(db_schema, run, lease.lease_id) == [(None, "active", "acquired"),
                                                          ("active", "released", "work_complete")]
    run(assert_system_invariants(db_schema))


def test_an_expired_lease_is_not_released(db_schema, run):
    run(_seed(db_schema, workers={"w-exp-rel": 1}, executions=["e-exp-rel-1", "e-exp-rel-2"]))
    stale = run(_acquire(db_schema, "w-exp-rel", "e-exp-rel-1", ttl=1))
    run(asyncio.sleep(1.3))
    fresh = run(_acquire(db_schema, "w-exp-rel", "e-exp-rel-2"))
    assert run(_manager(db_schema).release(stale, reason="fenced_out")) is False
    assert run(db_schema.fetchval("SELECT status FROM worker_leases WHERE lease_id = $1", stale.lease_id)) == "expired"
    assert run(_load(db_schema, "w-exp-rel")) == (1, 1, fresh.fence_token)
    run(assert_system_invariants(db_schema))


def test_an_illegal_release_reason_is_refused_and_nothing_changes(db_schema, run):
    run(_seed(db_schema, workers={"w-bad": 1}, executions=["e-bad"]))
    lease = run(_acquire(db_schema, "w-bad", "e-bad"))
    with pytest.raises(IllegalStateTransition):
        run(_manager(db_schema).release(lease, reason="ttl_elapsed"))
    assert run(db_schema.fetchval("SELECT status FROM worker_leases WHERE lease_id = $1", lease.lease_id)) == "active"
    assert run(_load(db_schema, "w-bad"))[:2] == (1, 1)


# --- refusals --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ttl", [0, -1])
def test_a_non_positive_ttl_is_refused(db_schema, run, ttl):
    with pytest.raises(ValueError):
        run(_manager(db_schema).acquire(tenant_id=T, worker_id="w-any", execution_id="e-any",
                                        runtime_instance_id="runtime-A", ttl_s=ttl))


def test_an_execution_without_ownership_record_is_an_error_and_nothing_is_leased(db_schema, run):
    run(_seed(db_schema, workers={"w-noown": 1}, executions=["e-noown"]))
    run(db_schema.execute("DELETE FROM execution_ownership WHERE execution_id = 'e-noown'"))
    with pytest.raises(LookupError):
        run(_acquire(db_schema, "w-noown", "e-noown"))
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE worker_id = 'w-noown'")) == 0
    assert run(_load(db_schema, "w-noown"))[:2] == (0, 0)


def test_a_terminal_run_is_never_leased(db_schema, run):
    run(_seed(db_schema, workers={"w-term": 1}, executions=["e-term"]))
    run(db_schema.execute("UPDATE execution_runs SET status = 'completed' WHERE execution_id = 'e-term'"))
    assert run(_acquire(db_schema, "w-term", "e-term")) is None
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = 'e-term'")) == 0


def test_another_tenants_worker_is_invisible(db_schema, run):
    other = "agent-other-tenant"
    run(_seed(db_schema, workers={}, executions=["e-foreign"]))
    run(db_schema.execute(
        "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation,"
        " policy_version_id) VALUES ($1, 'o', 'active', 100, false, 'IRREVERSIBLE', 'p1')", other))
    run(db_schema.execute("INSERT INTO workers (worker_id, tenant_id, worker_class, capability_profile, state, capacity)"
                          " VALUES ('w-foreign', $1, 'golden', '{}'::jsonb, 'ACTIVE', 1)", other))
    assert run(_acquire(db_schema, "w-foreign", "e-foreign")) is None
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE worker_id = 'w-foreign'")) == 0
