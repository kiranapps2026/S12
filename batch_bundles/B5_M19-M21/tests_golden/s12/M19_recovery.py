"""M19 golden — crash recovery and fault injection (gate commit L part 1). Owner-pinned.

Gate v10: §13 (on start a new ``runtime_instance_id``; the sweeper finds RUNNING / RECONCILING runs with no usable
lease; step 1 takeover with a new, larger token and the ownership compare-and-set, ``FOR UPDATE SKIP LOCKED``; 1a the
live check — on REVOKED the in-flight step is resolved, then the run cancelled, never resumed; 2 the plan digest; 3 the
single in-flight decision rule; 4 the loop continues from the first PENDING step; expired leases are never
reactivated; the database is the truth), §15.2 (the ten named injection points, ``SimulatedCrash`` in test mode only,
inert otherwise; the in-process crash discards the Worker Runtime and recovers in a fresh one), C14 (a LOCKED
reservation is resolved only by the probe outcome), C26, C35 (the dispatch marker: no marker → NOT_EXECUTED without a
probe; marker → probe; the existing reservation is reused, a new one only for a retry after NOT_EXECUTED), suite 6
(Crash A, B, C; cached failure at recovery; expired record at recovery), suite 14, suite 16b (recovery after
revocation), suite 19 (C35 rows); invariants I1–I16 (I4 through the mock's side-effect ledger).
Rulings: CONF-033 (a sweeper never takes an execution its own runtime owns), CONF-042 (cross-tenant discovery through
``s12_recovery_candidates``, ids only), CONF-043 (an in-flight step of a tampered plan is dead-lettered, never probed).

Interface this file fixes:
  * ``engine.stages.s12_execute.fault_injection``: ``POINTS`` (the ten names of §15.2, in that order);
    ``SimulatedCrash`` (a BaseException, so no ``except Exception`` swallows it); ``NoFaults`` (``hit(point)``: inert,
    ValueError for an unknown name). ``LoopDeps.faults`` (default ``NoFaults()``) is called at every point:
    after_lease_acquire (lease held, nothing reserved), after_budget_reserve (reservation RESERVED),
    after_budget_lock (step RUNNING, reservation LOCKED, no dispatch marker), after_dispatch_marker_before_call,
    after_adapter_call_before_ledger, after_ledger_before_verification, during_verification (after the first layer
    result is persisted), after_verification_before_step_commit, after_commit_before_checkpoint (step COMPLETED,
    lease still held), during_probe (after a probe attempt started).
  * ``engine.stages.s12_execute.loop.recover_execution(deps, tenant_id, execution_id) -> LoopResult``: lapsed leases
    of the execution are expired (``ttl_elapsed``); takeover through ``PostgresLeaseManager.acquire(...,
    skip_locked=True)`` (holder None) on an eligible worker; none possible → reason ``not_orphaned``, nothing else
    written; then §13 steps 1a–4. In-flight rule: RUNNING → ``pending_probe (recovery)``, TIMEOUT → ``pending_probe
    (step_timeout_probe)``; an open episode is continued (a lost ``reconciling`` attempt is recorded
    ``inconclusive``); else ledger success with every required layer PASS recorded → a VERIFICATION episode opened and
    closed LEDGER_HIT, ``completed (ledger_hit_success)``; ledger success otherwise → a VERIFICATION episode
    (``verification_passed``); ledger failure → an EXECUTION episode closed LEDGER_HIT, ``failed
    (ledger_hit_failure)``; no record and no marker → an EXECUTION episode closed NOT_EXECUTED (evidence
    ``no_dispatch_marker``), ``pending (no_dispatch_marker)``, budget released ``no_dispatch_marker``; otherwise an
    EXECUTION episode and the probe. A retried step resumes at the attempt after its last dispatched one.
  * ``engine.stages.s12_execute.recovery.RecoverySweeper(database, deps, *, batch=10)``: ``candidates()``,
    ``sweep() -> [(tenant_id, execution_id, LoopResult)]`` and ``run(stop, *, interval_s) -> int`` (sweeps until the
    ``asyncio.Event`` is set, waiting ``interval_s`` between sweeps; ValueError unless 0 < interval_s < 30, §13).
    ``ExecutionSettings.recovery_sweep_interval_s`` (``S12_RECOVERY_SWEEP_INTERVAL_S``, default 10, < 30).
  * ``PostgresLeaseManager.acquire`` gains ``skip_locked`` (default False); ``expire_lapsed(tenant_id, execution_id)``.
  * ``PostgresEpisodes.find_open(tenant_id, step_id)``; ``PostgresExecutionEvents.layer_verdicts(tenant_id,
    step_id)``; migration 017 ``s12_recovery_candidates(runtime_instance_id, limit, orphan_after_s)`` (SECURITY
    DEFINER, search_path pinned with pg_temp last; a run never leased is a candidate only after ``orphan_after_s``, the lease TTL, CONF-046).
    ``RecoverySweeper.sweep`` isolates each run: an error recovering one is logged at ERROR (``recovery_failed``, the
    run and the error type) and the sweep goes on; a ``SimulatedCrash`` is never caught.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import _admit, _moves, _order, _ops, _state, _steps

CRASHED, RECOVERING = "runtime-A", "runtime-B"


class CrashAt:
    """A test's FaultInjector: raises SimulatedCrash at the nth hit of ``point``; records every hit."""
    def __init__(self, point, nth=1):
        self.point, self.nth, self.hits = point, nth, []

    def hit(self, point):
        from engine.stages.s12_execute.fault_injection import POINTS, SimulatedCrash
        assert point in POINTS, point
        self.hits.append(point)
        if point == self.point and self.hits.count(point) == self.nth:
            raise SimulatedCrash(point)


def _mocked(**programs):
    from tests_golden.s12.M12_loop import _mock as mock
    return mock(**programs)


def _full(schema, mock, *, runtime=CRASHED, faults=None, live=None):
    from engine.stages.s12_execute.fault_injection import NoFaults
    from tests_golden.s12.M17_dead_letter import _dl_deps
    deps = _dl_deps(schema, mock)
    return dataclasses.replace(deps, runtime_instance_id=runtime, faults=faults or NoFaults(),
                               live=live or deps.live)


def _crash(schema, run, deps, tenant, execution):
    from engine.stages.s12_execute.fault_injection import SimulatedCrash
    from engine.stages.s12_execute.loop import run_execution
    with pytest.raises(SimulatedCrash):
        run(run_execution(deps, tenant, execution))


def _time_passes(schema, run, execution):
    """The crashed runtime's lease runs out (its TTL elapses; nothing renews it)."""
    run(schema.execute("UPDATE worker_leases SET expires_at = now() - interval '1 second' WHERE execution_id = $1"
                       " AND status = 'active'", execution))


def _sweep(schema, run, deps):
    from engine.stages.s12_execute.recovery import RecoverySweeper
    return run(RecoverySweeper(schema.database(), deps).sweep())


def _run_status(schema, run, execution):
    return run(schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution))


def _reservations(schema, run, step_id):
    return [r["status"] for r in run(schema.fetch("SELECT status FROM budget_reservations WHERE step_id = $1"
                                                  " ORDER BY created_at", step_id))]


def _episodes(schema, run, step_id):
    return [dict(r) for r in run(schema.fetch("SELECT episode_id, kind, status, outcome, evidence FROM"
                                              " step_reconciliations WHERE step_id = $1 ORDER BY opened_at", step_id))]


def _key(state, sid):
    return f"{state.execution_context.request_id}:{sid}"


# --- the injection points (§15.2) ------------------------------------------------------------------------------------

def test_the_ten_points_are_named_inert_by_default_and_a_crash_is_never_swallowed():
    from engine.stages.s12_execute.fault_injection import POINTS, NoFaults, SimulatedCrash
    from engine.stages.s12_execute.loop import LoopDeps
    assert POINTS == ("after_lease_acquire", "after_budget_reserve", "after_budget_lock",
                      "after_dispatch_marker_before_call", "after_adapter_call_before_ledger",
                      "after_ledger_before_verification", "during_verification",
                      "after_verification_before_step_commit", "after_commit_before_checkpoint", "during_probe")
    faults = NoFaults()
    for point in POINTS:
        assert faults.hit(point) is None
    with pytest.raises(ValueError):
        faults.hit("somewhere_else")
    assert issubclass(SimulatedCrash, BaseException) and not issubclass(SimulatedCrash, Exception)
    default = {f.name: f for f in dataclasses.fields(LoopDeps)}["faults"]
    assert isinstance(default.default, NoFaults)


def test_every_point_is_wired_and_nothing_in_the_product_raises_a_simulated_crash():
    from engine.stages.s12_execute.fault_injection import POINTS
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    home = "src/engine/stages/s12_execute/fault_injection.py"
    text = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in s12_files()}
    wired = "\n".join(t for path, t in text.items() if path != home)
    assert [p for p in POINTS if f'hit("{p}")' not in wired] == []
    assert [path for path, t in text.items() if "raise SimulatedCrash" in t] == []
    assert [path for path, t in text.items() if path != home and "SimulatedCrash" in t] == []


# --- crash, then recover in a fresh Worker Runtime (§13, suite 6, suite 14) -------------------------------------------

POINT_CASES = [
    # point, first step's program, what recovery must do with the first step
    ("after_lease_acquire", {}, "fresh"),
    ("after_budget_reserve", {}, "reuses_reservation"),
    ("after_budget_lock", {}, "not_executed_without_probe"),
    ("after_dispatch_marker_before_call", {}, "probe_then_retry"),
    ("after_adapter_call_before_ledger", {}, "crash_a"),
    ("after_ledger_before_verification", {}, "crash_b"),
    ("during_verification", {}, "crash_b"),
    ("after_verification_before_step_commit", {}, "crash_c_all_passed"),
    ("after_commit_before_checkpoint", {}, "already_completed"),
    ("during_probe", {"call": "timeout_executed"}, "probe_continued"),
]


@pytest.mark.parametrize("point,program,expected", POINT_CASES, ids=[c[0] for c in POINT_CASES])
def test_a_crash_at_every_point_recovers_to_completed_without_a_second_side_effect(db_schema, run, point, program,
                                                                                    expected):
    state = _state(f"golden-rec-{point}", f"rec{POINT_CASES.index((point, program, expected))}")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    mock = _mocked(**({_ops(state)[first]: program} if program else {}))
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt(point)), tenant, execution)
    calls_before, probes_before = len(mock.calls), len(mock.probes)
    step_id = _steps(db_schema, run, execution)[first]["step_id"]
    _time_passes(db_schema, run, execution)
    if program:
        mock.program(_ops(state)[first], "success")                  # the provider answers normally again
    (swept,) = _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    assert swept[:2] == (tenant, execution)
    assert _run_status(db_schema, run, execution) == "completed"
    for sid in _order(state):
        assert mock.side_effects(_key(state, sid)) == 1, sid                    # I4: never twice
    key = _key(state, first)
    first_calls = [m for m in mock.calls if m.idempotency_key == key]
    reservations = _reservations(db_schema, run, step_id)
    moves = _moves(db_schema, run, "step", step_id)
    episodes = _episodes(db_schema, run, step_id)
    new_probes = len(mock.probes) - probes_before
    if expected == "fresh":
        assert reservations == ["committed"] and episodes == [] and len(first_calls) == 1
    elif expected == "reuses_reservation":
        assert reservations == ["committed"] and episodes == []                 # the RESERVED one, reused (C35)
    elif expected == "not_executed_without_probe":
        assert new_probes == 0 and ("running", "pending_probe", "recovery") in moves
        assert ("pending_probe", "pending", "no_dispatch_marker") in moves
        assert [(e["kind"], e["outcome"]) for e in episodes] == [("EXECUTION", "NOT_EXECUTED")]
        assert reservations == ["released", "committed"]                         # a new one only after NOT_EXECUTED
    elif expected == "probe_then_retry":
        assert new_probes == 1 and [(e["kind"], e["outcome"]) for e in episodes] == [("EXECUTION", "NOT_EXECUTED")]
        assert [m.attempt_id for m in first_calls] == ["att-0-2"]                  # the next attempt, never attempt 1
        assert reservations == ["released", "committed"]
    elif expected == "crash_a":                                                    # suite 6 Crash A
        assert calls_before == 1 and new_probes == 1 and len(first_calls) == 1     # called once, never again
        assert [(e["kind"], e["outcome"]) for e in episodes] == [("EXECUTION", "EXECUTED_SUCCESS")]
        assert reservations == ["committed"] and moves[-1] == ("pending_probe", "completed", "probe_executed_success")
    elif expected == "crash_b":                                                    # suite 6 Crash B / C
        assert new_probes == 0 and len(first_calls) == 1
        assert [(e["kind"], e["status"]) for e in episodes] == [("VERIFICATION", "confirmed_success")]
        assert reservations == ["committed"] and moves[-1] == ("pending_probe", "completed", "verification_passed")
    elif expected == "crash_c_all_passed":                                         # suite 6 Crash C, all layers PASS
        assert new_probes == 0 and len(first_calls) == 1
        assert [(e["kind"], e["outcome"]) for e in episodes] == [("VERIFICATION", "LEDGER_HIT")]
        assert reservations == ["committed"] and moves[-1] == ("pending_probe", "completed", "ledger_hit_success")
    elif expected == "already_completed":
        assert episodes == [] and reservations == ["committed"] and len(first_calls) == 1
    elif expected == "probe_continued":
        assert [(e["kind"], e["outcome"]) for e in episodes] == [("EXECUTION", "EXECUTED_SUCCESS")]  # the same one
        (episode,) = episodes
        assert ("reconciling", "pending_probe", "inconclusive") in _moves(db_schema, run, "episode",
                                                                           episode["episode_id"])
        assert reservations == ["committed"] and len(first_calls) == 1
    run(assert_system_invariants(db_schema))


def test_recovery_expires_the_lapsed_lease_and_takes_over_with_a_larger_token(db_schema, run):
    state = _state("golden-rec-token", "rectoken")
    tenant, execution = _admit(db_schema, run, state)
    _crash(db_schema, run, _full(db_schema, _mocked(), faults=CrashAt("after_budget_lock")), tenant, execution)
    old = run(db_schema.fetch("SELECT lease_id, fence_token FROM worker_leases WHERE execution_id = $1", execution))[0]
    _time_passes(db_schema, run, execution)
    _sweep(db_schema, run, _full(db_schema, _mocked(), runtime=RECOVERING))
    assert _moves(db_schema, run, "lease", old["lease_id"])[-1] == ("active", "expired", "ttl_elapsed")
    tokens = [r["fence_token"] for r in run(db_schema.fetch(
        "SELECT fence_token FROM worker_leases WHERE execution_id = $1 AND lease_id <> $2", execution,
        old["lease_id"]))]
    assert tokens and min(tokens) > old["fence_token"]
    runtimes = {r["runtime_instance_id"] for r in run(db_schema.fetch(
        "SELECT runtime_instance_id FROM state_transitions WHERE execution_id = $1 AND entity_type = 'step'"
        " AND reason = 'recovery'", execution))}
    assert runtimes == {RECOVERING}
    run(assert_system_invariants(db_schema))


def test_a_takeover_on_another_worker_still_expires_the_crashed_lease(db_schema, run):
    """C26: the sweeper observes the lapsed lease first, even when recovery leases a different worker."""
    state = _state("golden-rec-otherworker", "recotherworker")
    tenant, execution = _admit(db_schema, run, state)
    _crash(db_schema, run, _full(db_schema, _mocked(), faults=CrashAt("after_budget_lock")), tenant, execution)
    old = run(db_schema.fetch("SELECT lease_id, worker_id FROM worker_leases WHERE execution_id = $1", execution))[0]
    run(db_schema.execute("INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile,"
                          " state, capacity) SELECT worker_id || '-spare', tenant_id, workspace_id, worker_class,"
                          " capability_profile, 'ACTIVE', capacity FROM workers WHERE worker_id = $1", old["worker_id"]))
    run(db_schema.execute("UPDATE workers SET state = 'DRAINING' WHERE worker_id = $1", old["worker_id"]))
    _time_passes(db_schema, run, execution)
    _sweep(db_schema, run, _full(db_schema, _mocked(), runtime=RECOVERING))
    assert _run_status(db_schema, run, execution) == "completed"
    assert _moves(db_schema, run, "lease", old["lease_id"])[-1] == ("active", "expired", "ttl_elapsed")
    assert run(db_schema.fetchval("SELECT current_load FROM workers WHERE worker_id = $1", old["worker_id"])) == 0
    used = {r["worker_id"] for r in run(db_schema.fetch("SELECT worker_id FROM worker_leases WHERE execution_id = $1"
                                                        " AND lease_id <> $2", execution, old["lease_id"]))}
    assert used == {f"{old['worker_id']}-spare"}
    run(assert_system_invariants(db_schema))


# --- the in-flight rule's other branches (§13 step 3, suite 6) -------------------------------------------------------

def test_a_cached_failure_at_recovery_fails_the_step_without_probe_or_call(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    from tests_golden.s12.M16_consolidation import _holder
    state = _state("golden-rec-cachedfail", "reccachedfail")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_dispatch_marker_before_call")), tenant,
           execution)
    run(PostgresIdempotencyLedger(db_schema.database()).store(          # the call's outcome, recorded elsewhere
        _holder(db_schema, run, tenant, execution), idempotency_key=_key(state, first),
        kernel_op_id=_ops(state)[first], result=AdapterResult("error", False, "client_error"), ttl_s=3600))
    _time_passes(db_schema, run, execution)
    _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    step = _steps(db_schema, run, execution)[first]
    assert (step["status"], step["budget"]) == ("failed", "released") and mock.calls == [] and mock.probes == []
    assert _moves(db_schema, run, "step", step["step_id"])[-1] == ("pending_probe", "failed", "ledger_hit_failure")
    assert [(e["kind"], e["outcome"]) for e in _episodes(db_schema, run, step["step_id"])] == [
        ("EXECUTION", "LEDGER_HIT")]
    run(assert_system_invariants(db_schema))


def test_an_expired_record_at_recovery_is_probed_never_blindly_called(db_schema, run):
    state = _state("golden-rec-expired", "recexpired")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_ledger_before_verification")), tenant,
           execution)
    run(db_schema.execute("UPDATE idempotency_ledger SET expires_at = now() - interval '1 second'"
                          " WHERE idempotency_key = $1", _key(state, first)))
    _time_passes(db_schema, run, execution)
    probes = len(mock.probes)
    _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    assert len(mock.probes) == probes + 1 and mock.side_effects(_key(state, first)) == 1
    assert len([m for m in mock.calls if m.idempotency_key == _key(state, first)]) == 1
    assert _run_status(db_schema, run, execution) == "completed"
    run(assert_system_invariants(db_schema))


def test_a_plan_that_changed_since_admission_is_dead_lettered_on_reload(db_schema, run):
    from tests_golden.s12.M12_loop import _force_plan_update, _retamper
    state = _state("golden-rec-tamper", "rectamper")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_commit_before_checkpoint")), tenant, execution)
    calls = len(mock.calls)
    original = run(db_schema.fetch("SELECT canonical_plan::text AS plan, plan_hash FROM execution_plans"
                                   " WHERE execution_id = $1", execution))[0]
    run(_retamper(db_schema, execution, "params_changed"))
    _time_passes(db_schema, run, execution)
    try:
        (swept,) = _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    finally:
        run(_force_plan_update(db_schema, execution, f"canonical_plan = $j${original['plan']}$j$::jsonb,"
                                                     f" plan_hash = '{original['plan_hash']}'"))
    assert swept[2].reason == "plan_integrity" and len(mock.calls) == calls              # no new step ran
    assert _run_status(db_schema, run, execution) == "dead_letter"
    first, *rest = _order(state)
    steps = _steps(db_schema, run, execution)
    assert steps[first]["status"] == "completed"
    assert all((steps[sid]["status"], steps[sid]["terminal_reason"]) == ("cancelled", "run_dead_lettered")
               for sid in rest)
    run(assert_system_invariants(db_schema))


def test_recovery_after_a_revocation_resolves_the_in_flight_step_then_cancels(db_schema, run):
    from contracts.step_execution import Revoked

    class KillSwitch:
        async def check(self, **kw):
            return Revoked("kill_switch_engaged")

    state = _state("golden-rec-revoked", "recrevoked")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_dispatch_marker_before_call")), tenant,
           execution)
    _time_passes(db_schema, run, execution)
    probes = len(mock.probes)
    _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING, live=KillSwitch()))
    assert len(mock.probes) == probes + 1 and mock.calls == []           # resolved by the probe, then no new call
    steps = _steps(db_schema, run, execution)
    assert (steps[first]["status"], steps[first]["terminal_reason"]) == ("cancelled", "kill_switch_engaged")
    assert all((steps[sid]["status"], steps[sid]["terminal_reason"]) == ("cancelled", "kill_switch_engaged")
               for sid in rest)
    assert _run_status(db_schema, run, execution) == "cancelled"
    run(assert_system_invariants(db_schema))


# --- what the sweeper takes (§13, CONF-033, CONF-042) ----------------------------------------------------------------

def test_the_sweeper_takes_only_orphaned_runs_of_other_runtimes(db_schema, run):
    from engine.stages.s12_execute.recovery import RecoverySweeper
    live = _state("golden-rec-alive", "recalive")
    tenant, execution = _admit(db_schema, run, live)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_budget_lock")), tenant, execution)
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=RECOVERING))
    assert (tenant, execution) not in run(sweeper.candidates())                 # its lease is still usable
    before = run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1", execution))
    _time_passes(db_schema, run, execution)
    own = RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=CRASHED))
    assert (tenant, execution) not in run(own.candidates())                     # CONF-033: never its own
    assert (tenant, execution) in run(sweeper.candidates())
    assert run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1",
                                  execution)) == before                         # discovery writes nothing
    finished = _state("golden-rec-finished", "recfinished")
    f_tenant, f_execution = _admit(db_schema, run, finished)
    from tests_golden.s12.M17_dead_letter import _dl_deps
    from engine.stages.s12_execute.loop import run_execution
    run(run_execution(_dl_deps(db_schema, _mocked()), f_tenant, f_execution))
    assert (f_tenant, f_execution) not in run(sweeper.candidates())             # terminal runs are never taken


def test_a_run_whose_owner_is_alive_is_not_recovered(db_schema, run):
    from engine.stages.s12_execute.loop import recover_execution
    state = _state("golden-rec-owned", "recowned")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_budget_lock")), tenant, execution)
    before = run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1", execution))
    result = run(recover_execution(_full(db_schema, mock, runtime=RECOVERING), tenant, execution))
    assert result.reason == "not_orphaned"
    assert run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE execution_id = $1",
                                  execution)) == before
    assert run(db_schema.fetchval("SELECT runtime_instance_id FROM execution_ownership WHERE execution_id = $1",
                                  execution)) == CRASHED


def test_every_move_on_these_paths_is_legal(db_schema, run):
    run(assert_system_invariants(db_schema))


# --- second review pass: recovery under repeated failure, the rarer states, and the sweeper itself -------------------

THIRD = "runtime-C"

DOUBLE_CRASHES = [
    # the first crash, a second crash inside recovery, what the third runtime finds for the first step
    ("after_dispatch_marker_before_call", "during_probe", [("EXECUTION", "NOT_EXECUTED")], ["att-0-2"]),
    ("after_budget_lock", "after_dispatch_marker_before_call",              # attempt 1 never left the process,
     [("EXECUTION", "NOT_EXECUTED"), ("EXECUTION", "NOT_EXECUTED")], ["att-0-2"]),   # so recovery re-used its number
    ("after_adapter_call_before_ledger", "during_probe", [("EXECUTION", "EXECUTED_SUCCESS")], ["att-0-1"]),
    ("after_ledger_before_verification", "during_verification", [("VERIFICATION", "VERIFIED_PASS")], ["att-0-1"]),
]


@pytest.mark.parametrize("first_point,second_point,expected_episodes,expected_attempts", DOUBLE_CRASHES,
                         ids=[f"{a}+{b}" for a, b, _, _ in DOUBLE_CRASHES])
def test_recovery_is_itself_recoverable(db_schema, run, first_point, second_point, expected_episodes,
                                        expected_attempts):
    """A crash inside recovery leaves a state the next recovery resolves by the same rule: an open episode is
    continued, never duplicated; a step is never executed twice; every takeover has a larger token."""
    from engine.stages.s12_execute.fault_injection import SimulatedCrash
    index = [c[0] for c in DOUBLE_CRASHES].index(first_point)
    state = _state(f"golden-rec-twice-{index}", f"rectwice{index}")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt(first_point)), tenant, execution)
    _time_passes(db_schema, run, execution)
    with pytest.raises(SimulatedCrash):
        _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING, faults=CrashAt(second_point)))
    _time_passes(db_schema, run, execution)
    (swept,) = _sweep(db_schema, run, _full(db_schema, mock, runtime=THIRD))
    assert swept[:2] == (tenant, execution)
    assert _run_status(db_schema, run, execution) == "completed"
    for sid in _order(state):
        assert mock.side_effects(_key(state, sid)) == 1, sid
    step_id = _steps(db_schema, run, execution)[first]["step_id"]
    assert [(e["kind"], e["outcome"]) for e in _episodes(db_schema, run, step_id)] == expected_episodes
    assert [m.attempt_id for m in mock.calls if m.idempotency_key == _key(state, first)] == expected_attempts
    tokens = [r["fence_token"] for r in run(db_schema.fetch(
        "SELECT fence_token FROM worker_leases WHERE execution_id = $1 ORDER BY acquired_at, fence_token", execution))]
    assert tokens == sorted(tokens) and len(set(tokens)) == len(tokens) >= 3
    assert run(db_schema.fetchval("SELECT runtime_instance_id FROM execution_ownership WHERE execution_id = $1",
                                  execution)) == THIRD
    run(assert_system_invariants(db_schema))


def test_an_unknown_step_is_in_flight_and_is_probed_never_called_blindly(db_schema, run):
    """§13 step 3 lists UNKNOWN with RUNNING, TIMEOUT and PENDING_PROBE. Nothing in this phase writes it (C24), but a
    row in that state (an older runtime, an operator) is in flight: probed, never re-executed without one."""
    state = _state("golden-rec-unknown", "recunknown")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_adapter_call_before_ledger")), tenant,
           execution)
    step_id = _steps(db_schema, run, execution)[first]["step_id"]
    run(db_schema.execute("UPDATE execution_steps SET status = 'unknown' WHERE step_id = $1", step_id))  # no edge leads
    probes = len(mock.probes)
    _time_passes(db_schema, run, execution)
    _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    assert len(mock.probes) == probes + 1 and mock.side_effects(_key(state, first)) == 1
    assert len([m for m in mock.calls if m.idempotency_key == _key(state, first)]) == 1
    assert ("unknown", "pending_probe", "recovery") in _moves(db_schema, run, "step", step_id)
    assert _run_status(db_schema, run, execution) == "completed"
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("call,last_outcome", [
    ("timeout_executed", ("completed", None)),
    ("timeout_not_executed", ("cancelled", "not_executed_no_retry")),     # RECONCILING never goes back to RUNNING
])
def test_a_reconciling_run_is_resolved_and_consolidated(db_schema, run, call, last_outcome):
    """C13: a run is RECONCILING only when every other step is terminal and one awaits its probe. Recovery resolves
    that step and consolidates the run (RECONCILING → terminal); it never leaves it for the next sweep. A step the
    probe finds not executed cannot be retried there (RECONCILING → RUNNING is illegal): cancelled, never called."""
    from adapters.postgres.execution import PostgresExecutionStore
    from engine.stages.s12_execute.recovery import RecoverySweeper
    from tests_golden.s12.M12_loop import CHAIN3
    from tests_golden.s12.M16_consolidation import _holder
    state = _state(f"golden-rec-reconciling-{call}", f"recreconciling{call.replace('_', '')}",
                   chain=CHAIN3[:2])                                         # its last step writes (probed)
    tenant, execution = _admit(db_schema, run, state)
    *head, last = _order(state)
    mock = _mocked(**{_ops(state)[last]: {"call": call}})
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("during_probe")), tenant, execution)
    steps = _steps(db_schema, run, execution)
    assert [steps[sid]["status"] for sid in head] == ["completed"] * len(head)
    assert steps[last]["status"] == "pending_probe"
    run(PostgresExecutionStore(db_schema.database()).transition_run(
        _holder(db_schema, run, tenant, execution), "reconciling", reason="awaiting_resolution"))
    _time_passes(db_schema, run, execution)
    calls = len(mock.calls)
    (swept,) = _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    assert swept[:2] == (tenant, execution) and len(mock.calls) == calls           # resolved by the probe only
    steps = _steps(db_schema, run, execution)
    assert (steps[last]["status"], steps[last]["terminal_reason"]) == last_outcome
    status = _run_status(db_schema, run, execution)
    assert status not in ("running", "reconciling")
    assert _moves(db_schema, run, "run", execution)[-1] == ("reconciling", status, "consolidated")
    assert mock.side_effects(_key(state, last)) == (1 if last_outcome[0] == "completed" else 0)
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=THIRD))
    assert (tenant, execution) not in run(sweeper.candidates())
    run(assert_system_invariants(db_schema))


def test_the_in_flight_step_of_a_tampered_plan_is_dead_lettered_never_probed(db_schema, run):
    """CONF-043: the call cannot be rebuilt from an untrusted plan, so the in-flight step is neither probed nor re-run:
    DEAD_LETTER, its budget LOCKED (D4), a PROBE dead letter for an operator; the rest is cancelled."""
    from tests_golden.s12.M12_loop import _force_plan_update, _retamper
    state = _state("golden-rec-tamperflight", "rectamperflight")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_dispatch_marker_before_call")), tenant,
           execution)
    original = run(db_schema.fetch("SELECT canonical_plan::text AS plan, plan_hash FROM execution_plans"
                                   " WHERE execution_id = $1", execution))[0]
    run(_retamper(db_schema, execution, "params_changed"))
    _time_passes(db_schema, run, execution)
    probes = len(mock.probes)
    try:
        (swept,) = _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    finally:
        run(_force_plan_update(db_schema, execution, f"canonical_plan = $j${original['plan']}$j$::jsonb,"
                                                     f" plan_hash = '{original['plan_hash']}'"))
    assert swept[2].reason == "plan_integrity"
    assert len(mock.probes) == probes and mock.calls == []
    steps = _steps(db_schema, run, execution)
    assert (steps[first]["status"], steps[first]["budget"]) == ("dead_letter", "locked")
    assert all((steps[sid]["status"], steps[sid]["terminal_reason"]) == ("cancelled", "run_dead_lettered")
               for sid in rest)
    (letter,) = run(db_schema.fetch("SELECT error_type, retry_mode, status FROM dead_letters WHERE step_id = $1",
                                    steps[first]["step_id"]))
    assert (letter["error_type"], letter["retry_mode"], letter["status"]) == ("unknown_unresolved", "PROBE",
                                                                              "pending")
    assert _run_status(db_schema, run, execution) == "dead_letter"
    run(assert_system_invariants(db_schema))


REVOKED_IN_RECOVERY = [
    # the crash point, the revocation, the first step's outcome
    ("after_budget_lock", "credential_invalid", ("cancelled", "credential_invalid")),
    ("after_adapter_call_before_ledger", "authorization_revoked", ("completed", None)),
    ("after_commit_before_checkpoint", "binding_invalid", ("completed", None)),
]


@pytest.mark.parametrize("point,reason,first_outcome", REVOKED_IN_RECOVERY, ids=[c[1] for c in REVOKED_IN_RECOVERY])
def test_every_revocation_found_in_recovery_resolves_then_cancels(db_schema, run, point, reason, first_outcome):
    """§13 1a for each kind of revocation: an in-flight step is resolved first (an executed one completes, a
    provably unexecuted one is cancelled, never retried), then the rest is cancelled with the reason."""
    from contracts.step_execution import Revoked

    class Revoking:
        async def check(self, **kw):
            return Revoked(reason)

    index = [c[0] for c in REVOKED_IN_RECOVERY].index(point)
    state = _state(f"golden-rec-revoke-{index}", f"recrevoke{index}")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt(point)), tenant, execution)
    calls = len(mock.calls)
    _time_passes(db_schema, run, execution)
    (swept,) = _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING, live=Revoking()))
    assert (swept[2].run_status, swept[2].reason) == ("cancelled", reason)
    assert len(mock.calls) == calls                                            # nothing new is dispatched
    steps = _steps(db_schema, run, execution)
    assert (steps[first]["status"], steps[first]["terminal_reason"]) == first_outcome
    assert all((steps[sid]["status"], steps[sid]["terminal_reason"]) == ("cancelled", reason) for sid in rest)
    assert _reservations(db_schema, run, steps[first]["step_id"])[-1] in ("committed", "released")
    assert _run_status(db_schema, run, execution) == "cancelled"
    run(assert_system_invariants(db_schema))


def test_a_cancellation_requested_while_crashed_is_honoured_by_recovery(db_schema, run):
    """C16 across a crash: the flag is read from the database, so the in-flight step is resolved and nothing after it
    runs."""
    from adapters.postgres.cancellation import PostgresCancellation
    state = _state("golden-rec-usercancel", "recusercancel")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_adapter_call_before_ledger")), tenant,
           execution)
    assert run(PostgresCancellation(db_schema.database()).request(tenant, execution,
                                                                  state.execution_context.user_id)) is True
    _time_passes(db_schema, run, execution)
    _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    steps = _steps(db_schema, run, execution)
    assert steps[first]["status"] == "completed" and mock.side_effects(_key(state, first)) == 1
    assert all((steps[sid]["status"], steps[sid]["terminal_reason"]) == ("cancelled", "user_cancelled")
               for sid in rest)
    assert [m for m in mock.calls if m.idempotency_key != _key(state, first)] == []
    assert _run_status(db_schema, run, execution) == "cancelled"
    run(assert_system_invariants(db_schema))


def test_one_run_that_cannot_be_recovered_does_not_stop_the_sweep(db_schema, run, caplog):
    """A failure recovering one run (here an idempotency conflict: the ledger names another operation for the key) is
    logged at ERROR with the run and the sweep goes on to the others; that run is left as it is, never forced
    terminal, never re-executed. A SimulatedCrash is never caught (it is the process dying)."""
    import logging
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    from tests_golden.s12.M16_consolidation import _holder
    bad, good = _state("golden-rec-poison", "recpoison"), _state("golden-rec-healthy", "rechealthy")
    b_tenant, b_execution = _admit(db_schema, run, bad)
    g_tenant, g_execution = _admit(db_schema, run, good)
    mock = _mocked()
    for tenant, execution in ((b_tenant, b_execution), (g_tenant, g_execution)):
        _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_dispatch_marker_before_call")), tenant,
               execution)
    run(PostgresIdempotencyLedger(db_schema.database()).store(
        _holder(db_schema, run, b_tenant, b_execution), idempotency_key=_key(bad, _order(bad)[0]),
        kernel_op_id="some.other_operation", result=AdapterResult("ok", data={"id": "x"}), ttl_s=3600))
    for execution in (b_execution, g_execution):
        _time_passes(db_schema, run, execution)
    with caplog.at_level(logging.ERROR):
        swept = _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING))
    assert [(t, e) for t, e, _ in swept] == [(g_tenant, g_execution)]
    assert _run_status(db_schema, run, g_execution) == "completed"
    assert _run_status(db_schema, run, b_execution) == "running"
    assert [m for m in mock.calls if m.idempotency_key == _key(bad, _order(bad)[0])] == []
    assert [r for r in caplog.records if r.levelno >= logging.ERROR and b_execution in r.getMessage()
            + str(getattr(r, "execution_id", ""))]
    run(assert_system_invariants(db_schema))


def test_a_sweep_takes_at_most_its_batch_and_a_later_sweep_the_rest(db_schema, run):
    from engine.stages.s12_execute.recovery import RecoverySweeper
    with pytest.raises(ValueError):
        RecoverySweeper(db_schema.database(), _full(db_schema, _mocked()), batch=0)
    states = [_state(f"golden-rec-batch-{i}", f"recbatch{i}") for i in range(3)]
    mock = _mocked()
    admitted = [_admit(db_schema, run, s) for s in states]
    for tenant, execution in admitted:
        _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_budget_lock")), tenant, execution)
        _time_passes(db_schema, run, execution)
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=RECOVERING), batch=2)
    first, second, third = run(sweeper.sweep()), run(sweeper.sweep()), run(sweeper.sweep())
    assert (len(first), len(second), third) == (2, 1, [])
    assert sorted(e for _, e, _ in first + second) == sorted(e for _, e in admitted)
    assert all(_run_status(db_schema, run, e) == "completed" for _, e in admitted)
    run(assert_system_invariants(db_schema))


def test_a_run_never_leased_is_orphaned_only_after_a_lease_ttl(db_schema, run):
    """CONF-046: an admitted run whose runtime has not leased it yet is not taken at once (its admitting runtime is
    about to): with no lease at all, the run is a candidate once its ownership is older than one lease TTL."""
    from engine.stages.s12_execute.recovery import RecoverySweeper
    state = _state("golden-rec-neverleased", "recneverleased")
    tenant, execution = _admit(db_schema, run, state)
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, _mocked(), runtime=RECOVERING))
    assert (tenant, execution) not in run(sweeper.candidates())
    run(db_schema.execute("UPDATE execution_ownership SET updated_at = now() - interval '31 seconds'"
                          " WHERE execution_id = $1", execution))                 # _dl_deps: lease_ttl_s = 30
    assert (tenant, execution) in run(sweeper.candidates())
    run(sweeper.sweep())
    assert _run_status(db_schema, run, execution) == "completed"
    run(assert_system_invariants(db_schema))


def test_a_live_run_between_steps_is_not_taken_and_a_silent_one_is(db_schema, run):
    """CONF-046: a live loop releases its lease when a step commits and leases the next step at once; in that gap the
    run has no usable lease but is not orphaned. It is judged by its latest lease: released → orphaned only one lease
    TTL after the release; active but lapsed, or expired → at once."""
    from adapters.postgres.leases import Lease, PostgresLeaseManager
    from engine.stages.s12_execute.recovery import RecoverySweeper
    state = _state("golden-rec-betweensteps", "recbetweensteps")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_commit_before_checkpoint")), tenant, execution)
    leases = PostgresLeaseManager(db_schema.database())
    row = run(db_schema.fetch("SELECT * FROM worker_leases WHERE execution_id = $1 AND status = 'active'",
                              execution))[0]
    lease = Lease(lease_id=row["lease_id"], tenant_id=tenant, worker_id=row["worker_id"], execution_id=execution,
                  fence_token=row["fence_token"])
    assert run(leases.release(lease, reason="work_complete")) is True          # as the live loop does after a commit
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=RECOVERING))
    assert (tenant, execution) not in run(sweeper.candidates())                 # between steps: not orphaned
    run(db_schema.execute("UPDATE worker_leases SET released_at = now() - interval '31 seconds'"
                          " WHERE lease_id = $1", row["lease_id"]))              # _dl_deps: lease_ttl_s = 30
    assert (tenant, execution) in run(sweeper.candidates())                     # silent for a TTL: orphaned
    run(sweeper.sweep())
    assert _run_status(db_schema, run, execution) == "completed"
    for sid in _order(state):
        assert mock.side_effects(_key(state, sid)) == 1, sid
    run(assert_system_invariants(db_schema))


def test_a_run_is_judged_by_its_latest_lease_only(db_schema, run):
    """CONF-046: a lease the sweeper expired (it then died before its takeover) leaves the run orphaned at once; an old
    expired lease under a newer live one does not (the new owner is alive)."""
    from engine.stages.s12_execute.fault_injection import SimulatedCrash
    from engine.stages.s12_execute.recovery import RecoverySweeper
    from tests_golden.s12.M12_loop import _mock as plain_mock
    state = _state("golden-rec-latestlease", "reclatestlease")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    _crash(db_schema, run, _full(db_schema, mock, faults=CrashAt("after_budget_lock")), tenant, execution)
    _time_passes(db_schema, run, execution)
    deps = _full(db_schema, mock, runtime=RECOVERING)
    run(deps.leases.expire_lapsed(tenant, execution))                    # a sweeper expired it, then died
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, plain_mock(), runtime=THIRD))
    assert (tenant, execution) in run(sweeper.candidates())
    with pytest.raises(SimulatedCrash):                                   # a takeover that dies holding a new lease
        _sweep(db_schema, run, _full(db_schema, mock, runtime=RECOVERING,
                                     faults=CrashAt("after_dispatch_marker_before_call")))
    statuses = [r["status"] for r in run(db_schema.fetch(
        "SELECT status FROM worker_leases WHERE execution_id = $1 ORDER BY fence_token", execution))]
    assert statuses[0] == "expired" and statuses[-1] == "active"
    assert (tenant, execution) not in run(sweeper.candidates())          # its latest lease is still usable
    _time_passes(db_schema, run, execution)
    assert (tenant, execution) in run(sweeper.candidates())
    run(RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=THIRD)).sweep())
    assert _run_status(db_schema, run, execution) == "completed"
    run(assert_system_invariants(db_schema))


def test_the_discovery_function_is_hardened(db_schema, run):
    """CONF-042: a SECURITY DEFINER function runs with its owner's rights, so it pins its search_path with pg_temp
    last (a temporary table cannot stand in for a real one), returns ids only, and writes nothing (STABLE)."""
    state = _state("golden-rec-hardened", "rechardened")
    tenant, execution = _admit(db_schema, run, state)
    row = run(db_schema.fetch(
        "SELECT p.prosecdef, p.provolatile::text AS volatility, p.proconfig, pg_get_function_result(p.oid) AS result FROM pg_proc p"
        " WHERE p.proname = 's12_recovery_candidates' AND p.pronamespace = $1::regnamespace", db_schema.name))[0]
    assert row["prosecdef"] is True and row["volatility"] == "s"
    assert row["result"] == "TABLE(tenant_id text, execution_id text)"
    (path,) = [c.split("=", 1)[1] for c in row["proconfig"] or [] if c.startswith("search_path=")]
    assert [p.strip().strip('"') for p in path.split(",")][-1] == "pg_temp"

    async def shadowed():
        async with db_schema.database().tenant_transaction(tenant) as c:
            await c.execute("CREATE TEMP TABLE execution_runs (tenant_id TEXT, execution_id TEXT, status TEXT)"
                            " ON COMMIT DROP")
            await c.execute("INSERT INTO pg_temp.execution_runs VALUES ('forged', 'forged', 'running')")
            return [tuple(r) for r in await c.fetch("SELECT * FROM s12_recovery_candidates('runtime-X', 100, 0)")]
    assert ("forged", "forged") not in run(shadowed())
    definers = [r["proname"] for r in run(db_schema.fetch(
        "SELECT proname FROM pg_proc WHERE prosecdef AND pronamespace = $1::regnamespace", db_schema.name))]
    assert definers == ["s12_recovery_candidates"]                  # the one reviewed exception to RLS (CONF-042)


def test_the_sweeper_runs_with_the_runtime_until_stopped_at_an_interval_under_30_seconds(db_schema, run, caplog):
    """§13: the sweeper starts with the Worker Runtime and runs at an interval under 30 seconds; a sweep that fails
    (the database briefly unreachable) is logged at ERROR and the next sweep runs."""
    import asyncio
    import logging
    from engine.stages.s12_execute.recovery import RecoverySweeper
    state = _state("golden-rec-sweeploop", "recsweeploop")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    sweeper = RecoverySweeper(db_schema.database(), _full(db_schema, mock, runtime=RECOVERING))
    for bad in (0, -1, 30, 45):
        with pytest.raises(ValueError):
            run(sweeper.run(asyncio.Event(), interval_s=bad))
    real, outages = sweeper.candidates, []

    async def flaky():
        if not outages:
            outages.append(1)
            raise ConnectionError("database unreachable")
        return await real()
    sweeper.candidates = flaky

    async def runtime():
        stop = asyncio.Event()
        task = asyncio.ensure_future(sweeper.run(stop, interval_s=0.05))
        await asyncio.sleep(0.2)                                       # idle sweeps: nothing is orphaned yet
        await _crash_async(db_schema, _full(db_schema, mock, faults=CrashAt("after_budget_lock")), tenant, execution)
        await db_schema.execute("UPDATE worker_leases SET expires_at = now() - interval '1 second'"
                                " WHERE execution_id = $1 AND status = 'active'", execution)
        for _ in range(100):
            if await db_schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1",
                                        execution) == "completed":
                break
            await asyncio.sleep(0.05)
        stop.set()
        return await asyncio.wait_for(task, 5)
    with caplog.at_level(logging.ERROR):
        sweeps = run(runtime())
    assert sweeps >= 3 and _run_status(db_schema, run, execution) == "completed"
    assert outages == [1] and [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "database unreachable" not in caplog.text                   # the error's type is logged, never its text
    run(assert_system_invariants(db_schema))


async def _crash_async(schema, deps, tenant, execution):
    from engine.stages.s12_execute.fault_injection import SimulatedCrash
    from engine.stages.s12_execute.loop import run_execution
    with pytest.raises(SimulatedCrash):
        await run_execution(deps, tenant, execution)
