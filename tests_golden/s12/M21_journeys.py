"""M21 golden — S0→S15 journeys, the architecture suite, the §21 seams (gate commit M). ★ Owner-pinned.

Gate v10: suite 15 (the eight journeys, S0 → S15), suite 2 (architecture: no resolver, risk or mutation
recomputation; no S8 stage handler import, only the shared check library of C23; no direct adapter call outside the
reliability guard; no durable execution write outside ``fenced_write()``; no filesystem checkpoint code; fault injection
inert outside test mode), the M21 card (no hard-coded hosts, no Laya code), §17 (the invariant checker after every
journey), §21 S1 (settings, no hard-coded infrastructure), S5 (a metrics hook with counters for step outcomes, probes,
dead letters and fenced-out writes; a no-op implementation), the performance baseline (p50 / p95 per-step overhead over
at least 200 steps, recorded, no threshold).

Every journey starts from a state the real S0–S11 pipeline certified (``fixtures/certified.py``), is admitted by the S12
entry (M06), runs the S12 loop with every B3–B4 component (M17's dependencies: guard, verification, consolidation,
dead letters), and ends with the S15 envelope (M18). The S5 resolver is never called after S11.

Interface this file fixes:
  * ``contracts.metrics``: ``MetricsHook`` (``increment(name, **labels)``, ``timing(name, value, **labels)``),
    ``NoMetrics``; names ``STEP_OUTCOME`` ("step_outcome", label ``status``, once per step reaching a terminal
    state), ``PROBE`` ("probe", once per provider probe attempt), ``DEAD_LETTER`` ("dead_letter", label
    ``error_type``, once per record), ``FENCED_OUT`` ("fenced_out", once per loop stopped by ``FencedOut``),
    ``STEP_DURATION_MS`` ("step_duration_ms", once per step the loop runs). ``LoopDeps.metrics`` (default
    ``NoMetrics()``).

Stage 2 amendments (rulings CONF-027 as amended, CONF-049, CONF-052, DEF-003 / D-13):
  * ``adapters.postgres.admission_snapshot.PostgresAdmissionSnapshot(database)`` — the loop's ``admission`` source:
    ``await snapshot(tenant_id, execution_id, plan_step_id) -> AdmissionSnapshot``, read under the tenant's RLS. The
    database-backed gates: ``kill_switch_engaged`` (``tenants.kill_switch_engaged``), ``tenant_active``
    (``tenants.status == 'active'``), ``worker_capacity_available`` (an ACTIVE worker of the tenant with free capacity),
    ``budget_available`` (the tenant's ``budget_pool`` still covers the step). ``adapters.postgres.preflight
    .PostgresPreflight(database)`` — the loop's ``preflight`` source, ``await preflight(step, binding) -> str | None``.
    A journey runs end to end on both real sources.
  * ``engine.stages.s14_dead_letter.operator.DeadLetterOperator(database, *, admin, dead_letters, probe, reverify)``
    — the operator path for dead letters (CONF-049). ``admin`` is the frozen ``AdminService``: every call first takes
    the caller's live role with ``admin.authorize(principal)`` (``AdminError(403, "admin_required")`` otherwise, nothing
    written). ``list_open(principal) -> list[dict]``: the caller's tenant's ``pending`` / ``retrying`` records (keys
    ``dead_letter_id``, ``execution_id``, ``step_id``, ``kernel_op_id``, ``error_type``, ``retry_mode``, ``status``),
    never another tenant's. ``resolve(principal, dead_letter_id, outcome)``: a ``ResolutionOutcome``; settles a LOCKED
    reservation (C21: EXECUTED / UNDETERMINED commit, NOT_EXECUTED releases); never moves the run or the step (D4).
    ``retry(principal, dead_letter_id) -> str`` (the record's status afterwards): PROBE / VERIFY only, through
    ``retry_dead_letter`` with ``probe`` / ``reverify``; a NONE record is refused with ``AdminError(409,
    "retry_not_allowed")`` and nothing written. Another tenant's or an unknown id is ``AdminError(404,
    "dead_letter_not_found")``. Each resolve and retry writes an ``admin_audit`` row (``dead_letter.resolve`` /
    ``dead_letter.retry``, target ``dead_letter``, ``details`` with the outcome or status).
  * ``engine.stages.s12_execute.startup`` — the Worker Runtime start-up checks: ``StartupRefused`` (an Exception with
    ``reason``); ``verifiable(adapter_class) -> bool`` (the class overrides both ``BaseAdapter.probe`` and
    ``BaseAdapter.observe``); ``unverifiable_mutations(database, adapters) -> list[(kernel_op_id, binding_id)]``
    (sorted: every active binding of a PRODUCTION_ENABLED W / D / IRREVERSIBLE kernel operation whose
    ``adapter_class`` is missing from ``adapters`` (name → class) or not verifiable; ``tools/registry_readiness.py``
    reports the same list); ``check_worker_runtime(database, adapters)`` refuses with reason ``privileged_role`` when
    the database role is a superuser or has BYPASSRLS (DEF-003, as ``app.py`` does for the API), then with reason
    ``unverifiable_mutation`` when that list is not empty (CONF-052).
"""
from __future__ import annotations

import ast
import dataclasses
import re
import statistics

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import _admit, _order, _ops, _state


class Metrics:
    def __init__(self):
        self.counts, self.timings = [], []

    def increment(self, name, **labels):
        self.counts.append((name, dict(labels)))

    def timing(self, name, value, **labels):
        self.timings.append((name, value))

    def count(self, name, **labels):
        return sum(1 for n, got in self.counts if n == name and all(got.get(k) == v for k, v in labels.items()))


def _mocked(**programs):
    from tests_golden.s12.M12_loop import _mock as mock
    return mock(**programs)


def _deps(schema, mock, *, metrics=None, faults=None, runtime="runtime-A"):
    from engine.stages.s12_execute.fault_injection import NoFaults
    from tests_golden.s12.M17_dead_letter import _dl_deps
    return dataclasses.replace(_dl_deps(schema, mock), metrics=metrics or Metrics(), faults=faults or NoFaults(),
                               runtime_instance_id=runtime)


def _envelope(schema, run, tenant, execution):
    from adapters.postgres.run_summary import PostgresRunSummaries
    from engine.stages.s15_final_state.response import build_envelope
    return build_envelope(run(PostgresRunSummaries(schema.database()).load(tenant, execution)))


class _Trap:
    """After S11 nothing may resolve again (suite 2). Armed once the fixture certified the state (S0–S11 runs S5)."""
    def __init__(self, monkeypatch):
        self.monkeypatch, self.calls = monkeypatch, []

    def arm(self):
        def refuse(*args, **kwargs):
            self.calls.append(args)
            raise AssertionError("S5 re-resolution after S11")
        self.monkeypatch.setattr("engine.stages.s5_provider_resolution.handler.handle", refuse)


@pytest.fixture
def no_reresolution(monkeypatch):
    return _Trap(monkeypatch)          # an armed trap fails the journey by raising where the call happens


def _journey(schema, run, name, *, trap, programs=None, budget_pool=1000, retry_safety="safe", metrics=None):
    from engine.stages.s12_execute.loop import run_execution
    state = _state(f"golden-journey-{name}", f"journey{name}")
    trap.arm()
    tenant, execution = _admit(schema, run, state, budget_pool=budget_pool, retry_safety=retry_safety)
    mock = _mocked(**{_ops(state)[sid]: p for sid, p in (programs or {}).items()})
    result = run(run_execution(_deps(schema, mock, metrics=metrics), tenant, execution))
    return state, tenant, execution, mock, result


# --- the eight journeys (suite 15) -----------------------------------------------------------------------------------

def test_journey_happy_path_with_dependencies(db_schema, run, no_reresolution):
    state, tenant, execution, mock, _ = _journey(db_schema, run, "happy", trap=no_reresolution)
    env = _envelope(db_schema, run, tenant, execution)
    assert env.status == "ok" and [s["position"] for s in env.data["steps"]] == [1, 2, 3]
    assert all(s.depends_on for s in state.plan.plan.steps[1:])                     # a chain: each needs the last
    called = [m.idempotency_key.split(":")[-1] for m in mock.calls]
    assert called == _order(state)                                                   # in dependency order
    run(assert_system_invariants(db_schema))


def test_journey_retry_then_success(db_schema, run, no_reresolution):
    state = _state("golden-journey-retry", "journeyretry")
    second = _order(state)[1]
    state, tenant, execution, mock, _ = _journey(db_schema, run, "retry", trap=no_reresolution,
                                                 programs={second: {"call": "fail_500_then_success", "n": 1}})
    assert _envelope(db_schema, run, tenant, execution).status == "ok"
    ids = [m.attempt_id for m in mock.calls if m.idempotency_key.endswith(f":{second}")]
    assert ids == ["att-1-1", "att-1-2"]
    run(assert_system_invariants(db_schema))


def test_journey_timeout_executed_resolved_by_the_probe(db_schema, run, no_reresolution):
    state = _state("golden-journey-texec", "journeytexec")
    first = _order(state)[0]
    state, tenant, execution, mock, _ = _journey(db_schema, run, "texec", trap=no_reresolution,
                                                 programs={first: {"call": "timeout_executed"}})
    assert _envelope(db_schema, run, tenant, execution).status == "ok"
    assert len(mock.probes) == 1 and mock.side_effects(f"{state.execution_context.request_id}:{first}") == 1
    run(assert_system_invariants(db_schema))


def test_journey_timeout_not_executed_then_retry(db_schema, run, no_reresolution):
    state = _state("golden-journey-tnot", "journeytnot")
    first = _order(state)[0]
    state, tenant, execution, mock, _ = _journey(db_schema, run, "tnot", trap=no_reresolution,
                                                 programs={first: {"call": "timeout_not_executed", "n": 1}})
    assert _envelope(db_schema, run, tenant, execution).status == "ok"
    ids = [m.attempt_id for m in mock.calls if m.idempotency_key.endswith(f":{first}")]
    assert ids == ["att-0-1", "att-0-2"] and len(mock.probes) == 1
    run(assert_system_invariants(db_schema))


def test_journey_verification_mismatch_leads_to_partial(db_schema, run, no_reresolution):
    state = _state("golden-journey-mismatch", "journeymismatch")
    second = _order(state)[1]
    state, tenant, execution, _, _ = _journey(db_schema, run, "mismatch", trap=no_reresolution,
                                              programs={second: {"call": "verify_mismatch"}})
    env = _envelope(db_schema, run, tenant, execution)
    assert env.status == "partial"
    assert env.error.details["failed_steps"] == [{"position": 2, "operation": _ops(state)[second], "status": "failed"}]
    letters = run(db_schema.fetch("SELECT error_type, retry_mode FROM dead_letters WHERE execution_id = $1",
                                  execution))
    assert [tuple(r) for r in letters] == [("data", "NONE")]
    run(assert_system_invariants(db_schema))


def test_journey_budget_exhaustion_mid_plan(db_schema, run, no_reresolution):
    state = _state("golden-journey-budget", "journeybudget")
    pool = state.plan.plan.steps[0].cost
    state, tenant, execution, _, result = _journey(db_schema, run, "budget", trap=no_reresolution, budget_pool=pool)
    assert (result.run_status, result.reason) == ("cancelled", "budget_exhausted")
    env = _envelope(db_schema, run, tenant, execution)
    assert (env.status, env.error.type) == ("error", "budget_exceeded")
    assert env.error.details["completed_steps"] == [{"position": 1, "operation": _ops(state)[_order(state)[0]],
                                                     "status": "completed"}]
    run(assert_system_invariants(db_schema))


def test_journey_inconclusive_probe_leads_to_dead_letter(db_schema, run, no_reresolution):
    state = _state("golden-journey-dl", "journeydl")
    first = _order(state)[0]
    metrics = Metrics()
    state, tenant, execution, _, _ = _journey(db_schema, run, "dl", trap=no_reresolution, metrics=metrics, programs={
        first: {"call": "timeout_executed", "probe": "inconclusive"}})
    env = _envelope(db_schema, run, tenant, execution)
    assert env.status == "error" and env.error.recoverable is False
    assert run(db_schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution)) == \
        "dead_letter"
    assert metrics.count("probe") == 3 and metrics.count("dead_letter", error_type="unknown_unresolved") == 1
    assert metrics.count("step_outcome", status="dead_letter") == 1
    assert metrics.count("step_outcome", status="cancelled") == len(_order(state)) - 1
    run(assert_system_invariants(db_schema))


def test_journey_crash_mid_plan_then_resume_to_completed(db_schema, run, no_reresolution):
    from tests_golden.s12.M19_recovery import CrashAt, _crash, _sweep, _time_passes
    state = _state("golden-journey-crash", "journeycrash")
    no_reresolution.arm()
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    _crash(db_schema, run, _deps(db_schema, mock, faults=CrashAt("after_commit_before_checkpoint", nth=2)), tenant,
           execution)
    _time_passes(db_schema, run, execution)
    _sweep(db_schema, run, _deps(db_schema, mock, runtime="runtime-B"))
    assert _envelope(db_schema, run, tenant, execution).status == "ok"
    for sid in _order(state):
        assert mock.side_effects(f"{state.execution_context.request_id}:{sid}") == 1, sid
    run(assert_system_invariants(db_schema))


# --- metrics seam and the performance baseline (§21 S5, performance baseline) ----------------------------------------

# --- the real admission and pre-flight sources (CONF-027 as amended) --------------------------------------------------

def test_journey_on_the_real_admission_and_preflight_sources(db_schema, run, no_reresolution):
    from adapters.postgres.admission_snapshot import PostgresAdmissionSnapshot
    from adapters.postgres.preflight import PostgresPreflight
    from engine.stages.s12_execute.loop import run_execution
    state = _state("golden-journey-realsources", "journeyrealsources")
    no_reresolution.arm()
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    db = db_schema.database()
    deps = dataclasses.replace(_deps(db_schema, mock), admission=PostgresAdmissionSnapshot(db),
                               preflight=PostgresPreflight(db))
    run(run_execution(deps, tenant, execution))
    env = _envelope(db_schema, run, tenant, execution)
    assert env.status == "ok" and [s["position"] for s in env.data["steps"]] == [1, 2, 3]
    run(assert_system_invariants(db_schema))


HEALTHY = dict(kill_switch_engaged=False, tenant_active=True, worker_capacity_available=True, budget_available=True)
GATE_CASES = [
    # case, the database change (tenant-scoped, $1 = tenant), the gate it must flip
    ("healthy", None, None),
    ("kill_switch", "UPDATE tenants SET kill_switch_engaged = true WHERE tenant_id = $1", "kill_switch_engaged"),
    ("tenant_suspended", "UPDATE tenants SET status = 'suspended' WHERE tenant_id = $1", "tenant_active"),
    ("no_free_worker", "UPDATE workers SET state = 'DRAINING' WHERE tenant_id = $1", "worker_capacity_available"),
    ("budget_spent", "UPDATE tenants SET budget_pool = 0 WHERE tenant_id = $1", "budget_available"),
]


@pytest.mark.parametrize("case,change,gate", GATE_CASES, ids=[c[0] for c in GATE_CASES])
def test_the_admission_snapshot_reads_each_database_backed_gate(db_schema, run, case, change, gate):
    from adapters.postgres.admission_snapshot import PostgresAdmissionSnapshot
    index = [c[0] for c in GATE_CASES].index(case)
    state = _state(f"golden-snapshot-{index}", f"snapshot{index}")
    tenant, execution = _admit(db_schema, run, state)
    if change is not None:
        run(db_schema.execute(change, tenant, tenant=tenant))
    snap = run(PostgresAdmissionSnapshot(db_schema.database())(tenant, execution, _order(state)[0]))
    expected = dict(HEALTHY)
    if gate is not None:
        expected[gate] = not expected[gate]
    assert {name: getattr(snap, name) for name in HEALTHY} == expected


# --- the operator path for dead letters (CONF-049) ---------------------------------------------------------------------

def _principal(schema, run, state, role):
    from contracts.principal import Principal
    ctx = state.execution_context
    membership = f"m-{role}-{ctx.tenant_id}"
    run(schema.execute("INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role, is_active)"
                       " VALUES ($1, $2, $3, $4, $5, true) ON CONFLICT DO NOTHING", membership, ctx.tenant_id,
                       ctx.user_id, ctx.workspace_id, role, tenant=ctx.tenant_id))
    return Principal(ctx.tenant_id, ctx.workspace_id, ctx.user_id, membership, "conn-1", "")


def _operator(schema, *, probe=None, reverify=None):
    from adapters.postgres.admin import AdminService
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from engine.stages.s14_dead_letter.operator import DeadLetterOperator

    async def never(record):
        raise AssertionError("not expected to be asked")
    db = schema.database()
    return DeadLetterOperator(db, admin=AdminService(db, None), dead_letters=PostgresDeadLetters(db),
                              probe=probe or never, reverify=reverify or never)


def _audit(schema, run, tenant, target):
    rows = run(schema.fetch("SELECT action, target_type, details FROM admin_audit WHERE tenant_id = $1"
                            " AND target_id = $2 ORDER BY audit_id", tenant, target))
    return [(r["action"], r["target_type"], r["details"]) for r in rows]


def test_an_admin_lists_and_resolves_only_their_tenants_dead_letters(db_schema, run, no_reresolution):
    from adapters.postgres.admin import AdminError
    first = _order(_state("golden-journey-operator", "journeyoperator"))[0]
    state, tenant, execution, _, _ = _journey(db_schema, run, "operator", trap=no_reresolution, programs={
        first: {"call": "timeout_executed", "probe": "inconclusive"}})
    other = _state("golden-journey-operator-other", "journeyoperatorother")
    _admit(db_schema, run, other)
    admin, member = _principal(db_schema, run, state, "admin"), _principal(db_schema, run, state, "member")
    stranger = _principal(db_schema, run, other, "owner")
    operator = _operator(db_schema)
    (listed,) = run(operator.list_open(admin))
    assert (listed["execution_id"], listed["retry_mode"], listed["status"]) == (execution, "PROBE", "pending")
    assert run(operator.list_open(stranger)) == []                                # never another tenant's
    letter = listed["dead_letter_id"]
    for who, status in ((member, 403), (stranger, 404)):
        with pytest.raises(AdminError) as refused:
            run(operator.resolve(who, letter, "NOT_EXECUTED"))
        assert refused.value.status == status
    step = run(db_schema.fetch("SELECT s.status, b.status AS budget FROM execution_steps s JOIN budget_reservations b"
                               " ON b.reservation_id = s.reservation_id WHERE s.step_id = $1", listed["step_id"]))[0]
    assert (step["status"], step["budget"]) == ("dead_letter", "locked")          # nothing written by a refusal
    run(operator.resolve(admin, letter, "NOT_EXECUTED"))
    row = run(db_schema.fetch("SELECT d.status, d.resolution_outcome, b.status AS budget, s.status AS step,"
                              " r.status AS run FROM dead_letters d JOIN budget_reservations b"
                              " ON b.reservation_id = d.reservation_id JOIN execution_steps s ON s.step_id = d.step_id"
                              " JOIN execution_runs r ON r.execution_id = d.execution_id WHERE d.dead_letter_id = $1",
                              letter))[0]
    assert (row["status"], row["resolution_outcome"], row["budget"]) == ("resolved", "NOT_EXECUTED", "released")
    assert (row["step"], row["run"]) == ("dead_letter", "dead_letter")           # D4: never moves the run or step
    assert [(a, t) for a, t, _ in _audit(db_schema, run, tenant, letter)] == [("dead_letter.resolve", "dead_letter")]
    assert run(operator.list_open(admin)) == []
    run(assert_system_invariants(db_schema))


def test_the_operator_retries_probe_records_and_refuses_none(db_schema, run):
    from adapters.postgres.admin import AdminError
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from contracts.adapter_interface import ProbeOutcome
    from tests_golden.s12.M12_loop import _steps
    from tests_golden.s12.M16_consolidation import _holder
    state = _state("golden-operator-retry", "operatorretry")
    tenant, execution = _admit(db_schema, run, state)
    holder = _holder(db_schema, run, tenant, execution)
    steps = _steps(db_schema, run, execution)
    first, second = _order(state)[:2]
    letters = PostgresDeadLetters(db_schema.database())
    probe_letter = run(letters.create(holder, step_id=steps[first]["step_id"], kernel_op_id=_ops(state)[first],
                                      error_type="unknown_unresolved", retry_mode="PROBE", error="probe_exhausted",
                                      evidence={"attempts": 3}))
    none_letter = run(letters.create(holder, step_id=steps[second]["step_id"], kernel_op_id=_ops(state)[second],
                                     error_type="data", retry_mode="NONE", error="verification_failed",
                                     evidence={"layers": [{"verdict": "FAIL"}]}))
    asked = []

    async def probe(record):
        asked.append(record.dead_letter_id)
        return ProbeOutcome.EXECUTED_SUCCESS
    admin = _principal(db_schema, run, state, "owner")
    operator = _operator(db_schema, probe=probe)
    with pytest.raises(AdminError) as refused:
        run(operator.retry(admin, none_letter))
    assert (refused.value.status, refused.value.reason) == (409, "retry_not_allowed")
    row = run(db_schema.fetch("SELECT status, retry_count FROM dead_letters WHERE dead_letter_id = $1",
                              none_letter))[0]
    assert (row["status"], row["retry_count"]) == ("pending", 0) and _audit(db_schema, run, tenant, none_letter) == []
    assert run(operator.retry(admin, probe_letter)) == "resolved" and asked == [probe_letter]
    assert [(a, t) for a, t, _ in _audit(db_schema, run, tenant, probe_letter)] == [("dead_letter.retry", "dead_letter")]
    run(assert_system_invariants(db_schema))


# --- Worker Runtime start-up (DEF-003 / D-13, CONF-052 / D-12) ----------------------------------------------------------

def test_a_worker_runtime_refuses_a_privileged_database_role(db_schema, run):
    import asyncpg
    from adapters.postgres.database import Database
    from adapters.runtime.mock_adapter import MockAdapter
    from engine.stages.s12_execute.startup import StartupRefused, check_worker_runtime
    from tests_golden.fixtures.db import golden_database_url
    run(check_worker_runtime(db_schema.database(), {"MockAdapter": MockAdapter}))      # golden_app: allowed
    pool = run(asyncpg.create_pool(golden_database_url(), min_size=1, max_size=1,
                                   server_settings={"search_path": db_schema.name}))
    try:
        with pytest.raises(StartupRefused) as refused:
            run(check_worker_runtime(Database(pool), {"MockAdapter": MockAdapter}))  # the test's superuser
        assert refused.value.reason == "privileged_role"
    finally:
        run(pool.close())


def test_only_verifying_adapters_may_carry_production_mutations(db_schema, run):
    from adapters.runtime.mock_adapter import MockAdapter
    from contracts.adapter_interface import BaseAdapter, ProbeOutcome
    from contracts.step_execution import AdapterResult
    from engine.stages.s12_execute.startup import (StartupRefused, check_worker_runtime, unverifiable_mutations,
                                                   verifiable)

    class Bare(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            return AdapterResult("ok")

    class ProbeOnly(Bare):
        async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
            return ProbeOutcome.NOT_EXECUTED

    assert verifiable(MockAdapter) and not verifiable(Bare) and not verifiable(ProbeOnly)
    state = _state("golden-startup-enablement", "startupenablement")
    _admit(db_schema, run, state)
    ours = {b.binding_id for b in state.frozen_bindings}
    writes = sorted((b.kernel_op_id, b.binding_id) for b in state.frozen_bindings if b.effective_mutation != "R")
    assert writes and len(writes) < len(ours)                                      # reads are never listed
    db = db_schema.database()

    def listed(adapters):
        return [pair for pair in run(unverifiable_mutations(db, adapters)) if pair[1] in ours]
    assert listed({"MockAdapter": MockAdapter}) == []
    assert listed({"MockAdapter": Bare}) == writes == listed({"MockAdapter": ProbeOnly}) == listed({})
    with pytest.raises(StartupRefused) as refused:
        run(check_worker_runtime(db, {"MockAdapter": Bare}))
    assert refused.value.reason == "unverifiable_mutation"


def test_a_fenced_out_loop_is_counted(db_schema, run):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    from engine.stages.s12_execute.loop import run_execution
    from tests_golden.s12.M12_loop import PASSING, _take_over
    state = _state("golden-journey-fenced", "journeyfenced")
    tenant, execution = _admit(db_schema, run, state)
    second = _order(state)[1]
    moved = []

    async def take_over_at_second(tenant_id, execution_id, plan_step_id):
        if plan_step_id == second and not moved:
            await _take_over(db_schema, execution)
            moved.append(True)
        return AdmissionSnapshot(**PASSING)

    metrics = Metrics()
    deps = dataclasses.replace(_deps(db_schema, _mocked(), metrics=metrics), admission=take_over_at_second)
    assert run(run_execution(deps, tenant, execution)).reason == "fenced_out"
    assert metrics.count("fenced_out") == 1 and metrics.count("step_outcome", status="completed") == 1


def test_the_metrics_hook_is_a_no_op_by_default():
    from contracts.metrics import NoMetrics
    from engine.stages.s12_execute.loop import LoopDeps
    default = {f.name: f for f in dataclasses.fields(LoopDeps)}["metrics"].default
    assert isinstance(default, NoMetrics)
    assert default.increment("step_outcome", status="completed") is None and default.timing("x", 1.0) is None


def test_the_per_step_overhead_baseline_can_be_recorded_over_200_steps(db_schema, run, capsys):
    """Record only (no threshold): p50 / p95 of the loop's per-step time with a zero-delay mock (gate §21)."""
    from engine.stages.s12_execute.loop import run_execution
    metrics = Metrics()
    for i in range(70):
        state = _state(f"golden-journey-perf-{i}", f"journeyperf{i}")
        tenant, execution = _admit(db_schema, run, state)
        run(run_execution(_deps(db_schema, _mocked(), metrics=metrics), tenant, execution))
    samples = [v for name, v in metrics.timings if name == "step_duration_ms"]
    assert len(samples) >= 200 and all(v > 0 for v in samples)
    p50, p95 = statistics.median(samples), statistics.quantiles(samples, n=20)[-1]
    assert p95 >= p50 > 0
    with capsys.disabled():
        print(f"\nS12 per-step overhead baseline over {len(samples)} steps: p50 {p50:.1f} ms, p95 {p95:.1f} ms")


# --- the architecture suite (suite 2, M21 card) ----------------------------------------------------------------------

def _s12_sources():
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in s12_files()}


def _imports(text):
    out = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


ALLOWED_OUTSIDE = (          # every engine import of S12–S15 code outside S12–S15, with its reason
    "engine.stages.plan_steps",              # the step → binding index S4 recorded (no resolution)
    "engine.control_plane.scope",            # the run scope LiveAuthorizationCheck reads (C23)
    "engine.stages.s8_safety_gate.checks",   # the shared check library (C23), the only S8 code allowed
    "engine.stages.s8_safety_gate.dependencies",   # the S8 CircuitBreaker protocol the breaker implements
    "engine.stages.s0_entry.activation",     # the pause / activation check the S12 entry repeats (C39)
)


def test_s12_to_s15_code_never_re_resolves_and_imports_no_stage_handler():
    offenders = []
    for path, text in _s12_sources().items():
        for module in _imports(text):
            if not module.startswith("engine."):
                continue
            if module.startswith(("engine.stages.s12", "engine.stages.s13", "engine.stages.s14",
                                  "engine.stages.s15")):
                continue
            if module == "engine.stages.s8_safety_gate" or module.startswith(ALLOWED_OUTSIDE):
                continue
            offenders.append(f"{path}: {module}")
    handler = [f"{p}: {m}" for p, t in _s12_sources().items() for m in _imports(t) if "s8_safety_gate.handler" in m]
    assert offenders == [] and handler == []


def test_no_adapter_is_called_outside_the_reliability_guard():
    guards = ("src/engine/stages/s12_execute/reliability.py",
              "src/engine/stages/s12_execute/guard.py")          # the prototype guard (CONF-011) is a guard too
    direct = re.compile(r"\b\w*adapter\w*\.(call|probe|observe)\(", re.I)
    offenders = [p for p, t in _s12_sources().items()
                 if p not in guards and p.startswith("src/engine/") and direct.search(t)]
    concrete = [f"{p}: {m}" for p, t in _s12_sources().items() if p.startswith("src/engine/")
                for m in _imports(t) if m.startswith(("adapters.runtime.mock_adapter", "engine.providers"))]
    assert offenders == [] and concrete == []


_WRITE = re.compile(r"(?<!FOR )\b(INSERT INTO|UPDATE|DELETE FROM)\s+([a-z_]+)\b", re.I)
EXECUTION_TABLES = ("execution_runs", "execution_steps", "budget_reservations", "step_reconciliations",
                    "dead_letters", "idempotency_ledger", "execution_events", "checkpoints")
UNFENCED_BY_DESIGN = {
    "src/adapters/postgres/admission.py": "the §7.2 admission transaction creates the ownership row: no fence yet",
    "src/adapters/postgres/cancellation.py": "C16: the user's cancellation request, recorded without a lease",
}


def test_no_durable_execution_write_happens_outside_fenced_write():
    offenders = []
    for path, text in _s12_sources().items():
        tables = {m.group(2).lower() for m in _WRITE.finditer(text)} & set(EXECUTION_TABLES)
        if not tables:
            continue
        if path.startswith("src/engine/"):
            offenders.append(f"{path}: SQL writes belong to the adapters")
        elif path not in UNFENCED_BY_DESIGN and "fenced_write" not in text and "check_fence" not in text:
            offenders.append(f"{path}: writes {sorted(tables)} without fenced_write")
    assert offenders == []


def test_no_filesystem_checkpoints_no_hard_coded_hosts_and_no_laya():
    banned = {
        "filesystem": re.compile(r"(?<![.\w])(?<!def )open\(|\.write_text\(|\.write_bytes\(|\bpickle\b|\bshelve\b"),
        "host": re.compile(r"localhost|127\.0\.0\.1|postgres(ql)?://|https?://|:5432\b"),
        "laya": re.compile(r"laya", re.I),
    }
    offenders = [f"{kind}: {path}" for path, text in _s12_sources().items()
                 for kind, pattern in banned.items() if pattern.search(text)]
    assert offenders == []


def test_fault_injection_has_no_switch_outside_the_tests():
    text = _s12_sources()["src/engine/stages/s12_execute/fault_injection.py"]
    assert "environ" not in text and "getenv" not in text
    from engine.stages.s12_execute.fault_injection import NoFaults
    from engine.stages.s12_execute.loop import LoopDeps
    assert isinstance({f.name: f for f in dataclasses.fields(LoopDeps)}["faults"].default, NoFaults)


def test_infrastructure_settings_come_from_the_environment_and_are_validated():
    from engine.stages.s12_execute.settings import ExecutionSettings
    env = {"S12_ADAPTER_CLIENT_TIMEOUT_S": "5", "S12_STEP_TIMEOUT_S": "30", "S12_PROBE_TIMEOUT_S": "5",
           "S12_LEASE_TTL_S": "30", "S12_LEASE_RENEWAL_INTERVAL_S": "10"}
    settings = ExecutionSettings.from_env(env)
    assert (settings.step_timeout_s, settings.lease_ttl_s) == (30.0, 30.0)
    with pytest.raises(ValueError):
        ExecutionSettings.from_env({**env, "S12_STEP_TIMEOUT_S": "4"})         # inverted timeouts (C37)
    assert 0 < settings.recovery_sweep_interval_s < 30                           # §13: under 30 seconds
    assert ExecutionSettings.from_env({**env, "S12_RECOVERY_SWEEP_INTERVAL_S": "5"}).recovery_sweep_interval_s == 5
    for bad in ("30", "0", "soon"):
        with pytest.raises(ValueError):
            ExecutionSettings.from_env({**env, "S12_RECOVERY_SWEEP_INTERVAL_S": bad})


def test_every_move_on_these_paths_is_legal(db_schema, run):
    run(assert_system_invariants(db_schema))
