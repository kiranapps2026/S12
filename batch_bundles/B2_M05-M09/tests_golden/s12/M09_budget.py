"""M9 golden — BudgetReserver (gate commit F). Owner-pinned.

Gate v10: C3 (per step; availability = budget_pool − Σ cost of reserved/locked/committed in the current period; lock the
tenant row, insert only if available >= cost), C14 (a LOCKED reservation is only resolved by a probe/verification/
dead-letter outcome, never by a timer), C31 (BudgetReserver is the only writer of budget state; each operation is one
fenced_write and one legal transition with a reason), C33 (period start from database time, UTC; the step ↔ reservation
link in one transaction), suite 4; invariants I1, I2, I12 (non-dead-letter parts), I5.

Interface this file fixes (``adapters.postgres.budget_reserver``):
  * ``Reservation`` (frozen): ``reservation_id`` (None when exhausted), ``status``, ``reason`` (``"budget_exhausted"`` when
    exhausted, else None).
  * ``PostgresBudgetReserver(database)``, every write inside ``fenced_write`` for the holder's execution:
      ``async reserve(holder, *, user_id, step_id, cost) -> Reservation`` — insert ``reserved`` (logged
      ``None → reserved``, reason ``reserved``) and set ``execution_steps.reservation_id`` in the same transaction; a step
      that already has a live reservation gets that one back (idempotent); exhausted → nothing written.
      ``async lock(holder, reservation_id, *, reason, connection=None)``, ``async commit(...)``,
      ``async release(...)`` (same signature) — one Appendix A.3 transition each, validated with its reason
      (``engine.stages.s12_execute.transitions.validate``), logged; an illegal move raises ``IllegalStateTransition`` and
      writes nothing; a stale holder raises ``FencedOut`` and writes nothing. With ``connection`` (a connection inside the
      caller's ``fenced_write`` for the same holder) the move joins that transaction instead of opening its own: Appendix
      A.2 requires the step's ``pending → running`` and its reservation's ``reserved → locked`` in ONE transaction (I-3).
      ``async status(tenant_id, reservation_id) -> str | None``.
"""
from __future__ import annotations

import asyncio

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants

T = "golden-tenant"
RUNTIME = "runtime-A"


async def _seed(schema, tenant, *, pool, steps, execution=None, token=7, period="monthly"):
    execution = execution or f"e-{tenant}"
    await schema.execute(
        "INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation, policy_version_id,"
        " budget_period) VALUES ($1, 'g', 'active', $2, false, 'IRREVERSIBLE', 'p1', $3) ON CONFLICT DO NOTHING",
        tenant, pool, period, tenant=tenant)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ($1, $2, 'w')"
                         " ON CONFLICT DO NOTHING", f"ws-{tenant}", tenant, tenant=tenant)
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ($1, $2, 'active')"
                         " ON CONFLICT DO NOTHING", f"u-{tenant}", tenant, tenant=tenant)
    await schema.execute(
        "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,"
        " conversation_id, status, actor_type, actor_id, budget_spent) VALUES ($1, $1, 'tr', 'task', $2, $3, $4, 'conv',"
        " 'running', 'user', $2, 0)", execution, f"u-{tenant}", tenant, f"ws-{tenant}", tenant=tenant)
    await schema.execute(
        "INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id, fencing_token,"
        " checkpoint_sequence, updated_at) VALUES ($1, $2, $3, $4, 0, now())", execution, tenant, RUNTIME, token,
        tenant=tenant)
    for i in range(steps):
        await schema.execute(
            "INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, kernel_op_id,"
            " resolved_binding_id, effective_risk, effective_mutation, request_fingerprint, status, attempt)"
            " VALUES ($1, $2, $3, $4, 'op', 'b', 0.1, 'W', 'fp', 'pending', 0)",
            f"{execution}:s{i}", f"s{i}", execution, tenant, tenant=tenant)


def _holder(tenant, execution=None, token=7):
    from adapters.postgres.fencing import FenceHolder
    return FenceHolder(tenant_id=tenant, execution_id=execution or f"e-{tenant}", runtime_instance_id=RUNTIME, fence_token=token)


def _reserver(schema):
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    return PostgresBudgetReserver(schema.database())


async def _reserve(schema, tenant, step, cost, execution=None):
    execution = execution or f"e-{tenant}"
    return await _reserver(schema).reserve(_holder(tenant, execution), user_id=f"u-{tenant}",
                                           step_id=f"{execution}:{step}", cost=cost)


# --- paths ---------------------------------------------------------------------------------------------------------

def test_reserve_lock_commit(db_schema, run):
    tenant = "t-commit"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    r = run(_reserve(db_schema, tenant, "s0", 10))
    assert r.reservation_id and (r.status, r.reason) == ("reserved", None)
    linked = run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1", f"e-{tenant}:s0"))
    assert linked == r.reservation_id
    m = _reserver(db_schema)
    run(m.lock(_holder(tenant), r.reservation_id, reason="step_started"))
    run(m.commit(_holder(tenant), r.reservation_id, reason="step_completed"))
    assert run(m.status(tenant, r.reservation_id)) == "committed"
    logged = run(db_schema.fetch("SELECT from_state, to_state, reason FROM state_transitions"
                                 " WHERE entity_type = 'reservation' AND entity_id = $1 ORDER BY transition_id",
                                 r.reservation_id))
    assert [tuple(x) for x in logged] == [(None, "reserved", "reserved"), ("reserved", "locked", "step_started"),
                                          ("locked", "committed", "step_completed")]


@pytest.mark.parametrize("path", [("release", "preflight_failed"), ("lock", "step_started", "release", "step_failed"),
                                  ("lock", "step_started", "release", "probe_not_executed")])
def test_release_paths(db_schema, run, path):
    tenant = f"t-rel-{len(path)}-{path[-1]}"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    r = run(_reserve(db_schema, tenant, "s0", 10))
    m = _reserver(db_schema)
    for op, reason in zip(path[::2], path[1::2]):
        run(getattr(m, op)(_holder(tenant), r.reservation_id, reason=reason))
    assert run(m.status(tenant, r.reservation_id)) == "released"
    avail = run(db_schema.fetchval("SELECT count(*) FROM budget_reservations WHERE tenant_id = $1 AND status IN"
                                   " ('reserved','locked','committed')", tenant))
    assert avail == 0


def test_reserve_is_idempotent_per_step(db_schema, run):
    tenant = "t-idem"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    a, b = run(_reserve(db_schema, tenant, "s0", 10)), run(_reserve(db_schema, tenant, "s0", 10))
    assert a.reservation_id == b.reservation_id
    assert run(db_schema.fetchval("SELECT count(*) FROM budget_reservations WHERE tenant_id = $1", tenant)) == 1


@pytest.mark.parametrize("op,start", [("commit", ()), ("lock", ("lock",)), ("release", ("lock", "commit"))])
def test_illegal_moves_are_rejected_and_write_nothing(db_schema, run, op, start):
    from engine.stages.s12_execute.transitions import IllegalStateTransition
    tenant = f"t-illegal-{op}-{len(start)}"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    r = run(_reserve(db_schema, tenant, "s0", 10))
    m = _reserver(db_schema)
    reasons = {"lock": "step_started", "commit": "step_completed", "release": "step_failed"}
    for step in start:
        run(getattr(m, step)(_holder(tenant), r.reservation_id, reason=reasons[step]))
    before = run(m.status(tenant, r.reservation_id)), run(db_schema.fetchval("SELECT count(*) FROM state_transitions"))
    with pytest.raises(IllegalStateTransition):
        run(getattr(m, op)(_holder(tenant), r.reservation_id, reason=reasons[op]))
    assert (run(m.status(tenant, r.reservation_id)), run(db_schema.fetchval("SELECT count(*) FROM state_transitions"))) \
        == before


def test_lock_joins_the_callers_transaction(db_schema, run):
    """I-3: the step starts and its reservation locks together, or neither happens."""
    from adapters.postgres.fencing import fenced_write
    tenant = "t-join"
    run(_seed(db_schema, tenant, pool=100, steps=2))
    m = _reserver(db_schema)
    a = run(_reserve(db_schema, tenant, "s0", 5))
    b = run(_reserve(db_schema, tenant, "s1", 5))

    async def start(step, reservation_id, fail):
        async def write(c):
            await c.execute("UPDATE execution_steps SET status = 'running' WHERE tenant_id = $1 AND step_id = $2",
                            tenant, f"e-{tenant}:{step}")
            await m.lock(_holder(tenant), reservation_id, reason="step_started", connection=c)
            if fail:
                raise RuntimeError("crash after lock, before commit")
        await fenced_write(db_schema.database(), _holder(tenant), write)

    run(start("s0", a.reservation_id, fail=False))
    with pytest.raises(RuntimeError):
        run(start("s1", b.reservation_id, fail=True))
    rows = {r["step_id"]: (r["status"], r["res"]) for r in run(db_schema.fetch(
        "SELECT s.step_id, s.status, b.status AS res FROM execution_steps s JOIN budget_reservations b"
        " ON b.reservation_id = s.reservation_id WHERE s.tenant_id = $1", tenant))}
    assert rows == {f"e-{tenant}:s0": ("running", "locked"), f"e-{tenant}:s1": ("pending", "reserved")}


def test_a_disallowed_reason_is_rejected(db_schema, run):
    from engine.stages.s12_execute.transitions import IllegalStateTransition
    tenant = "t-reason"
    run(_seed(db_schema, tenant, pool=100, steps=1))
    r = run(_reserve(db_schema, tenant, "s0", 10))
    with pytest.raises(IllegalStateTransition):
        run(_reserver(db_schema).lock(_holder(tenant), r.reservation_id, reason="timer_expired"))
    assert run(_reserver(db_schema).status(tenant, r.reservation_id)) == "reserved"


def test_stale_holder_is_fenced_out(db_schema, run):
    from contracts.step_execution import FencedOut
    tenant = "t-fence"
    run(_seed(db_schema, tenant, pool=100, steps=2))
    with pytest.raises(FencedOut):
        run(_reserver(db_schema).reserve(_holder(tenant, token=6), user_id=f"u-{tenant}", step_id=f"e-{tenant}:s0", cost=5))
    assert run(db_schema.fetchval("SELECT count(*) FROM budget_reservations WHERE tenant_id = $1", tenant)) == 0
    r = run(_reserve(db_schema, tenant, "s1", 5))
    with pytest.raises(FencedOut):
        run(_reserver(db_schema).lock(_holder(tenant, token=6), r.reservation_id, reason="step_started"))
    assert run(_reserver(db_schema).status(tenant, r.reservation_id)) == "reserved"


# --- availability ---------------------------------------------------------------------------------------------------

def test_exhaustion_writes_nothing(db_schema, run):
    tenant = "t-exhaust"
    run(_seed(db_schema, tenant, pool=15, steps=2))
    assert run(_reserve(db_schema, tenant, "s0", 10)).reservation_id
    r = run(_reserve(db_schema, tenant, "s1", 10))
    assert (r.reservation_id, r.status, r.reason) == (None, None, "budget_exhausted")
    assert run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1", f"e-{tenant}:s1")) is None
    assert run(db_schema.fetchval("SELECT count(*) FROM budget_reservations WHERE tenant_id = $1", tenant)) == 1


def test_released_budget_is_available_again(db_schema, run):
    tenant = "t-again"
    run(_seed(db_schema, tenant, pool=10, steps=2))
    first = run(_reserve(db_schema, tenant, "s0", 10))
    run(_reserver(db_schema).release(_holder(tenant), first.reservation_id, reason="preflight_failed"))
    assert run(_reserve(db_schema, tenant, "s1", 10)).reservation_id


def test_only_the_current_period_counts(db_schema, run):
    tenant = "t-period"
    run(_seed(db_schema, tenant, pool=10, steps=2))
    run(db_schema.execute(
        "INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status,"
        " created_at) VALUES ('r-old', $1, $2, $3, $4, 10, 'committed',"
        " date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' - interval '1 second')",
        tenant, f"u-{tenant}", f"e-{tenant}", f"e-{tenant}:s0", tenant=tenant))
    assert run(_reserve(db_schema, tenant, "s1", 10)).reservation_id       # last month's use does not count
    run(db_schema.execute("UPDATE budget_reservations SET created_at = now() WHERE reservation_id = 'r-old'", tenant=tenant))
    run(db_schema.execute("UPDATE budget_reservations SET status = 'released' WHERE tenant_id = $1 AND reservation_id <> 'r-old'",
                          tenant, tenant=tenant))
    run(db_schema.execute("UPDATE execution_steps SET reservation_id = NULL WHERE step_id = $1", f"e-{tenant}:s1",
                          tenant=tenant))
    r = run(_reserve(db_schema, tenant, "s1", 10))                        # this month's use counts
    assert r.reason == "budget_exhausted"


def test_twenty_concurrent_reservations_never_over_reserve(db_schema, run):
    """Suite 4 (the certifier repeats this file 5 times): pool 50, 20 steps of cost 5 → exactly 10 reserved."""
    tenant = "t-race"
    run(_seed(db_schema, tenant, pool=50, steps=20, execution="e-race"))

    async def race():
        return await asyncio.gather(*(_reserve(db_schema, tenant, f"s{i}", 5, execution="e-race") for i in range(20)))

    results = run(race())
    assert sum(1 for r in results if r.reservation_id) == 10
    assert all(r.reason == "budget_exhausted" for r in results if not r.reservation_id)
    total = run(db_schema.fetchval("SELECT sum(cost) FROM budget_reservations WHERE tenant_id = $1", tenant))
    assert total == 50
    run(assert_system_invariants(db_schema))


# --- invariants and traps -------------------------------------------------------------------------------------------

def test_invariants_hold_after_a_full_lifecycle(db_schema, run):
    tenant = "t-inv"
    run(_seed(db_schema, tenant, pool=100, steps=3, execution="e-inv"))
    m = _reserver(db_schema)
    h = _holder(tenant, "e-inv")
    a = run(m.reserve(h, user_id=f"u-{tenant}", step_id="e-inv:s0", cost=5))
    b = run(m.reserve(h, user_id=f"u-{tenant}", step_id="e-inv:s1", cost=5))
    run(m.lock(h, a.reservation_id, reason="step_started"))
    run(m.commit(h, a.reservation_id, reason="step_completed"))
    run(db_schema.execute("UPDATE execution_steps SET status = 'running' WHERE step_id = 'e-inv:s0'", tenant=tenant))
    run(db_schema.execute("UPDATE execution_steps SET status = 'completed' WHERE step_id = 'e-inv:s0'", tenant=tenant))
    run(m.release(h, b.reservation_id, reason="preflight_failed"))
    run(db_schema.execute("UPDATE execution_steps SET status = 'cancelled', terminal_reason = 'preflight_failed'"
                          " WHERE step_id = 'e-inv:s1'", tenant=tenant))
    run(assert_system_invariants(db_schema))


def test_no_tenant_budget_table_and_no_timer_release():
    """C3 trap (no tenant_budget table) and C14 (no automatic release of LOCKED budget)."""
    from tests_golden.fixtures.code_scan import s12_files, string_literals
    texts = [t for p in s12_files() for _, t in string_literals(p)]
    assert not any("tenant_budget" in t for t in texts)
    assert not any("budget_reservations" in t and "locked" in t and "interval" in t for t in texts)
