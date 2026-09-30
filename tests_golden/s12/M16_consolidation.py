"""M16 golden — consolidation (gate commit I part 2). Owner-pinned.

Gate v10: §10 (the S13 table as corrected by C8: any DEAD_LETTER step → DEAD_LETTER / FAILURE; all COMPLETED, or
COMPLETED + SKIPPED with no failure → COMPLETED / SUCCESS; at least one COMPLETED and one FAILED or CANCELLED → PARTIAL;
no COMPLETED → FAILED / FAILURE; CANCELLED and SKIPPED count as not completed; legal matrix only;
VERIFICATION_STARTED / VERIFICATION_COMPLETED ledger events with the layer results; no RESERVED reservation after
consolidation, LOCKED only under D4), C13, C39 (quota refund exactly when the run ends CANCELLED with no step
COMPLETED, in the consolidation transaction, with a ledger event), suite 10; invariants I2, I3, I13.
Rulings: CONF-034 (a run whose steps were cancelled ``run_dead_lettered`` is DEAD_LETTER), CONF-037 (the refunded
quota rows are the run's tenant- and workspace-level ``executions`` rows whose period contains the run's creation).

Interface this file fixes:
  * ``contracts.execution_states.ConsolidationOutcome`` (StrEnum SUCCESS, PARTIAL, FAILURE), stored in
    ``execution_runs.consolidation``.
  * ``engine.stages.s13_reconciliation.consolidation.consolidation_outcome(steps) -> (run_status, outcome)`` — pure;
    ``steps`` are ``(status, terminal_reason)`` pairs; ValueError while any step is not terminal.
  * ``adapters.postgres.consolidation.PostgresConsolidator(database)``:
      ``async consolidate(holder, tenant_id, execution_id)`` (also its ``__call__``, so it is a ``LoopDeps.consolidate``)
        and ``async cancel(holder, tenant_id, execution_id, *, reason)`` (a ``LoopDeps.cancel_run``, M14's CANCELLED
        path) → ``ConsolidationResult(run_status, outcome, refunded)``. ONE fenced transaction each: every step must
        be terminal (else ValueError, nothing written); every RESERVED reservation of the run is released
        (``budget_released_before_start``, or ``run_cancelled`` when cancelling); events VERIFICATION_STARTED
        (``{"steps": {plan_step_id: [required layers]}}``) then VERIFICATION_COMPLETED (``{"steps": {plan_step_id:
        [{"layer", "verdict"}...]}}`` from the persisted ``verification_layer`` events, the latest verdict per layer);
        the run moved by the matrix (``consolidated``; ``cancel``: its reason as reason and ``terminal_reason``);
        ``cancel`` with no step COMPLETED also decrements the run's quota rows and records ``quota_refunded``
        (``{"quota_ids": [...]}``). A run that is not RUNNING or RECONCILING is refused (ValueError, nothing written),
        so nothing is refunded twice.
  * ``LoopDeps.cancel_run`` (default None: the store moves the run, M12–M14).
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import (PASSING, _admit, _deps, _events, _loop, _moves, _order, _ops, _state, _steps)

RUNTIME = "runtime-A"


# --- the table (§10, C8, I13) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("steps,expected", [
    ([("completed", None)] * 3, ("completed", "SUCCESS")),
    ([("completed", None), ("skipped", "dependency_failed")], ("completed", "SUCCESS")),
    ([("completed", None), ("failed", None), ("skipped", "dependency_failed")], ("partial", "PARTIAL")),
    ([("completed", None), ("cancelled", "admission_rejected")], ("partial", "PARTIAL")),
    ([("completed", None), ("cancelled", "no_worker"), ("cancelled", "no_worker")], ("partial", "PARTIAL")),
    ([("failed", None), ("skipped", "dependency_failed")], ("failed", "FAILURE")),
    ([("cancelled", "admission_rejected")] * 3, ("failed", "FAILURE")),
    ([("cancelled", "preflight_failed"), ("skipped", "dependency_failed")], ("failed", "FAILURE")),
    ([("completed", None), ("dead_letter", None), ("cancelled", "run_dead_lettered")], ("dead_letter", "FAILURE")),
    ([("dead_letter", None)], ("dead_letter", "FAILURE")),
    ([("cancelled", "run_dead_lettered")] * 2, ("dead_letter", "FAILURE")),
], ids=["all-completed", "completed-skipped", "partial-failed", "partial-cancelled", "partial-no-worker",
        "failed-skipped", "all-cancelled", "preflight", "dead-letter-mixed", "dead-letter", "plan-integrity"])
def test_every_row_of_the_consolidation_table(steps, expected):
    from engine.stages.s13_reconciliation.consolidation import consolidation_outcome
    status, outcome = consolidation_outcome(steps)
    assert (status, outcome) == expected


def test_a_cancelled_step_never_consolidates_to_completed():
    from engine.stages.s13_reconciliation.consolidation import consolidation_outcome
    for reason in ("admission_rejected", "user_cancelled", "not_executed_no_retry", "lease_unavailable"):
        assert consolidation_outcome([("completed", None)] * 4 + [("cancelled", reason)])[0] != "completed"


@pytest.mark.parametrize("status", ["pending", "running", "timeout", "pending_probe"])
def test_consolidation_needs_every_step_terminal(status):
    from engine.stages.s13_reconciliation.consolidation import consolidation_outcome
    with pytest.raises(ValueError):
        consolidation_outcome([("completed", None), (status, None)])


# --- in the loop -----------------------------------------------------------------------------------------------------

def _consolidating(schema, mock, *, verified=True, **settings):
    from adapters.postgres.consolidation import PostgresConsolidator
    from adapters.postgres.reconciliation import PostgresEpisodes
    if verified:
        from tests_golden.s12.M15_verification import _verifying
        deps = _verifying(schema, mock, **settings)
    else:
        deps = dataclasses.replace(_deps(schema, mock, **{"step_timeout_s": 0.1, "probe_backoff_s": 0.001,
                                                          **settings}),
                                   episodes=PostgresEpisodes(schema.database()))
    consolidator = PostgresConsolidator(schema.database())
    return dataclasses.replace(deps, consolidate=consolidator, cancel_run=consolidator.cancel)


def _mocked(**programs):
    from tests_golden.s12.M12_loop import _mock as mock
    return mock(**programs)


def _run_row(schema, run, execution):
    return dict(run(schema.fetch("SELECT status, terminal_reason, consolidation FROM execution_runs"
                                 " WHERE execution_id = $1", execution))[0])


def _payload(event):
    body = event["payload"]
    return json.loads(body) if isinstance(body, str) else body


def _holder(schema, run, tenant, execution):
    from adapters.postgres.fencing import FenceHolder
    owner = run(schema.fetch("SELECT runtime_instance_id, fencing_token FROM execution_ownership WHERE execution_id = $1",
                             execution))[0]
    return FenceHolder(tenant_id=tenant, execution_id=execution, runtime_instance_id=owner["runtime_instance_id"],
                       fence_token=owner["fencing_token"])


def test_a_successful_run_consolidates_completed_with_its_verification_events(db_schema, run):
    state = _state("golden-cons-ok", "cok")
    tenant, execution = _admit(db_schema, run, state)
    result = _loop(db_schema, run, _consolidating(db_schema, _mocked()), tenant, execution)
    assert set(result.steps.values()) == {("completed", None)}
    row = _run_row(db_schema, run, execution)
    assert (row["status"], row["consolidation"]) == ("completed", "SUCCESS")
    assert _moves(db_schema, run, "run", execution)[-1] == ("running", "completed", "consolidated")
    kinds = [e["event_type"] for e in _events(db_schema, run, execution)]
    assert kinds.count("VERIFICATION_STARTED") == kinds.count("VERIFICATION_COMPLETED") == 1
    assert kinds.index("VERIFICATION_STARTED") < kinds.index("VERIFICATION_COMPLETED")
    started = _payload(_events(db_schema, run, execution, "VERIFICATION_STARTED")[0])["steps"]
    completed = _payload(_events(db_schema, run, execution, "VERIFICATION_COMPLETED")[0])["steps"]
    for step in state.plan.plan.steps:
        want = ["schema", "deterministic"] + (["provider_state"] if step.mutation != "R" else [])
        assert started[step.id] == want, step.id
        assert completed[step.id] == [{"layer": x, "verdict": "PASS"} for x in want], step.id
    consolidated = run(db_schema.fetchval("SELECT xmin::text FROM state_transitions WHERE entity_id = $1"
                                          " AND reason = 'consolidated'", execution))
    event = run(db_schema.fetchval("SELECT xmin::text FROM execution_events WHERE execution_id = $1"
                                   " AND event_type = 'VERIFICATION_COMPLETED'", execution))
    assert consolidated == event                                               # one transaction
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("which,program,expected", [
    (0, {"call": "auth_401"}, ("failed", "FAILURE")),
    (1, {"call": "auth_401"}, ("partial", "PARTIAL")),
    (0, {"call": "timeout_executed", "probe": "inconclusive"}, ("dead_letter", "FAILURE")),
], ids=["first-fails", "second-fails", "dead-letter"])
def test_run_outcomes_follow_the_step_states(db_schema, run, which, program, expected):
    state = _state(f"golden-cons-{which}-{program['call']}", f"c{which}{program['call'][:4]}")
    tenant, execution = _admit(db_schema, run, state)
    target = _order(state)[which]
    _loop(db_schema, run, _consolidating(db_schema, _mocked(**{_ops(state)[target]: program})), tenant, execution)
    row = _run_row(db_schema, run, execution)
    assert (row["status"], row["consolidation"]) == expected
    assert _moves(db_schema, run, "run", execution)[-1][2] == "consolidated"
    live = run(db_schema.fetch("SELECT status FROM budget_reservations WHERE execution_id = $1"
                               " AND status IN ('reserved', 'locked')", execution))
    assert [r["status"] for r in live] == (["locked"] if expected[0] == "dead_letter" else [])     # D4 only
    run(assert_system_invariants(db_schema))


def test_an_admission_reject_after_a_completed_step_is_partial_never_completed(db_schema, run):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    state = _state("golden-cons-reject", "creject")
    tenant, execution = _admit(db_schema, run, state)
    second = _order(state)[1]

    async def reject_second(tenant_id, execution_id, plan_step_id):
        return AdmissionSnapshot(**{**PASSING, "provider_allowed": plan_step_id != second})

    deps = dataclasses.replace(_consolidating(db_schema, _mocked()), admission=reject_second)
    _loop(db_schema, run, deps, tenant, execution)
    assert (_run_row(db_schema, run, execution)["status"]) == "partial"
    run(assert_system_invariants(db_schema))


def test_a_tampered_plan_consolidates_to_dead_letter(db_schema, run):
    from tests_golden.s12.M12_loop import _force_plan_update, _retamper
    state = _state("golden-cons-tamper", "ctamper")
    tenant, execution = _admit(db_schema, run, state)
    original = run(db_schema.fetch("SELECT canonical_plan::text AS plan, plan_hash FROM execution_plans"
                                   " WHERE execution_id = $1", execution))[0]
    run(_retamper(db_schema, execution, "params_changed"))
    try:
        _loop(db_schema, run, _consolidating(db_schema, _mocked()), tenant, execution)
    finally:
        run(_force_plan_update(db_schema, execution, f"canonical_plan = $j${original['plan']}$j$::jsonb,"
                                                     f" plan_hash = '{original['plan_hash']}'"))
    assert (_run_row(db_schema, run, execution)["status"], _run_row(db_schema, run, execution)["consolidation"]) == (
        "dead_letter", "FAILURE")
    run(assert_system_invariants(db_schema))


def test_no_reservation_stays_reserved_after_consolidation(db_schema, run):
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    from adapters.postgres.consolidation import PostgresConsolidator
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    from tests_golden.s12.M12_loop import Recorder
    state = _state("golden-cons-reserved", "creserved")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]

    async def reject_all_but_first(tenant_id, execution_id, plan_step_id):
        return AdmissionSnapshot(**{**PASSING, "provider_allowed": plan_step_id == first})

    deps = dataclasses.replace(_consolidating(db_schema, _mocked()), consolidate=Recorder(),
                               admission=reject_all_but_first)
    _loop(db_schema, run, deps, tenant, execution)                            # steps settled, run still RUNNING
    holder = _holder(db_schema, run, tenant, execution)
    stray = run(PostgresBudgetReserver(db_schema.database()).reserve(
        holder, user_id=state.execution_context.user_id, step_id=_steps(db_schema, run, execution)[_order(state)[1]]
        ["step_id"], cost=1))
    assert stray.reservation_id is not None
    run(PostgresConsolidator(db_schema.database()).consolidate(holder, tenant, execution))
    assert run(db_schema.fetchval("SELECT count(*) FROM budget_reservations WHERE execution_id = $1"
                                  " AND status = 'reserved'", execution)) == 0
    assert _moves(db_schema, run, "reservation", stray.reservation_id)[-1] == (
        "reserved", "released", "budget_released_before_start")
    run(assert_system_invariants(db_schema))


def test_consolidation_is_refused_while_a_step_is_not_terminal_and_never_runs_twice(db_schema, run):
    from adapters.postgres.consolidation import PostgresConsolidator
    state = _state("golden-cons-early", "cearly")
    tenant, execution = _admit(db_schema, run, state)
    holder = _holder(db_schema, run, tenant, execution)
    consolidator = PostgresConsolidator(db_schema.database())
    with pytest.raises(ValueError):
        run(consolidator.consolidate(holder, tenant, execution))                # every step is still PENDING
    assert _run_row(db_schema, run, execution)["status"] == "running" and _events(db_schema, run, execution) == []
    done = _state("golden-cons-twice", "ctwice")
    done_tenant, done_execution = _admit(db_schema, run, done)
    _loop(db_schema, run, _consolidating(db_schema, _mocked()), done_tenant, done_execution)
    count = len(_events(db_schema, run, done_execution))
    with pytest.raises(ValueError):
        run(consolidator.consolidate(_holder(db_schema, run, done_tenant, done_execution), done_tenant,
                                     done_execution))
    assert len(_events(db_schema, run, done_execution)) == count


# --- the quota refund (C39) ------------------------------------------------------------------------------------------

def _seed_quotas(schema, run, state, *, workspace_level=False, budget_pool=1000):
    """The tenant (with its budget) and its quota rows, before admission consumes one use of each."""
    ctx = state.execution_context
    from tests_golden.fixtures.certified import seed_identity
    run(seed_identity(schema, state, budget_pool=budget_pool))
    ids = []
    for workspace in (None, ctx.workspace_id) if workspace_level else (None,):
        quota_id = f"q-{ctx.tenant_id}-{workspace or 'tenant'}"
        run(schema.execute(
            "INSERT INTO operation_quotas (quota_id, tenant_id, workspace_id, resource_type, period_start, period_end,"
            " limit_value, used_count, is_hard) VALUES ($1, $2, $3, 'executions', now() - interval '1 hour',"
            " now() + interval '1 hour', 5, 0, true)", quota_id, ctx.tenant_id, workspace, tenant=ctx.tenant_id))
        ids.append(quota_id)
    return ids


def _used(schema, run, quota_ids):
    return [run(schema.fetchval("SELECT used_count FROM operation_quotas WHERE quota_id = $1", q)) for q in quota_ids]


def test_a_run_cancelled_before_any_step_completed_refunds_its_quota_in_the_same_transaction(db_schema, run):
    state = _state("golden-cons-refund", "crefund")
    pool = state.plan.plan.steps[0].cost - 1
    quotas = _seed_quotas(db_schema, run, state, workspace_level=True, budget_pool=pool)
    tenant, execution = _admit(db_schema, run, state, budget_pool=pool)
    assert _used(db_schema, run, quotas) == [1, 1]
    result = _loop(db_schema, run, _consolidating(db_schema, _mocked()), tenant, execution)
    assert (result.run_status, result.reason) == ("cancelled", "budget_exhausted")
    assert _used(db_schema, run, quotas) == [0, 0]
    (refund,) = _events(db_schema, run, execution, "quota_refunded")
    assert sorted(_payload(refund)["quota_ids"]) == sorted(quotas)
    cancelled = run(db_schema.fetchval("SELECT xmin::text FROM state_transitions WHERE entity_id = $1"
                                       " AND to_state = 'cancelled'", execution))
    assert cancelled == run(db_schema.fetchval("SELECT xmin::text FROM execution_events WHERE execution_id = $1"
                                               " AND event_type = 'quota_refunded'", execution))
    assert _run_row(db_schema, run, execution)["terminal_reason"] == "budget_exhausted"
    run(assert_system_invariants(db_schema))


def test_a_user_cancel_before_start_refunds_and_a_second_cancel_refunds_nothing(db_schema, run):
    from adapters.postgres.cancellation import PostgresCancellation
    from adapters.postgres.consolidation import PostgresConsolidator
    state = _state("golden-cons-usercancel", "cusercancel")
    quotas = _seed_quotas(db_schema, run, state)
    tenant, execution = _admit(db_schema, run, state)
    assert run(PostgresCancellation(db_schema.database()).request(tenant, execution,
                                                                  state.execution_context.user_id)) is True
    result = _loop(db_schema, run, _consolidating(db_schema, _mocked()), tenant, execution)
    assert (result.run_status, result.reason) == ("cancelled", "user_cancelled") and _used(db_schema, run, quotas) == [0]
    with pytest.raises(ValueError):
        run(PostgresConsolidator(db_schema.database()).cancel(_holder(db_schema, run, tenant, execution), tenant,
                                                              execution, reason="user_cancelled"))
    assert _used(db_schema, run, quotas) == [0] and len(_events(db_schema, run, execution, "quota_refunded")) == 1


def test_no_refund_once_a_step_completed_or_for_a_run_that_was_not_cancelled(db_schema, run):
    later = _state("golden-cons-norefund", "cnorefund")
    pool = later.plan.plan.steps[0].cost
    quotas = _seed_quotas(db_schema, run, later, budget_pool=pool)
    tenant, execution = _admit(db_schema, run, later, budget_pool=pool)
    result = _loop(db_schema, run, _consolidating(db_schema, _mocked()), tenant, execution)
    assert (result.run_status, result.reason) == ("cancelled", "budget_exhausted")
    assert _used(db_schema, run, quotas) == [1] and _events(db_schema, run, execution, "quota_refunded") == []
    failed = _state("golden-cons-failed-norefund", "cfailnorefund")
    failed_quotas = _seed_quotas(db_schema, run, failed)
    f_tenant, f_execution = _admit(db_schema, run, failed)
    first = _order(failed)[0]
    _loop(db_schema, run, _consolidating(db_schema, _mocked(**{_ops(failed)[first]: {"call": "auth_401"}})),
          f_tenant, f_execution)
    assert _run_row(db_schema, run, f_execution)["status"] == "failed"
    assert _used(db_schema, run, failed_quotas) == [1]
    run(assert_system_invariants(db_schema))


def test_every_move_on_these_paths_is_legal(db_schema, run):
    run(assert_system_invariants(db_schema))
