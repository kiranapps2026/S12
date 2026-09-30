"""M12 golden — the S12 step loop: happy path, dependents, terminal reasons (gate commit H part 1). Owner-pinned.

Gate v10: §8 steps 1–12 (the live check of step 0 and cancellation are M14; the probe path of §9 is M13; verification
layers are M15, here an injected verdict), C11 (topological order, ties by step index; a step is never skipped by
admission or a lease failure), C15 (budget exhausted: the step and every remaining step CANCELLED ``budget_exhausted``,
the run CANCELLED), C22 (the trigger's reason for collateral steps; SKIPPED only with ``dependency_failed``), C30 (a
REJECT mapped by ``gate_failed``; ``no_worker``/``lease_unavailable`` handled as REJECT; every decision a ledger
event), C24/C35/I16 (a retry is a ``step_attempt`` event; every ``ProviderCalled`` follows its marker), Appendix A.1/A.2
reasons, I-3 (a step starts and its reservation locks in one transaction), §21 S2 (dispatch through
``ExecutionDispatcher``), S5 (every log line carries the correlation ids), FINAL_ARCHITECTURE §40 (the execution
ledger ``execution_events``, append-only). Rulings: CONF-026 (the ``execution_events`` table), CONF-027 (live
admission snapshot and pre-flight sources are injected in this phase).

Interface this file fixes:
  * Migration 016+ creates ``execution_events``: ``seq`` BIGSERIAL (order), ``event_id`` TEXT UNIQUE, ``tenant_id`` TEXT
    NOT NULL, ``execution_id``, ``trace_id`` NOT NULL, ``event_type`` NOT NULL, ``step_id``, ``attempt_id``,
    ``provider_call_id``, ``runtime_instance_id``, ``fence_token``, ``payload`` JSONB, ``created_at``; forced RLS;
    UPDATE and DELETE rejected for every role (append-only).
  * ``adapters.postgres.execution_events.PostgresExecutionEvents(database)``: ``recorder(holder, *, trace_id,
    step_id=None)`` → an object with ``async record(kind, payload)`` (one ``fenced_write``; ``step_id``/``attempt_id``/
    ``provider_call_id`` columns from the payload, else the bound ``step_id``).
  * ``adapters.postgres.execution.PostgresExecutionStore(database)`` (the loop's store; every write fenced, validated by
    ``transitions.validate`` and logged).
  * ``adapters.postgres.kernel_policy.PostgresKernelPolicy(database)``: ``async retry_safety(kernel_op_id) -> str``
    (``kernel_ops.retry_safety``; an unknown operation is ``never``).
  * ``engine.stages.s12_execute.loop``:
      ``topological_order(steps)`` (ties by index; a cycle or unknown id raises ValueError).
      ``LoopSettings(admission_max_attempts, lease_max_attempts, lease_ttl_s, backoff_base_s, ledger_ttl_s)``.
      ``LoopDeps(runtime_instance_id, store, events, admission, selection, leases, budget, kernel_policy, preflight,
        guard, idempotency, attempts, live, verify, consolidate, sleep, settings)`` where ``admission(tenant_id,
        execution_id, plan_step_id) -> AdmissionSnapshot``, ``preflight(step, binding) -> str | None`` (a failure
        detail), ``verify(step, binding, result) -> "PASS" | "FAIL" | "UNKNOWN"``, ``consolidate(holder, tenant_id,
        execution_id)`` (called once after the loop unless the run already ended), the others the M7–M11 adapters.
      ``async run_execution(deps, tenant_id, execution_id) -> LoopResult(run_status, steps, reason)``; ``steps`` maps
        each plan step id to ``(status, terminal_reason)``.
      Per step, in topological order: admission (``admit_step``; REJECT per ``reject_outcome``); eligibility filters
      and selection (``lease_for_step``: ``no_worker`` / ``lease_unavailable`` end the run like a REJECT); reserve
      (exhausted: C15); pre-flight (failure: budget released ``preflight_failed``, lease released, step CANCELLED
      ``preflight_failed`` with the detail in ``error``, dependents SKIPPED); start (``started`` + ``step_started`` in
      one transaction); ``run_attempts``; ``verify``; ``verified`` / ``ledger_hit_verified`` with the reservation
      committed, or FAILED (``non_retryable_error``, ``retries_exhausted``, ``ledger_hit_failure``,
      ``verification_failed``) with it released (``step_failed``); ``undo_token`` for a completed W/D step whose
      binding has an inverse; lease released ``work_complete``; dependents of a FAILED/CANCELLED step SKIPPED
      ``dependency_failed``. A run-ending trigger cancels the step and every remaining PENDING step with its reason.
      Before any step (gate §7.3, ruling CONF-034): a run that is not RUNNING is returned untouched; a run whose
      ownership does not name ``runtime_instance_id`` is never taken over (reason ``fenced_out``, nothing written:
      only recovery takes ownership, M19); the canonical plan is decoded and its digest recomputed, and a plan that
      does not decode or whose digest differs from ``execution_plans.plan_hash`` or ``execution_manifests.plan_hash``
      executes nothing: every PENDING step CANCELLED ``run_dead_lettered``, an ERROR alert naming
      ``plan_integrity``, consolidation, reason ``plan_integrity``.
      ``FencedOut`` at any point (§8 step 8, C25): stop at once with reason ``fenced_out``; no further execution
      write, no consolidation; a lease the loop holds is released ``fenced_out`` (Appendix A.4); a step in flight is
      left as it is for the new owner. A lease is acquired only while the ownership row still names the loop's
      holder, checked atomically inside the acquisition: ``PostgresLeaseManager.acquire`` gains the keyword
      ``holder`` (default None, M07 unchanged) and raises ``FencedOut`` without writing when ownership moved.
  The loop never names runtime types (M08a, RD-9): it takes the binding's runtime list (read once per run through
  the selection reader, ruling CONF-019) and builds the ``SelectionContext`` through ``engine.stages.s12_execute.
  eligibility``.
  * ``engine.stages.s12_execute.dispatch.InProcessDispatcher(run)``: ``dispatch(tenant_id, execution_id)`` returns an
    awaitable handle of ``run(tenant_id, execution_id)``; no other S12–S15 module schedules tasks.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging

import pytest

from tests_golden.fixtures.certified import ManifestBindings, certified_state, entry_readers, fresh, seed_identity
from tests_golden.fixtures.invariants import assert_system_invariants

RUNTIME = "runtime-A"
CHAIN3 = (("contact.create", {"name": "Ana"}), ("email.send", {"to": "a@x.com"}), ("contact.list", {}))
PASSING = dict(kill_switch_engaged=False, tenant_quota_exceeded=False, tenant_active=True, workspace_active=True,
               mode_allowed=True, provider_allowed=True, worker_capacity_available=True, circuit_open=False,
               db_pool_pressure=False, budget_available=True, system_overloaded=False)


# --- pure ------------------------------------------------------------------------------------------------------------

def _plain_step(sid, depends_on=()):
    from contracts.stage_outputs import Step
    return Step(id=sid, kernel_op_id="op", depends_on=tuple(depends_on))


def test_topological_order_breaks_ties_by_step_index():
    from engine.stages.s12_execute.loop import topological_order
    steps = [_plain_step("c", ["b"]), _plain_step("a"), _plain_step("b", ["a"]), _plain_step("d")]
    assert [s.id for s in topological_order(steps)] == ["a", "b", "c", "d"]
    independent = [_plain_step(x) for x in ("z", "y", "x")]
    assert [s.id for s in topological_order(independent)] == ["z", "y", "x"]


@pytest.mark.parametrize("steps", [[("a", ["b"]), ("b", ["a"])], [("a", ["nope"])]], ids=["cycle", "unknown"])
def test_topological_order_refuses_a_cycle_or_an_unknown_dependency(steps):
    from engine.stages.s12_execute.loop import topological_order
    with pytest.raises(ValueError):
        topological_order([_plain_step(s, d) for s, d in steps])


# --- fixtures --------------------------------------------------------------------------------------------------------

class Credentials:
    async def credential(self, tenant_id, connection_id):
        return "secret"


class Live:
    async def check(self, **kw):
        return None


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, *args):
        self.calls.append(args)


def _state(tenant, suffix, chain=CHAIN3):
    return fresh(certified_state(tenant_id=tenant, chain=chain), suffix)


async def _seed_registry(schema, state, retry_safety="safe"):
    for binding in state.frozen_bindings:
        await schema.execute(
            "INSERT INTO capabilities (capability_id, name, intent, mutation, risk_floor, risk_rule, risk_implied,"
            " truth_state) VALUES ($1, $1, $1, $2, 0, 0, 0, 'PRODUCTION_ENABLED') ON CONFLICT DO NOTHING",
            binding.capability_id, binding.effective_mutation)
        await schema.execute(
            "INSERT INTO kernel_ops (kernel_op_id, mutation, risk_floor, cost, timeout_seconds, retry_safety,"
            " truth_state) VALUES ($1, $2, 0, 1, 30, $3, 'PRODUCTION_ENABLED') ON CONFLICT (kernel_op_id)"
            " DO UPDATE SET retry_safety = EXCLUDED.retry_safety", binding.kernel_op_id, binding.effective_mutation,
            retry_safety)
        await schema.execute(
            "INSERT INTO bindings (binding_id, capability_id, kernel_op_id, provider, engine_module, adapter_class,"
            " is_active, required_runtime_types) VALUES ($1, $2, $3, $4, 'm', 'MockAdapter', true, '[]'::jsonb)"
            " ON CONFLICT DO NOTHING", binding.binding_id, binding.capability_id, binding.kernel_op_id,
            binding.provider)


async def _seed_worker(schema, state, *, workspace=None, capacity=2):
    ctx = state.execution_context
    caps = json.dumps(sorted({b.capability_id for b in state.frozen_bindings}))
    await schema.execute(
        "INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile, state, capacity)"
        " VALUES ($1, $2, $3, 'g', $4::jsonb, 'ACTIVE', $5) ON CONFLICT DO NOTHING", f"w-{ctx.tenant_id}",
        ctx.tenant_id, workspace or ctx.workspace_id, caps, capacity, tenant=ctx.tenant_id)


def _admit(schema, run, state, *, budget_pool=1000, retry_safety="safe", worker_workspace=None):
    from adapters.postgres.admission import PostgresExecutionAdmission
    from engine.stages.s12_entry.admission import admit_run
    run(seed_identity(schema, state, budget_pool=budget_pool))
    if worker_workspace is not None:
        run(schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ($1, $2, 'other')"
                           " ON CONFLICT DO NOTHING", worker_workspace, state.execution_context.tenant_id,
                           tenant=state.execution_context.tenant_id))
    run(_seed_registry(schema, state, retry_safety))
    run(_seed_worker(schema, state, workspace=worker_workspace))
    readers = {**entry_readers(), "bindings": ManifestBindings(state.execution_manifest.binding_version)}
    outcome = run(admit_run(state, **readers, admitter=PostgresExecutionAdmission(schema.database()),
                            runtime_instance_id=RUNTIME))
    assert outcome.status == "ADMITTED", outcome
    return state.execution_context.tenant_id, state.plan.execution_id


def _mock(**programs):
    from adapters.runtime.mock_adapter import MockAdapter
    mock = MockAdapter(Credentials())
    for op, program in programs.items():
        mock.program(op, **program)
    return mock


def _deps(schema, mock, *, admission=None, preflight=None, verify=None, consolidate=None, **settings):
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    from adapters.postgres.execution import PostgresExecutionStore
    from adapters.postgres.execution_events import PostgresExecutionEvents
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from adapters.postgres.kernel_policy import PostgresKernelPolicy
    from adapters.postgres.leases import PostgresLeaseManager
    from adapters.postgres.selection import PostgresSelectionReader
    from adapters.postgres.step_attempts import PostgresStepAttempts
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    from adapters.runtime.reliability import (InProcessBilling, InProcessBulkhead, InProcessHealthMonitor,
                                              InProcessRetryStormGuard)
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    from engine.stages.s12_execute.loop import LoopDeps, LoopSettings
    from engine.stages.s12_execute.reliability import BudgetTracker, ReliabilityGuard, TimeoutManager
    db = schema.database()
    guard = ReliabilityGuard(mock, bulkhead=InProcessBulkhead(4), breaker=InProcessCircuitBreaker(50, 30.0),
                             budget=BudgetTracker(PostgresBudgetReserver(db)),
                             retry_storm=InProcessRetryStormGuard(100, 60.0), timeouts=TimeoutManager(),
                             health=InProcessHealthMonitor(), billing=InProcessBilling(), probe_timeout_s=0.5)

    async def all_pass(tenant_id, execution_id, plan_step_id):
        return AdmissionSnapshot(**PASSING)

    async def no_preflight_problem(step, binding):
        return None

    async def passes(step, binding, result):
        return "PASS"

    async def no_sleep(seconds):
        return None
    config = dict(admission_max_attempts=3, lease_max_attempts=3, lease_ttl_s=30.0, backoff_base_s=0.001,
                  ledger_ttl_s=3600.0)
    config.update(settings)
    return LoopDeps(runtime_instance_id=RUNTIME, store=PostgresExecutionStore(db), events=PostgresExecutionEvents(db),
                    admission=admission or all_pass, selection=PostgresSelectionReader(db),
                    leases=PostgresLeaseManager(db), budget=PostgresBudgetReserver(db),
                    kernel_policy=PostgresKernelPolicy(db), preflight=preflight or no_preflight_problem, guard=guard,
                    idempotency=PostgresIdempotencyLedger(db), attempts=PostgresStepAttempts(db), live=Live(),
                    verify=verify or passes, consolidate=consolidate or Recorder(), sleep=no_sleep,
                    settings=LoopSettings(**config))


def _loop(schema, run, deps, tenant, execution):
    """Run the loop; its reported step outcomes must be what it persisted."""
    from engine.stages.s12_execute.loop import run_execution
    result = run(run_execution(deps, tenant, execution))
    persisted = {sid: (row["status"], row["terminal_reason"]) for sid, row in _steps(schema, run, execution).items()}
    assert dict(result.steps) == persisted
    return result


def _steps(schema, run, execution):
    rows = run(schema.fetch("SELECT s.plan_step_id, s.step_id, s.status, s.terminal_reason, s.error, s.undo_token,"
                            " b.status AS budget FROM execution_steps s LEFT JOIN budget_reservations b"
                            " ON b.reservation_id = s.reservation_id WHERE s.execution_id = $1 ORDER BY s.plan_step_id",
                            execution))
    return {r["plan_step_id"]: dict(r) for r in rows}


def _moves(schema, run, entity_type, entity_id):
    rows = run(schema.fetch("SELECT from_state, to_state, reason FROM state_transitions WHERE entity_type = $1"
                            " AND entity_id = $2 ORDER BY transition_id", entity_type, entity_id))
    return [tuple(r) for r in rows]


def _events(schema, run, execution, kind=None):
    rows = run(schema.fetch("SELECT seq, event_type, step_id, attempt_id, provider_call_id, payload FROM execution_events"
                            " WHERE execution_id = $1 ORDER BY seq", execution))
    return [dict(r) for r in rows if kind is None or r["event_type"] == kind]


def _order(state):
    return [s.id for s in state.plan.plan.steps]


def _ops(state):
    return {s.id: s.kernel_op_id for s in state.plan.plan.steps}


# --- the happy path ---------------------------------------------------------------------------------------------------

def test_a_chain_runs_in_order_and_every_step_completes(db_schema, run):
    state = _state("golden-loop-ok", "ok")
    tenant, execution = _admit(db_schema, run, state)
    mock, consolidate = _mock(), Recorder()
    result = _loop(db_schema, run, _deps(db_schema, mock, consolidate=consolidate), tenant, execution)
    order = _order(state)
    assert {sid: result.steps[sid] for sid in order} == {sid: ("completed", None) for sid in order}
    steps = _steps(db_schema, run, execution)
    assert all((steps[sid]["status"], steps[sid]["budget"]) == ("completed", "committed") for sid in order)
    called = [e["step_id"] for e in _events(db_schema, run, execution, "ProviderCalled")]
    assert called == [steps[sid]["step_id"] for sid in order]
    assert [mock.side_effects(f"{state.execution_context.request_id}:{sid}") for sid in order] == [1, 1, 1]
    assert len(consolidate.calls) == 1 and consolidate.calls[0][1:] == (tenant, execution)
    leases = run(db_schema.fetch("SELECT status FROM worker_leases WHERE execution_id = $1", execution))
    assert len(leases) == 3 and {r["status"] for r in leases} == {"released"}
    run(assert_system_invariants(db_schema))


def test_each_step_follows_the_section_8_sequence(db_schema, run):
    state = _state("golden-loop-seq", "seq")
    tenant, execution = _admit(db_schema, run, state)
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    steps = _steps(db_schema, run, execution)
    for sid in _order(state):
        step_id = steps[sid]["step_id"]
        reservation = run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1", step_id))
        rows = run(db_schema.fetch("SELECT entity_type, to_state, reason FROM state_transitions"
                                   " WHERE entity_id = ANY($1::text[]) ORDER BY transition_id", [step_id, reservation]))
        assert [tuple(r) for r in rows] == [
            ("step", "pending", "created"), ("reservation", "reserved", "reserved"), ("step", "running", "started"),
            ("reservation", "locked", "step_started"), ("step", "completed", "verified"),
            ("reservation", "committed", "step_completed")]
        kinds = [e["event_type"] for e in _events(db_schema, run, execution) if e["step_id"] == step_id]
        assert kinds == ["admission_decision", "step_attempt", "ProviderCalled", "ProviderReturned"]


def test_a_step_starts_and_locks_its_budget_in_one_transaction(db_schema, run):
    state = _state("golden-loop-i3", "i3")
    tenant, execution = _admit(db_schema, run, state)
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    for step in _steps(db_schema, run, execution).values():
        reservation = run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1",
                                             step["step_id"]))
        started = run(db_schema.fetchval("SELECT xmin::text FROM state_transitions WHERE entity_id = $1"
                                         " AND reason = 'started'", step["step_id"]))
        locked = run(db_schema.fetchval("SELECT xmin::text FROM state_transitions WHERE entity_id = $1"
                                        " AND reason = 'step_started'", reservation))
        assert started is not None and started == locked                  # the same inserting transaction (I-3)


def test_every_lease_is_released_after_its_step(db_schema, run):
    state = _state("golden-loop-lease", "lease")
    tenant, execution = _admit(db_schema, run, state)
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    for lease_id in [r["lease_id"] for r in run(db_schema.fetch(
            "SELECT lease_id FROM worker_leases WHERE execution_id = $1", execution))]:
        assert _moves(db_schema, run, "lease", lease_id) == [(None, "active", "acquired"),
                                                            ("active", "released", "work_complete")]
    assert run(db_schema.fetchval("SELECT current_load FROM workers WHERE tenant_id = $1", tenant)) == 0


def test_leases_bracket_each_step_in_the_section_8_order(db_schema, run):
    state = _state("golden-loop-bracket", "bracket")
    tenant, execution = _admit(db_schema, run, state)
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    steps = _steps(db_schema, run, execution)
    leases = [r["lease_id"] for r in run(db_schema.fetch(
        "SELECT lease_id FROM worker_leases WHERE execution_id = $1 ORDER BY fence_token", execution))]
    assert len(leases) == len(_order(state))
    for sid, lease_id in zip(_order(state), leases, strict=True):
        step_id = steps[sid]["step_id"]
        reservation = run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1", step_id))
        rows = run(db_schema.fetch("SELECT entity_type, to_state, reason FROM state_transitions"
                                   " WHERE entity_id = ANY($1::text[]) AND reason <> 'created' ORDER BY transition_id",
                                   [step_id, reservation, lease_id]))
        assert [tuple(r) for r in rows] == [
            ("lease", "active", "acquired"), ("reservation", "reserved", "reserved"), ("step", "running", "started"),
            ("reservation", "locked", "step_started"), ("step", "completed", "verified"),
            ("reservation", "committed", "step_completed"), ("lease", "released", "work_complete")]


def test_an_undo_token_is_recorded_for_a_completed_write_with_an_inverse(db_schema, run):
    state = _state("golden-loop-undo", "undo")
    tenant, execution = _admit(db_schema, run, state)
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    steps = _steps(db_schema, run, execution)
    with_inverse = {b.binding_id for b in state.frozen_bindings if b.inverse_kernel_op_id}
    for step in state.plan.plan.steps:
        binding = next(b for b in state.frozen_bindings if b.kernel_op_id == step.kernel_op_id)
        expected = binding.binding_id in with_inverse and step.mutation in ("W", "D")
        assert (steps[step.id]["undo_token"] is not None) is expected, step.id


def test_a_cached_result_completes_without_a_call_on_legal_transitions(db_schema, run):
    from adapters.postgres.fencing import FenceHolder
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    state = _state("golden-loop-hit", "hit")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    holder = FenceHolder(tenant_id=tenant, execution_id=execution, runtime_instance_id=RUNTIME, fence_token=0)
    run(PostgresIdempotencyLedger(db_schema.database()).store(
        holder, idempotency_key=f"{state.execution_context.request_id}:{first}", kernel_op_id=_ops(state)[first],
        result=AdapterResult("ok", data={"id": 1}), ttl_s=3600))
    mock = _mock()
    result = _loop(db_schema, run, _deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("completed", None)
    assert f"{state.execution_context.request_id}:{first}" not in {m.idempotency_key for m in mock.calls}
    step_id = _steps(db_schema, run, execution)[first]["step_id"]
    assert _moves(db_schema, run, "step", step_id)[-1] == ("running", "completed", "ledger_hit_verified")
    run(assert_system_invariants(db_schema))


# --- failures, dependents and terminal reasons (C22) -----------------------------------------------------------------

def test_a_failed_step_skips_its_dependents(db_schema, run):
    state = _state("golden-loop-dep", "dep")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mock(**{_ops(state)[first]: {"call": "auth_401"}})
    consolidate = Recorder()
    result = _loop(db_schema, run, _deps(db_schema, mock, consolidate=consolidate), tenant, execution)
    assert result.steps[first] == ("failed", None)
    assert all(result.steps[sid] == ("skipped", "dependency_failed") for sid in rest)
    steps = _steps(db_schema, run, execution)
    assert steps[first]["budget"] == "released" and all(steps[sid]["budget"] is None for sid in rest)
    assert _moves(db_schema, run, "step", steps[first]["step_id"])[-1] == ("running", "failed", "non_retryable_error")
    assert len(mock.calls) == 1 and len(consolidate.calls) == 1
    for sid in rest:
        assert _moves(db_schema, run, "step", steps[sid]["step_id"])[-1] == ("pending", "skipped", "dependency_failed")
    run(assert_system_invariants(db_schema))


def test_retries_exhausted_is_its_own_failure_reason(db_schema, run):
    state = _state("golden-loop-exhaust", "exhaust")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    mock = _mock(**{_ops(state)[first]: {"call": "fail_500_then_success", "n": 9}})
    result = _loop(db_schema, run, _deps(db_schema, mock), tenant, execution)
    step_id = _steps(db_schema, run, execution)[first]["step_id"]
    assert result.steps[first] == ("failed", None) and len(mock.calls) == 2           # W ceiling 2
    assert _moves(db_schema, run, "step", step_id)[-1] == ("running", "failed", "retries_exhausted")


def test_the_retry_safety_of_an_unknown_operation_is_never(db_schema, run):
    from adapters.postgres.kernel_policy import PostgresKernelPolicy
    state = _state("golden-loop-never", "never")
    run(_seed_registry(db_schema, state, "idempotent"))
    policy = PostgresKernelPolicy(db_schema.database())
    assert run(policy.retry_safety(state.frozen_bindings[0].kernel_op_id)) == "idempotent"
    assert run(policy.retry_safety("op.no.such.operation")) == "never"


def test_a_verification_failure_fails_the_step(db_schema, run):
    state = _state("golden-loop-vfail", "vfail")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]

    async def fail_first(step, binding, result):
        return "FAIL" if step.id == first else "PASS"

    result = _loop(db_schema, run, _deps(db_schema, _mock(), verify=fail_first), tenant, execution)
    steps = _steps(db_schema, run, execution)
    assert result.steps[first] == ("failed", None) and steps[first]["budget"] == "released"
    assert _moves(db_schema, run, "step", steps[first]["step_id"])[-1] == ("running", "failed", "verification_failed")


def test_budget_exhaustion_cancels_the_trigger_and_every_remaining_step_and_the_run(db_schema, run):
    state = _state("golden-loop-budget", "budget")
    costs = [s.cost for s in state.plan.plan.steps]
    tenant, execution = _admit(db_schema, run, state, budget_pool=costs[0])
    first, *rest = _order(state)
    consolidate = Recorder()
    result = _loop(db_schema, run, _deps(db_schema, _mock(), consolidate=consolidate), tenant, execution)
    assert result.steps[first] == ("completed", None)
    assert all(result.steps[sid] == ("cancelled", "budget_exhausted") for sid in rest)
    assert (result.run_status, result.reason) == ("cancelled", "budget_exhausted") and consolidate.calls == []
    assert _moves(db_schema, run, "run", execution)[-1] == ("running", "cancelled", "budget_exhausted")
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = $1 AND status = 'active'",
                                  execution)) == 0
    run(assert_system_invariants(db_schema))


def test_an_admission_reject_cancels_the_remaining_steps_and_consolidates(db_schema, run):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    state = _state("golden-loop-reject", "reject")
    tenant, execution = _admit(db_schema, run, state)
    first, second, third = _order(state)

    async def reject_second(tenant_id, execution_id, plan_step_id):
        return AdmissionSnapshot(**{**PASSING, "provider_allowed": plan_step_id != second})

    consolidate = Recorder()
    result = _loop(db_schema, run, _deps(db_schema, _mock(), admission=reject_second, consolidate=consolidate),
                   tenant, execution)
    assert result.steps[first] == ("completed", None)
    assert result.steps[second] == result.steps[third] == ("cancelled", "admission_rejected")
    assert len(consolidate.calls) == 1
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = $1", execution)) == 1
    decisions = [e["payload"] for e in _events(db_schema, run, execution, "admission_decision")]
    assert [json.loads(p)["status"] if isinstance(p, str) else p["status"] for p in decisions] == ["ACCEPT", "REJECT"]


def test_admission_queue_waits_and_never_skips_the_step(db_schema, run):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    state = _state("golden-loop-queue", "queue")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    seen = []

    async def queue_first_twice(tenant_id, execution_id, plan_step_id):
        seen.append(plan_step_id)
        busy = plan_step_id == first and seen.count(first) <= 2
        return AdmissionSnapshot(**{**PASSING, "worker_capacity_available": not busy})

    result = _loop(db_schema, run, _deps(db_schema, _mock(), admission=queue_first_twice), tenant, execution)
    assert result.steps[first] == ("completed", None) and seen.count(first) == 3


def test_persistent_backpressure_ends_as_admission_exhausted(db_schema, run):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    state = _state("golden-loop-exhausted", "exhausted")
    tenant, execution = _admit(db_schema, run, state)

    async def overloaded(tenant_id, execution_id, plan_step_id):
        return AdmissionSnapshot(**{**PASSING, "system_overloaded": True})

    result = _loop(db_schema, run, _deps(db_schema, _mock(), admission=overloaded, admission_max_attempts=2),
                   tenant, execution)
    assert all(result.steps[sid] == ("cancelled", "admission_exhausted") for sid in _order(state))


def test_no_eligible_worker_is_no_worker_for_the_step_and_the_rest(db_schema, run):
    state = _state("golden-loop-noworker", "noworker")
    tenant, execution = _admit(db_schema, run, state, worker_workspace="golden-ws-elsewhere")
    consolidate = Recorder()
    result = _loop(db_schema, run, _deps(db_schema, _mock(), consolidate=consolidate), tenant, execution)
    assert all(result.steps[sid] == ("cancelled", "no_worker") for sid in _order(state))
    assert len(consolidate.calls) == 1
    no_worker = _events(db_schema, run, execution, "no_worker")
    assert len(no_worker) == 1
    reasons = no_worker[0]["payload"]
    reasons = json.loads(reasons) if isinstance(reasons, str) else reasons
    assert set(reasons["reasons"].values()) == {"workspace_mismatch"}


def test_a_preflight_failure_cancels_only_its_step_and_skips_its_dependents(db_schema, run):
    state = _state("golden-loop-preflight", "preflight")
    tenant, execution = _admit(db_schema, run, state)
    first, second, third = _order(state)

    async def schema_invalid(step, binding):
        return "params do not match the kernel input schema" if step.id == second else None

    consolidate = Recorder()
    result = _loop(db_schema, run, _deps(db_schema, _mock(), preflight=schema_invalid, consolidate=consolidate),
                   tenant, execution)
    assert result.steps[first] == ("completed", None)
    assert result.steps[second] == ("cancelled", "preflight_failed")
    assert result.steps[third] == ("skipped", "dependency_failed")
    steps = _steps(db_schema, run, execution)
    assert steps[second]["budget"] == "released" and "schema" in (steps[second]["error"] or "")
    reservation = run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1",
                                         steps[second]["step_id"]))
    assert _moves(db_schema, run, "reservation", reservation)[-1] == ("reserved", "released", "preflight_failed")
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = $1 AND status = 'active'",
                                  execution)) == 0
    assert len(consolidate.calls) == 1
    run(assert_system_invariants(db_schema))


# --- ownership, fencing and plan integrity (gate §7.3, §8 step 8, C25; CONF-034) -------------------------------------

async def _snapshot(schema, tenant, execution):
    """Everything the loop could write for this execution (lease moves are compared separately)."""
    counts = {}
    for table in ("execution_events", "worker_leases", "budget_reservations", "idempotency_ledger",
                  "step_reconciliations"):
        counts[table] = await schema.fetchval(f"SELECT count(*) FROM {table} WHERE tenant_id = $1", tenant)
    counts["state_transitions"] = await schema.fetchval(
        "SELECT count(*) FROM state_transitions WHERE tenant_id = $1 AND entity_type <> 'lease'", tenant)
    steps = await schema.fetch("SELECT step_id, status, terminal_reason, attempt, dispatched_attempt, reservation_id"
                               " FROM execution_steps WHERE execution_id = $1 ORDER BY step_id", execution)
    run_row = await schema.fetch("SELECT status, terminal_reason FROM execution_runs WHERE execution_id = $1",
                                 execution)
    owner = await schema.fetch("SELECT runtime_instance_id, fencing_token, lease_id FROM execution_ownership"
                               " WHERE execution_id = $1", execution)
    return counts, [tuple(r) for r in steps], [tuple(r) for r in run_row], [tuple(r) for r in owner]


async def _take_over(schema, execution):
    """Another Worker Runtime takes the execution: a newer token from the one sequence (C25)."""
    await schema.execute("UPDATE execution_ownership SET runtime_instance_id = 'runtime-B',"
                         " fencing_token = nextval('fence_token_seq') WHERE execution_id = $1", execution)


class _Proxy:
    """Delegates to a real dependency; ``overrides`` replaces some of its methods."""
    def __init__(self, real, **overrides):
        self._real, self._overrides = real, overrides

    def __getattr__(self, name):
        return self._overrides.get(name) or getattr(self._real, name)


def test_a_run_that_is_not_running_is_left_untouched(db_schema, run):
    state = _state("golden-loop-notrunning", "notrunning")
    tenant, execution = _admit(db_schema, run, state)
    run(db_schema.execute("UPDATE execution_runs SET status = 'pending' WHERE execution_id = $1", execution))
    before = run(_snapshot(db_schema, tenant, execution))
    mock, consolidate = _mock(), Recorder()
    result = _loop(db_schema, run, _deps(db_schema, mock, consolidate=consolidate), tenant, execution)
    assert result.run_status == "pending" and mock.calls == [] and consolidate.calls == []
    assert run(_snapshot(db_schema, tenant, execution)) == before


def test_a_run_owned_by_another_runtime_is_never_taken_over(db_schema, run):
    state = _state("golden-loop-foreign", "foreign")
    tenant, execution = _admit(db_schema, run, state)
    run(_take_over(db_schema, execution))
    before = run(_snapshot(db_schema, tenant, execution))
    mock, consolidate = _mock(), Recorder()
    result = _loop(db_schema, run, _deps(db_schema, mock, consolidate=consolidate), tenant, execution)
    assert result.reason == "fenced_out" and mock.calls == [] and consolidate.calls == []
    assert run(_snapshot(db_schema, tenant, execution)) == before                 # ownership still runtime-B


def test_a_takeover_between_steps_stops_the_loop_with_no_further_write(db_schema, run):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    state = _state("golden-loop-takeover", "takeover")
    tenant, execution = _admit(db_schema, run, state)
    first, second, third = _order(state)
    after = {}

    async def take_over_at_second(tenant_id, execution_id, plan_step_id):
        if plan_step_id == second and not after:
            await _take_over(db_schema, execution)
            after["snapshot"] = await _snapshot(db_schema, tenant, execution)
        return AdmissionSnapshot(**PASSING)

    mock, consolidate = _mock(), Recorder()
    result = _loop(db_schema, run, _deps(db_schema, mock, admission=take_over_at_second, consolidate=consolidate),
                   tenant, execution)
    assert result.reason == "fenced_out" and consolidate.calls == [] and len(mock.calls) == 1
    assert (result.steps[first], result.steps[second], result.steps[third]) == (
        ("completed", None), ("pending", None), ("pending", None))
    assert run(_snapshot(db_schema, tenant, execution)) == after["snapshot"]


def test_a_lease_is_never_acquired_once_ownership_has_moved(db_schema, run):
    state = _state("golden-loop-steal", "steal")
    tenant, execution = _admit(db_schema, run, state)
    deps = _deps(db_schema, _mock())
    real, calls, after = deps.leases, [], {}

    async def acquire(**kw):
        calls.append(kw)
        if len(calls) == 2:                                           # just before the second step's lease
            await _take_over(db_schema, execution)
            after["snapshot"] = await _snapshot(db_schema, tenant, execution)
        return await real.acquire(**kw)

    deps = dataclasses.replace(deps, leases=_Proxy(real, acquire=acquire))
    result = _loop(db_schema, run, deps, tenant, execution)
    assert result.reason == "fenced_out"
    assert run(_snapshot(db_schema, tenant, execution)) == after["snapshot"]      # no lease, ownership runtime-B


def test_a_takeover_during_a_provider_call_discards_the_result_and_releases_the_lease(db_schema, run):
    from adapters.runtime.mock_adapter import MockAdapter
    state = _state("golden-loop-midcall", "midcall")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    after = {}

    class TakenOverDuringTheCall(MockAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            result = await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)
            if not after:
                await _take_over(db_schema, execution)
                after["snapshot"] = await _snapshot(db_schema, tenant, execution)
            return result

    mock, consolidate = TakenOverDuringTheCall(Credentials()), Recorder()
    result = _loop(db_schema, run, _deps(db_schema, mock, consolidate=consolidate), tenant, execution)
    assert result.reason == "fenced_out" and consolidate.calls == [] and len(mock.calls) == 1
    assert run(_snapshot(db_schema, tenant, execution)) == after["snapshot"]      # no ledger row, step still running
    steps = _steps(db_schema, run, execution)
    assert (steps[first]["status"], steps[first]["budget"]) == ("running", "locked")   # the new owner probes
    lease_id = run(db_schema.fetchval("SELECT lease_id FROM worker_leases WHERE execution_id = $1", execution))
    assert _moves(db_schema, run, "lease", lease_id) == [(None, "active", "acquired"),
                                                        ("active", "released", "fenced_out")]
    assert run(db_schema.fetchval("SELECT current_load FROM workers WHERE tenant_id = $1", tenant)) == 0


async def _force_plan_update(schema, execution, assignments):
    """Tamper below the application: the table's immutability trigger is bypassed for this one superuser
    transaction (``session_replication_role``), as a direct database write would."""
    await schema.execute("SET LOCAL session_replication_role = replica;"
                         f" UPDATE execution_plans SET {assignments} WHERE execution_id = $x${execution}$x$")


async def _retamper(schema, execution, how):
    from contracts import codec
    from contracts.plan_hash import canonical_plan_digest
    from contracts.stage_outputs import Plan
    if how == "undecodable":
        await _force_plan_update(schema, execution, """canonical_plan = '{"steps": "none"}'::jsonb""")
        return
    raw = await schema.fetchval("SELECT canonical_plan::text FROM execution_plans WHERE execution_id = $1", execution)
    body = json.loads(raw)
    body["steps"][0]["params"] = {**body["steps"][0]["params"], "tampered": True}
    assignments = f"canonical_plan = $j${json.dumps(body)}$j$::jsonb"
    if how == "plan_hash_rewritten":                     # the plan row is consistent again; the manifest is not
        assignments += f", plan_hash = '{canonical_plan_digest(codec.decode(Plan, body))}'"
    await _force_plan_update(schema, execution, assignments)


@pytest.mark.parametrize("how", ["params_changed", "plan_hash_rewritten", "undecodable"])
def test_a_tampered_plan_executes_nothing_and_raises_an_alert(db_schema, run, caplog, how):
    state = _state(f"golden-loop-tamper-{how}", f"tamper-{how}")
    tenant, execution = _admit(db_schema, run, state)
    original = run(db_schema.fetch("SELECT canonical_plan::text AS plan, plan_hash FROM execution_plans"
                                   " WHERE execution_id = $1", execution))[0]
    run(_retamper(db_schema, execution, how))
    mock, consolidate = _mock(), Recorder()
    caplog.set_level(logging.DEBUG)
    try:
        result = _loop(db_schema, run, _deps(db_schema, mock, consolidate=consolidate), tenant, execution)
    finally:                                   # the module's schema is shared: the stored plan must be intact again
        run(_force_plan_update(db_schema, execution, f"canonical_plan = $j${original['plan']}$j$::jsonb,"
                                                     f" plan_hash = '{original['plan_hash']}'"))
    assert result.reason == "plan_integrity" and mock.calls == [] and len(consolidate.calls) == 1
    assert set(result.steps.values()) == {("cancelled", "run_dead_lettered")}
    for table in ("worker_leases", "budget_reservations", "execution_events"):
        assert run(db_schema.fetchval(f"SELECT count(*) FROM {table} WHERE tenant_id = $1", tenant)) == 0, table
    alerts = [r for r in caplog.records if r.levelno >= logging.ERROR and "plan_integrity" in r.getMessage()]
    assert alerts and getattr(alerts[0], "execution_id", None) == execution
    run(assert_system_invariants(db_schema))


# --- the ledger, logs and dispatch (FINAL_ARCHITECTURE §40, §21 S2, S5) ----------------------------------------------

def test_every_provider_call_follows_a_committed_marker(db_schema, run):
    state = _state("golden-loop-i16", "i16")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    _loop(db_schema, run, _deps(db_schema, _mock(**{_ops(state)[first]: {"call": "fail_500_then_success", "n": 1}})),
          tenant, execution)
    called = _events(db_schema, run, execution, "ProviderCalled")
    assert len(called) == 4 and all(e["attempt_id"] and e["provider_call_id"] for e in called)
    run(assert_system_invariants(db_schema))                                  # includes I16


def test_the_execution_ledger_is_append_only_and_tenant_scoped(db_schema, run):
    import asyncpg
    state = _state("golden-loop-ledger", "ledger")
    tenant, execution = _admit(db_schema, run, state)
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    assert _events(db_schema, run, execution)
    for sql in ("UPDATE execution_events SET event_type = 'x' WHERE execution_id = $1",
                "DELETE FROM execution_events WHERE execution_id = $1"):
        with pytest.raises(asyncpg.PostgresError):
            run(db_schema.execute(sql, execution))
    forced = run(db_schema.fetchval("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname ="
                                    " 'execution_events' AND relnamespace = $1::regnamespace", db_schema.name))
    notnull = run(db_schema.fetchval("SELECT is_nullable FROM information_schema.columns WHERE table_schema = $1"
                                     " AND table_name = 'execution_events' AND column_name = 'tenant_id'",
                                     db_schema.name))
    assert forced is True and notnull == "NO"


def test_every_loop_log_line_carries_the_correlation_ids(db_schema, run, caplog):
    state = _state("golden-loop-logs", "logs")
    tenant, execution = _admit(db_schema, run, state)
    caplog.set_level(logging.DEBUG, logger="engine.stages.s12_execute")
    _loop(db_schema, run, _deps(db_schema, _mock()), tenant, execution)
    records = [r for r in caplog.records if r.name.startswith("engine.stages.s12_execute")]
    assert records
    for record in records:
        assert (getattr(record, "tenant_id", None), getattr(record, "execution_id", None),
                getattr(record, "runtime_instance_id", None)) == (tenant, execution, RUNTIME), record.getMessage()
        assert getattr(record, "trace_id", None) == state.execution_context.trace_id
    step_ids = {v["step_id"] for v in _steps(db_schema, run, execution).values()}
    assert step_ids <= {getattr(r, "step_id", None) for r in records}


def test_dispatch_goes_through_the_in_process_dispatcher():
    from engine.stages.s12_execute.dispatch import InProcessDispatcher
    seen = []

    async def body(tenant_id, execution_id):
        seen.append((tenant_id, execution_id))
        return "done"

    async def scenario():
        handle = InProcessDispatcher(body).dispatch("t", "e")
        return await handle

    assert asyncio.run(scenario()) == "done" and seen == [("t", "e")]


def test_no_s12_to_s15_module_schedules_tasks_itself():
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    offenders = [p.relative_to(ROOT).as_posix() for p in s12_files()
                 if p.relative_to(ROOT).as_posix() != "src/engine/stages/s12_execute/dispatch.py"
                 and any(k in p.read_text(encoding="utf-8") for k in ("create_task(", "ensure_future(", "TaskGroup("))]
    assert offenders == []
