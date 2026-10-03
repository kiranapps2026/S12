"""DEF-006: admission gate 10 (``budget_available``) must use the same arithmetic as the reserve step.

``PostgresAdmissionSnapshot`` used ``execution_steps.effective_risk`` (a 0..1 risk score) as the step's cost and
compared it with the raw ``tenants.budget_pool``, ignoring what the period's reservations already hold. The gate must
instead say whether the reserve step (``PostgresBudgetReserver.reserve``) would succeed:

  * cost      = the plan step's ``cost`` in the frozen plan (``execution_plans.canonical_plan``);
  * available = ``adapters.postgres.budget.AVAILABLE_SQL`` (pool minus reserved/locked/committed reservations created
                since the period start, database UTC);
  * True when available >= cost, or when the step already holds a live (reserved/locked) reservation, which reserve
    returns as it is;
  * False (fail closed) when the execution or the step is unknown.

Needs real PostgreSQL (TEST_DATABASE_URL), like every tests_agent/ file; reuses the golden M12 helpers and fixtures
read-only. It lives here, not under tests/ (OWN-11) and not under tests_golden/ (pinned).
"""
from __future__ import annotations

import uuid

from tests_golden.conftest import db_schema, run  # noqa: F401 - fixtures
from tests_golden.s12.M12_loop import _admit, _order, _state


def _snapshot(schema, run, tenant, execution, plan_step_id):  # noqa: F811
    from adapters.postgres.admission_snapshot import PostgresAdmissionSnapshot
    return run(PostgresAdmissionSnapshot(schema.database())(tenant, execution, plan_step_id))


def _cost(state, plan_step_id):
    return next(s.cost for s in state.plan.plan.steps if s.id == plan_step_id)


def _reservation(schema, run, state, tenant, execution, plan_step_id, cost, status, *, link=False):  # noqa: F811
    """Insert one reservation row directly (no fence holder needed); optionally link it to its step."""
    rid = str(uuid.uuid4())
    step_id = f"{execution}:{plan_step_id}"
    run(schema.execute(
        "INSERT INTO budget_reservations (reservation_id, tenant_id, user_id, execution_id, step_id, cost, status)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7)", rid, tenant, state.execution_context.user_id, execution, step_id, cost,
        status, tenant=tenant))
    if link:
        run(schema.execute("UPDATE execution_steps SET reservation_id = $2 WHERE step_id = $1", step_id, rid,
                           tenant=tenant))
    return rid


def _admitted(schema, run, name, *, pool):  # noqa: F811
    state = _state(f"unit-def006-{name}", f"def006{name}")
    tenant, execution = _admit(schema, run, state, budget_pool=pool)
    first = _order(state)[0]
    assert _cost(state, first) >= 2, "the certified chain's first step must cost at least 2 for these cases"
    return state, tenant, execution, first


def test_the_gate_passes_when_the_pool_covers_the_step(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "healthy", pool=1000)
    assert _snapshot(db_schema, run, tenant, execution, first).budget_available is True


def test_the_gate_passes_when_the_pool_exactly_covers_the_step(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "exact", pool=0)
    run(db_schema.execute("UPDATE tenants SET budget_pool = $2 WHERE tenant_id = $1", tenant, _cost(state, first),
                          tenant=tenant))
    assert _snapshot(db_schema, run, tenant, execution, first).budget_available is True


def test_the_gate_fails_when_a_positive_pool_is_below_the_step_cost(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "below", pool=0)
    run(db_schema.execute("UPDATE tenants SET budget_pool = $2 WHERE tenant_id = $1", tenant,
                          _cost(state, first) - 1, tenant=tenant))
    assert _snapshot(db_schema, run, tenant, execution, first).budget_available is False


def test_the_gate_counts_the_periods_reservations(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "spent", pool=0)
    cost = _cost(state, first)
    run(db_schema.execute("UPDATE tenants SET budget_pool = $2 WHERE tenant_id = $1", tenant, 10 * cost,
                          tenant=tenant))
    other = _order(state)[-1]
    _reservation(db_schema, run, state, tenant, execution, other, 10 * cost - cost + 1, "committed")
    assert _snapshot(db_schema, run, tenant, execution, first).budget_available is False


def test_released_reservations_do_not_count(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "released", pool=0)
    cost = _cost(state, first)
    run(db_schema.execute("UPDATE tenants SET budget_pool = $2 WHERE tenant_id = $1", tenant, cost, tenant=tenant))
    _reservation(db_schema, run, state, tenant, execution, _order(state)[-1], cost, "released")
    assert _snapshot(db_schema, run, tenant, execution, first).budget_available is True


def test_a_step_that_already_holds_a_live_reservation_passes(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "held", pool=0)
    cost = _cost(state, first)
    run(db_schema.execute("UPDATE tenants SET budget_pool = $2 WHERE tenant_id = $1", tenant, cost, tenant=tenant))
    _reservation(db_schema, run, state, tenant, execution, first, cost, "reserved", link=True)
    assert _snapshot(db_schema, run, tenant, execution, first).budget_available is True


def test_an_unknown_step_fails_closed(db_schema, run):  # noqa: F811
    state, tenant, execution, first = _admitted(db_schema, run, "unknown", pool=1000)
    assert _snapshot(db_schema, run, tenant, execution, "no-such-step").budget_available is False
    assert _snapshot(db_schema, run, tenant, "no-such-execution", first).budget_available is False
