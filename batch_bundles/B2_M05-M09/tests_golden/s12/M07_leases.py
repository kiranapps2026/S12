"""M7 golden — leases, fencing, ownership (gate commit E part 1). Owner-pinned.

Gate v10: C5 (acquisition transaction, capacity, current_load), C25 (one sequence, per-execution fence), C26 (stored
lease status, usable = active AND expires_at > now(), expiry by the next acquisition, no renewal after expiry), suite 5;
WORKER_LIFECYCLE §14 (ownership transfer: strictly greater token, compare-and-set); invariants I5, I7, I8.

Interface this file fixes (``adapters.postgres.leases``):
  * ``Lease`` (frozen): ``lease_id``, ``tenant_id``, ``worker_id``, ``execution_id``, ``fence_token``.
  * ``PostgresLeaseManager(database)``:
      ``async acquire(*, tenant_id, worker_id, execution_id, runtime_instance_id, ttl_s) -> Lease | None`` — ONE
      transaction: lock the worker row (FOR UPDATE), expire its stale leases (``active → expired``, reason
      ``ttl_elapsed``, logged), count its usable leases, and only if the count is below ``capacity`` and the worker is
      ``ACTIVE`` and the execution has no other usable lease (one owner at a time; takeover only after the old lease
      expired or was released): take the token from ``fence_token_seq``, insert the lease ``active`` (logged ``None → active``,
      ``acquired``), set ``workers.current_load`` to the new count and ``workers.lease_epoch`` to the token, and set
      ``execution_ownership`` (worker_id, lease_id, runtime_instance_id, fencing_token) by compare-and-set to the new,
      strictly greater token. ``None`` when at capacity or not ACTIVE (nothing written).
      ``async renew(lease, *, runtime_instance_id, ttl_s) -> Lease`` — only while usable; new token from the sequence;
      ownership compare-and-set from the old token; logged ``active → active`` (``renewed``); otherwise ``LeaseLost``.
      ``async release(lease, *, reason)`` — ``active → released`` with ``work_complete``, ``fenced_out`` or
      ``run_terminal``; decrements ``current_load`` in the same transaction.
  * ``LeaseLost`` (Exception).
Every lease log row that issues a token (``None → active``, ``active → active``) carries that new token in
``state_transitions.fence_token`` (I8 reads the issue order from the log).
Writes for the execution use ``fenced_write`` with ``FenceHolder(..., fence_token=lease.fence_token)``.
"""
from __future__ import annotations

import asyncio

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants

T = "golden-tenant"
TTL = 30


async def _seed(schema, *, workers: dict[str, int], executions: list[str], state: str = "ACTIVE") -> None:
    await schema.execute(
        "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation, policy_version_id)"
        " VALUES ($1, 'g', 'active', 100, false, 'IRREVERSIBLE', 'p1') ON CONFLICT DO NOTHING", T, tenant=T)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ('golden-ws', $1, 'w')"
                         " ON CONFLICT DO NOTHING", T, tenant=T)
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ('golden-user', $1, 'active')"
                         " ON CONFLICT DO NOTHING", T, tenant=T)
    for worker_id, capacity in workers.items():
        await schema.execute(
            "INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile, state, capacity)"
            " VALUES ($1, $2, 'golden-ws', 'golden', '{}'::jsonb, $3, $4)", worker_id, T, state, capacity, tenant=T)
    for execution_id in executions:
        await schema.execute(
            "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,"
            " conversation_id, status, actor_type, actor_id, budget_spent) VALUES ($1, $1, 'tr', 'task', 'golden-user',"
            " $2, 'golden-ws', 'conv', 'running', 'user', 'golden-user', 0)", execution_id, T, tenant=T)
        await schema.execute(
            "INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id, fencing_token,"
            " checkpoint_sequence, updated_at) VALUES ($1, $2, 'admission', 0, 0, now())", execution_id, T, tenant=T)


def _manager(schema):
    from adapters.postgres.leases import PostgresLeaseManager
    return PostgresLeaseManager(schema.database())


async def _acquire(schema, worker, execution, runtime="runtime-A", ttl=TTL):
    return await _manager(schema).acquire(tenant_id=T, worker_id=worker, execution_id=execution,
                                          runtime_instance_id=runtime, ttl_s=ttl)


async def _load(schema, worker):
    row = (await schema.fetch("SELECT current_load, lease_epoch FROM workers WHERE worker_id = $1", worker))[0]
    active = await schema.fetchval("SELECT count(*) FROM worker_leases WHERE worker_id = $1 AND status = 'active'", worker)
    return row["current_load"], active, row["lease_epoch"]


async def _write_ok(schema, lease, runtime="runtime-A") -> bool:
    from adapters.postgres.fencing import FenceHolder, fenced_write
    from contracts.step_execution import FencedOut
    holder = FenceHolder(tenant_id=T, execution_id=lease.execution_id, runtime_instance_id=runtime,
                         fence_token=lease.fence_token)

    async def write(connection):
        await connection.execute("UPDATE execution_runs SET budget_spent = budget_spent + 1"
                                 " WHERE tenant_id = $1 AND execution_id = $2", T, lease.execution_id)
    try:
        await fenced_write(schema.database(), holder, write)
        return True
    except FencedOut:
        return False


# --- acquisition, capacity, current_load --------------------------------------------------------------------------

def test_acquire_sets_lease_ownership_and_load(db_schema, run):
    run(_seed(db_schema, workers={"w-basic": 1}, executions=["e-basic"]))
    lease = run(_acquire(db_schema, "w-basic", "e-basic"))
    assert lease is not None and lease.fence_token > 0
    row = run(db_schema.fetch("SELECT status, fence_token, execution_id FROM worker_leases WHERE lease_id = $1",
                              lease.lease_id))[0]
    assert (row["status"], row["fence_token"], row["execution_id"]) == ("active", lease.fence_token, "e-basic")
    owner = run(db_schema.fetch("SELECT worker_id, lease_id, runtime_instance_id, fencing_token FROM execution_ownership"
                                " WHERE execution_id = 'e-basic'"))[0]
    assert tuple(owner) == ("w-basic", lease.lease_id, "runtime-A", lease.fence_token)
    assert run(_load(db_schema, "w-basic")) == (1, 1, lease.fence_token)
    assert run(_write_ok(db_schema, lease))
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("capacity", [1, 3])
def test_capacity_is_never_exceeded_under_concurrency(db_schema, run, capacity):
    worker = f"w-cap-{capacity}"
    executions = [f"e-cap-{capacity}-{i}" for i in range(12)]
    run(_seed(db_schema, workers={worker: capacity}, executions=executions))

    async def race():
        return await asyncio.gather(*(_acquire(db_schema, worker, e, runtime=f"rt-{e}") for e in executions))

    leases = run(race())
    granted = [lease for lease in leases if lease is not None]
    assert len(granted) == capacity
    assert run(_load(db_schema, worker))[:2] == (capacity, capacity)
    tokens = [lease.fence_token for lease in granted]
    assert len(set(tokens)) == capacity
    run(assert_system_invariants(db_schema))


def test_release_frees_capacity(db_schema, run):
    run(_seed(db_schema, workers={"w-rel": 1}, executions=["e-rel-1", "e-rel-2"]))
    first = run(_acquire(db_schema, "w-rel", "e-rel-1"))
    assert run(_acquire(db_schema, "w-rel", "e-rel-2")) is None
    run(_manager(db_schema).release(first, reason="work_complete"))
    assert run(_load(db_schema, "w-rel"))[:2] == (0, 0)
    second = run(_acquire(db_schema, "w-rel", "e-rel-2"))
    assert second is not None and second.fence_token > first.fence_token
    run(assert_system_invariants(db_schema))


def test_only_active_workers_are_leased(db_schema, run):
    run(_seed(db_schema, workers={"w-draining": 1}, executions=["e-draining"], state="DRAINING"))
    assert run(_acquire(db_schema, "w-draining", "e-draining")) is None
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE worker_id = 'w-draining'")) == 0


# --- tokens and fencing -------------------------------------------------------------------------------------------

def test_renewal_takes_a_new_larger_token_and_keeps_writing(db_schema, run):
    run(_seed(db_schema, workers={"w-renew": 1}, executions=["e-renew"]))
    lease = run(_acquire(db_schema, "w-renew", "e-renew"))
    renewed = run(_manager(db_schema).renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL))
    assert renewed.lease_id == lease.lease_id and renewed.fence_token > lease.fence_token
    assert run(_write_ok(db_schema, renewed)) and not run(_write_ok(db_schema, lease))
    assert run(_load(db_schema, "w-renew")) == (1, 1, renewed.fence_token)
    run(assert_system_invariants(db_schema))


def test_renewing_one_lease_never_fences_other_executions_on_the_worker(db_schema, run):
    """C25: the fence is per execution; with capacity 3, renewing A must not fence out B or C."""
    run(_seed(db_schema, workers={"w-multi": 3}, executions=["e-m-a", "e-m-b", "e-m-c"]))
    a, b, c = (run(_acquire(db_schema, "w-multi", e)) for e in ("e-m-a", "e-m-b", "e-m-c"))
    run(_manager(db_schema).renew(a, runtime_instance_id="runtime-A", ttl_s=TTL))
    assert run(_write_ok(db_schema, b)) and run(_write_ok(db_schema, c))


def test_takeover_by_another_worker_gets_a_larger_token_and_fences_the_old_owner(db_schema, run):
    run(_seed(db_schema, workers={"w-old": 1, "w-new": 1}, executions=["e-take"]))
    old = run(_acquire(db_schema, "w-old", "e-take", runtime="runtime-old", ttl=1))
    run(asyncio.sleep(1.3))
    new = run(_acquire(db_schema, "w-new", "e-take", runtime="runtime-new"))
    assert new is not None and new.fence_token > old.fence_token
    assert not run(_write_ok(db_schema, old, runtime="runtime-old"))
    assert run(_write_ok(db_schema, new, runtime="runtime-new"))
    run(assert_system_invariants(db_schema))


def test_a_live_execution_cannot_be_taken_over(db_schema, run):
    """One owner at a time (WORKER_LIFECYCLE §14 failover, gate suite 17): while its lease is usable, no other Worker
    Runtime may lease the execution, and ownership is unchanged."""
    run(_seed(db_schema, workers={"w-live-a": 1, "w-live-b": 1}, executions=["e-live"]))
    held = run(_acquire(db_schema, "w-live-a", "e-live", runtime="runtime-a"))
    assert run(_acquire(db_schema, "w-live-b", "e-live", runtime="runtime-b")) is None
    owner = run(db_schema.fetch("SELECT worker_id, runtime_instance_id, fencing_token FROM execution_ownership"
                                " WHERE execution_id = 'e-live'"))[0]
    assert tuple(owner) == ("w-live-a", "runtime-a", held.fence_token)
    assert run(_load(db_schema, "w-live-b"))[:2] == (0, 0) and run(_write_ok(db_schema, held, runtime="runtime-a"))
    run(assert_system_invariants(db_schema))


def test_tokens_strictly_increase_per_worker_and_per_execution(db_schema, run):
    run(_seed(db_schema, workers={"w-seq-1": 1, "w-seq-2": 1}, executions=["e-seq-1", "e-seq-2"]))
    m = _manager(db_schema)
    tokens = []
    for worker, execution in (("w-seq-1", "e-seq-1"), ("w-seq-2", "e-seq-2")):
        lease = run(_acquire(db_schema, worker, execution))
        tokens.append(lease.fence_token)
        lease = run(m.renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL))
        tokens.append(lease.fence_token)
        run(m.release(lease, reason="work_complete"))
    lease = run(_acquire(db_schema, "w-seq-1", "e-seq-2"))
    tokens.append(lease.fence_token)
    assert tokens == sorted(tokens) and len(set(tokens)) == len(tokens)
    run(assert_system_invariants(db_schema))


# --- expiry (C26) --------------------------------------------------------------------------------------------------

def test_expired_lease_is_transitioned_by_the_next_acquisition(db_schema, run):
    run(_seed(db_schema, workers={"w-exp": 1}, executions=["e-exp-1", "e-exp-2"]))
    stale = run(_acquire(db_schema, "w-exp", "e-exp-1", ttl=1))
    run(asyncio.sleep(1.3))
    fresh = run(_acquire(db_schema, "w-exp", "e-exp-2"))
    assert fresh is not None
    status = run(db_schema.fetchval("SELECT status FROM worker_leases WHERE lease_id = $1", stale.lease_id))
    assert status == "expired" and run(_load(db_schema, "w-exp"))[:2] == (1, 1)
    logged = run(db_schema.fetch("SELECT from_state, to_state, reason FROM state_transitions WHERE entity_type = 'lease'"
                                 " AND entity_id = $1 ORDER BY transition_id", stale.lease_id))
    assert [tuple(r) for r in logged] == [(None, "active", "acquired"), ("active", "expired", "ttl_elapsed")]
    run(assert_system_invariants(db_schema))


def test_renewal_after_expiry_is_rejected(db_schema, run):
    from adapters.postgres.leases import LeaseLost
    run(_seed(db_schema, workers={"w-late": 1}, executions=["e-late"]))
    lease = run(_acquire(db_schema, "w-late", "e-late", ttl=1))
    run(asyncio.sleep(1.3))
    with pytest.raises(LeaseLost):
        run(_manager(db_schema).renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL))
    assert run(db_schema.fetchval("SELECT fencing_token FROM execution_ownership WHERE execution_id = 'e-late'")) \
        == lease.fence_token


def test_renewal_by_a_released_holder_is_rejected(db_schema, run):
    from adapters.postgres.leases import LeaseLost
    run(_seed(db_schema, workers={"w-gone": 1}, executions=["e-gone"]))
    m = _manager(db_schema)
    lease = run(_acquire(db_schema, "w-gone", "e-gone"))
    run(m.release(lease, reason="run_terminal"))
    with pytest.raises(LeaseLost):
        run(m.renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL))


def test_stale_owner_writes_affect_zero_rows(db_schema, run):
    run(_seed(db_schema, workers={"w-stale": 1, "w-stale-2": 1}, executions=["e-stale"]))
    old = run(_acquire(db_schema, "w-stale", "e-stale", runtime="runtime-old", ttl=1))
    run(asyncio.sleep(1.3))
    run(_acquire(db_schema, "w-stale-2", "e-stale", runtime="runtime-new"))
    before = run(db_schema.fetchval("SELECT budget_spent FROM execution_runs WHERE execution_id = 'e-stale'"))
    assert not run(_write_ok(db_schema, old, runtime="runtime-old"))
    assert run(db_schema.fetchval("SELECT budget_spent FROM execution_runs WHERE execution_id = 'e-stale'")) == before


def test_lease_moves_are_logged_with_reasons(db_schema, run):
    run(_seed(db_schema, workers={"w-log": 1}, executions=["e-log"]))
    m = _manager(db_schema)
    lease = run(_acquire(db_schema, "w-log", "e-log"))
    lease = run(m.renew(lease, runtime_instance_id="runtime-A", ttl_s=TTL))
    run(m.release(lease, reason="work_complete"))
    logged = run(db_schema.fetch("SELECT from_state, to_state, reason FROM state_transitions WHERE entity_type = 'lease'"
                                 " AND entity_id = $1 ORDER BY transition_id", lease.lease_id))
    assert [tuple(r) for r in logged] == [(None, "active", "acquired"), ("active", "active", "renewed"),
                                          ("active", "released", "work_complete")]
    run(assert_system_invariants(db_schema))
