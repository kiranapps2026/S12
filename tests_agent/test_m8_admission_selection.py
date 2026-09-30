"""Agent tests for M8 (never count for certification): the edges of per-step admission and worker selection that the
pinned golden M08 does not fix, and selection driving the real lease manager (M7)."""
import asyncio

import pytest
from tests_golden.fixtures.db import GoldenSchema, golden_database_url, new_schema_name
from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M07_leases import _acquire, _seed

from contracts.step_admission import AdmissionDecision
from engine.stages.s12_execute.admission_control import (
    AdmissionSnapshot,
    admit_step,
    evaluate,
    reject_outcome,
)
from engine.stages.s12_execute.eligibility import WorkerCandidate
from engine.stages.s12_execute.selection import lease_for_step, select_worker

PASSING = dict(kill_switch_engaged=False, tenant_quota_exceeded=False, tenant_active=True, workspace_active=True,
               mode_allowed=True, provider_allowed=True, worker_capacity_available=True, circuit_open=False,
               db_pool_pressure=False, budget_available=True, system_overloaded=False)


def _snap(**changes):
    return AdmissionSnapshot(**{**PASSING, **changes})


def _candidate(worker_id, *, capacity=2, load=0):
    return WorkerCandidate(worker_id=worker_id, workspace_id="ws", capacity=capacity, current_load=load,
                           paused_until=None, scheduled_activation_at=None, assigned_user_id=None,
                           capability_profile=frozenset({"cap"}), settings={}, runtime_type="llm")


class Ledger:
    def __init__(self):
        self.events = []

    async def record(self, kind, payload):
        self.events.append((kind, dict(payload)))


def _admit(snapshots, *, max_attempts):
    it, slept, ledger = iter(snapshots), [], Ledger()

    async def source():
        return next(it)

    async def sleep(seconds):
        slept.append(seconds)

    decision = asyncio.run(admit_step(source, ledger=ledger, max_attempts=max_attempts, sleep=sleep))
    return decision, slept, ledger.events


# --- admission -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field", sorted(PASSING))
def test_an_unreadable_snapshot_value_is_refused_not_passed(field):
    with pytest.raises(TypeError):
        _snap(**{field: None})


def test_accept_carries_nothing_and_degrade_names_its_features():
    assert evaluate(_snap()) == AdmissionDecision("ACCEPT")
    degraded = evaluate(_snap(degrade=True))
    assert degraded.degraded_features and degraded.retry_after_ms is None and degraded.gate_failed is None


def test_a_reject_is_final_at_once_no_wait_one_event():
    decision, slept, events = _admit([_snap(provider_allowed=False)], max_attempts=5)
    assert (decision.status, decision.gate_failed) == ("REJECT", "6") and slept == [] and len(events) == 1


def test_each_retry_reads_live_state_again_so_a_later_reject_decides():
    decision, slept, events = _admit([_snap(worker_capacity_available=False), _snap(kill_switch_engaged=True)],
                                     max_attempts=5)
    assert (decision.status, decision.gate_failed) == ("REJECT", "1") and len(slept) == 1
    assert reject_outcome(decision) == ("kill_switch_engaged", "revocation")


def test_no_wait_after_the_last_attempt_and_the_exhaustion_names_the_last_gate():
    decision, slept, events = _admit([_snap(db_pool_pressure=True)] * 3, max_attempts=3)
    assert (decision.status, decision.reason, decision.gate_failed) == ("REJECT", "admission_exhausted", None)
    assert len(slept) == 2 and "gate 9" in decision.detail
    assert [p["status"] for _, p in events] == ["DELAY", "DELAY", "DELAY", "REJECT"]


def test_a_single_attempt_never_waits():
    decision, slept, _ = _admit([_snap(worker_capacity_available=False)], max_attempts=1)
    assert decision.reason == "admission_exhausted" and slept == []


@pytest.mark.parametrize("attempts", [0, -1])
def test_attempts_must_be_positive(attempts):
    with pytest.raises(ValueError):
        _admit([], max_attempts=attempts)


def test_ledger_payload_has_exactly_the_c30_fields():
    _, _, events = _admit([_snap(budget_available=False)], max_attempts=1)
    assert events == [("admission_decision", {"status": "REJECT", "gate_failed": "10", "reason": "budget_exhausted"})]


# --- selection -------------------------------------------------------------------------------------------------------

def test_every_full_candidate_means_no_selection():
    assert select_worker([_candidate("w-1", capacity=1, load=1), _candidate("w-2", capacity=3, load=3)],
                         current_owner=None) is None


def test_equal_free_fractions_tie_to_the_smallest_id():
    assert select_worker([_candidate("w-b", capacity=4, load=2), _candidate("w-a", capacity=2, load=1)],
                         current_owner=None) == "w-a"


def _rounds(pools, results):
    reads, tried = iter(pools), []
    outcomes = iter(results)

    async def candidates():
        return next(reads)

    async def acquire(worker_id):
        tried.append(worker_id)
        return next(outcomes)

    return candidates, acquire, tried


def test_full_candidates_use_up_attempts_without_acquiring_then_lease_unavailable():
    candidates, acquire, tried = _rounds([[_candidate("w-1", capacity=1, load=1)]] * 3, [])
    result = asyncio.run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=3))
    assert result == "lease_unavailable" and tried == []


def test_candidates_gone_after_a_failed_acquisition_is_no_worker():
    candidates, acquire, tried = _rounds([[_candidate("w-1")], []], [None])
    result = asyncio.run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=3))
    assert result == "no_worker" and tried == ["w-1"]


def test_reselection_follows_the_fresh_read():
    lease = object()
    candidates, acquire, tried = _rounds([[_candidate("w-1"), _candidate("w-2", load=1)],
                                          [_candidate("w-1", load=2), _candidate("w-2", load=1)]], [None, lease])
    result = asyncio.run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=3))
    assert result is lease and tried == ["w-1", "w-2"]


def test_an_acquisition_error_is_not_swallowed():
    async def candidates():
        return [_candidate("w-1")]

    async def acquire(worker_id):
        raise LookupError("no ownership record")

    with pytest.raises(LookupError):
        asyncio.run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=3))


# --- selection over the real lease manager ---------------------------------------------------------------------------

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


def _live(schema, workers, execution, runtime):
    async def candidates():
        rows = await schema.fetch("SELECT worker_id, capacity, current_load FROM workers WHERE worker_id = ANY($1)"
                                  " ORDER BY worker_id", list(workers))
        return [_candidate(r["worker_id"], capacity=r["capacity"], load=r["current_load"]) for r in rows]

    async def acquire(worker_id):
        return await _acquire(schema, worker_id, execution, runtime=runtime)

    return candidates, acquire


def test_a_live_owner_elsewhere_ends_as_lease_unavailable_and_ownership_is_kept(db_schema, run):
    run(_seed(db_schema, workers={"w-sel-a": 1, "w-sel-b": 2}, executions=["e-sel"]))
    held = run(_acquire(db_schema, "w-sel-a", "e-sel", runtime="runtime-a"))
    candidates, acquire = _live(db_schema, ["w-sel-b"], "e-sel", "runtime-b")
    result = run(lease_for_step(candidates=candidates, acquire=acquire, current_owner="w-sel-a", max_attempts=3))
    assert result == "lease_unavailable"
    owner = run(db_schema.fetchval("SELECT fencing_token FROM execution_ownership WHERE execution_id = 'e-sel'"))
    assert owner == held.fence_token
    run(assert_system_invariants(db_schema))


def test_two_steps_racing_for_one_slot_lease_it_once(db_schema, run):
    run(_seed(db_schema, workers={"w-slot": 1}, executions=["e-slot-1", "e-slot-2"]))

    async def race():
        attempts = []
        for execution in ("e-slot-1", "e-slot-2"):
            candidates, acquire = _live(db_schema, ["w-slot"], execution, f"rt-{execution}")
            attempts.append(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None,
                                           max_attempts=2))
        return await asyncio.gather(*attempts)

    results = run(race())
    assert sorted(type(r).__name__ for r in results) == ["Lease", "StepTerminalReason"]
    assert "lease_unavailable" in results
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE worker_id = 'w-slot'")) == 1
    run(assert_system_invariants(db_schema))
