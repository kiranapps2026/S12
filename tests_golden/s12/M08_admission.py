"""M8 golden — per-step admission controller and worker selection (gate commit E part 2). Owner-pinned.

Gate v10: §8 steps 1–3, C5 (a worker at capacity is not selectable), C30 (REJECT mapped by gate_failed; gate 7 is a
QUEUE, never a REJECT; every decision is a ledger event), WORKER_LIFECYCLE §10 (gates 1–11 in order, first reject
wins, admission is stateless), §11 (AdmissionDecision), §13 (locality scoring is deterministic and advisory);
rulings CONF-015 (the §11 contract, not the frozen contracts/worker.py one) and CONF-017 (gates 9 and 11 are DELAY).

Interface this file fixes:
  * ``contracts.step_admission.AdmissionDecision(status, reason=None, detail=None, retry_after_ms=None,
    degraded_features=None, gate_failed=None)``; status is one of ACCEPT, QUEUE, DELAY, REJECT, DEGRADE; ``gate_failed``
    is the gate number as a string ("1".."11").
  * ``engine.stages.s12_execute.admission_control``:
      ``AdmissionSnapshot`` (frozen) with booleans ``kill_switch_engaged``, ``tenant_quota_exceeded``, ``tenant_active``,
      ``workspace_active``, ``mode_allowed``, ``provider_allowed``, ``worker_capacity_available``, ``circuit_open``,
      ``db_pool_pressure``, ``budget_available``, ``system_overloaded``, ``degrade`` (default False);
      ``evaluate(snapshot) -> AdmissionDecision`` — pure; first failing gate decides; gate 7 → QUEUE with reason
      ``worker_at_capacity`` and a ``retry_after_ms``; gates 9 (``db_pool_pressure``) and 11 (``system_overloaded``) →
      DELAY with that reason and a ``retry_after_ms`` (backpressure, §11; ruling CONF-017); any other failing gate → REJECT
      with the §10 reason; all passing → ACCEPT, or DEGRADE when ``degrade``;
      ``async admit_step(snapshot_source, *, ledger, max_attempts, sleep) -> AdmissionDecision`` — calls
      ``await snapshot_source()`` then ``evaluate``; QUEUE/DELAY → ``await sleep(retry_after_ms / 1000)`` and again, at
      most ``max_attempts`` evaluations, then REJECT with reason ``admission_exhausted``; every decision is recorded with
      ``await ledger.record("admission_decision", {"status", "gate_failed", "reason"})``;
      ``reject_outcome(decision) -> (terminal_reason, path)``: gate "1" → ("kill_switch_engaged", "revocation"),
      gate "3" → ("authorization_revoked", "revocation"), gate "10" → ("budget_exhausted", "budget"), reason
      ``admission_exhausted`` → ("admission_exhausted", "consolidate") (§8 step 1, C22; DEF-005), anything else →
      ("admission_rejected", "consolidate"); a non-REJECT decision raises ValueError.
  * ``engine.stages.s12_execute.selection``:
      ``select_worker(candidates, *, current_owner) -> worker_id | None`` — candidates are
      ``engine.stages.s12_execute.eligibility.WorkerCandidate``; a worker with ``current_load >= capacity`` is never
      chosen; score = 0.30 × locality (1.0 for ``current_owner``, else 0.0) + 0.20 × (1 − current_load / capacity);
      the highest score wins, ties go to the smallest ``worker_id`` (deterministic);
      ``async lease_for_step(*, candidates, acquire, current_owner, max_attempts) -> Lease | str`` — select, then
      ``await acquire(worker_id)``; ``None`` from acquire re-reads ``await candidates()`` and selects again, at most
      ``max_attempts`` acquisitions, then ``"lease_unavailable"``; no candidate at all → ``"no_worker"``.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

GATES = [  # (gate, snapshot field that fails it, value that fails, §10 reason)
    ("1", "kill_switch_engaged", True, "system_halted"),
    ("2", "tenant_quota_exceeded", True, "tenant_quota_exceeded"),
    ("3", "tenant_active", False, "tenant_inactive"),
    ("4", "workspace_active", False, "workspace_inactive"),
    ("5", "mode_allowed", False, "mode_not_allowed"),
    ("6", "provider_allowed", False, "provider_blocked"),
    ("7", "worker_capacity_available", False, "worker_at_capacity"),
    ("8", "circuit_open", True, "provider_circuit_open"),
    ("9", "db_pool_pressure", True, "db_pool_pressure"),
    ("10", "budget_available", False, "budget_exhausted"),
    ("11", "system_overloaded", True, "system_overloaded"),
]


def _ok(**changes):
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    base = dict(kill_switch_engaged=False, tenant_quota_exceeded=False, tenant_active=True, workspace_active=True,
                mode_allowed=True, provider_allowed=True, worker_capacity_available=True, circuit_open=False,
                db_pool_pressure=False, budget_available=True, system_overloaded=False)
    return AdmissionSnapshot(**{**base, **changes})


class Ledger:
    def __init__(self):
        self.events = []

    async def record(self, kind, payload):
        self.events.append((kind, dict(payload)))


def _candidate(worker_id, *, capacity=1, load=0):
    from engine.stages.s12_execute.eligibility import WorkerCandidate
    return WorkerCandidate(worker_id=worker_id, workspace_id="ws", capacity=capacity, current_load=load,
                           paused_until=None, scheduled_activation_at=None, assigned_user_id=None,
                           capability_profile=frozenset({"cap"}), settings={}, runtime_type="llm")


# --- gates ---------------------------------------------------------------------------------------------------------

def test_all_gates_pass_is_accept():
    from engine.stages.s12_execute.admission_control import evaluate
    decision = evaluate(_ok())
    assert (decision.status, decision.gate_failed, decision.reason) == ("ACCEPT", None, None)


def test_degrade_when_all_pass_and_degraded():
    from engine.stages.s12_execute.admission_control import evaluate
    assert evaluate(_ok(degrade=True)).status == "DEGRADE"


@pytest.mark.parametrize("gate,field,value,reason", GATES)
def test_each_gate_rejects_with_its_reason(gate, field, value, reason):
    from engine.stages.s12_execute.admission_control import evaluate
    decision = evaluate(_ok(**{field: value}))
    expected_status = {"7": "QUEUE", "9": "DELAY", "11": "DELAY"}.get(gate, "REJECT")
    assert (decision.status, decision.gate_failed, decision.reason) == (expected_status, gate, reason)


@pytest.mark.parametrize("field", ["db_pool_pressure", "system_overloaded"])
def test_backpressure_is_a_delay_with_retry_after_never_a_reject(field):
    from engine.stages.s12_execute.admission_control import evaluate
    decision = evaluate(_ok(**{field: True}))
    assert decision.status == "DELAY" and decision.retry_after_ms and decision.retry_after_ms > 0


def test_capacity_is_a_queue_with_retry_after_never_a_reject():
    from engine.stages.s12_execute.admission_control import evaluate
    decision = evaluate(_ok(worker_capacity_available=False))
    assert decision.status == "QUEUE" and decision.retry_after_ms and decision.retry_after_ms > 0


@pytest.mark.parametrize("first,second", [(0, 1), (2, 9), (6, 9), (4, 10)])
def test_first_failing_gate_decides(first, second):
    from engine.stages.s12_execute.admission_control import evaluate
    g1, g2 = GATES[first], GATES[second]
    decision = evaluate(_ok(**{g1[1]: g1[2], g2[1]: g2[2]}))
    assert decision.gate_failed == g1[0]


def test_evaluation_is_stateless():
    from engine.stages.s12_execute.admission_control import evaluate
    snapshot = _ok(budget_available=False)
    assert evaluate(snapshot) == evaluate(snapshot) == evaluate(dataclasses.replace(snapshot))


# --- bounded QUEUE / DELAY, ledger, REJECT mapping -----------------------------------------------------------------

def test_queue_is_retried_then_accepted_and_every_decision_is_a_ledger_event():
    from engine.stages.s12_execute.admission_control import admit_step
    snapshots = iter([_ok(worker_capacity_available=False), _ok(worker_capacity_available=False), _ok()])
    slept, ledger = [], Ledger()

    async def source():
        return next(snapshots)

    async def sleep(seconds):
        slept.append(seconds)

    decision = asyncio.run(admit_step(source, ledger=ledger, max_attempts=5, sleep=sleep))
    assert decision.status == "ACCEPT" and len(slept) == 2 and all(s > 0 for s in slept)
    assert [(k, p["status"], p["gate_failed"]) for k, p in ledger.events] == [
        ("admission_decision", "QUEUE", "7"), ("admission_decision", "QUEUE", "7"), ("admission_decision", "ACCEPT", None)]


def test_queue_is_bounded_then_admission_exhausted():
    from engine.stages.s12_execute.admission_control import admit_step
    evaluations, ledger = [], Ledger()

    async def source():
        evaluations.append(1)
        return _ok(worker_capacity_available=False)

    async def sleep(seconds):
        pass

    decision = asyncio.run(admit_step(source, ledger=ledger, max_attempts=3, sleep=sleep))
    assert (decision.status, decision.reason) == ("REJECT", "admission_exhausted") and len(evaluations) == 3
    assert ledger.events[-1][1]["reason"] == "admission_exhausted" and len(ledger.events) == 4


def test_delay_is_retried_like_queue():
    from engine.stages.s12_execute.admission_control import admit_step
    snapshots = iter([_ok(system_overloaded=True), _ok(db_pool_pressure=True), _ok()])
    slept, ledger = [], Ledger()

    async def source():
        return next(snapshots)

    async def sleep(seconds):
        slept.append(seconds)

    decision = asyncio.run(admit_step(source, ledger=ledger, max_attempts=5, sleep=sleep))
    assert decision.status == "ACCEPT" and len(slept) == 2
    assert [p["status"] for _, p in ledger.events] == ["DELAY", "DELAY", "ACCEPT"]


def test_persistent_backpressure_ends_as_admission_exhausted():
    from engine.stages.s12_execute.admission_control import admit_step, reject_outcome

    async def source():
        return _ok(db_pool_pressure=True)

    async def sleep(seconds):
        pass

    decision = asyncio.run(admit_step(source, ledger=Ledger(), max_attempts=2, sleep=sleep))
    assert (decision.status, decision.reason) == ("REJECT", "admission_exhausted")
    assert reject_outcome(decision) == ("admission_exhausted", "consolidate")


@pytest.mark.parametrize("gate,expected", [
    ("1", ("kill_switch_engaged", "revocation")), ("3", ("authorization_revoked", "revocation")),
    ("10", ("budget_exhausted", "budget")), ("2", ("admission_rejected", "consolidate")),
    ("6", ("admission_rejected", "consolidate")), ("8", ("admission_rejected", "consolidate"))])
def test_reject_is_mapped_by_gate(gate, expected):
    from engine.stages.s12_execute.admission_control import evaluate, reject_outcome
    field, value = next((g[1], g[2]) for g in GATES if g[0] == gate)
    assert reject_outcome(evaluate(_ok(**{field: value}))) == expected


def test_exhausted_admission_keeps_its_own_reason_and_non_rejects_have_no_outcome():
    """§8 step 1: after the bounded QUEUE/DELAY, a REJECT with reason admission_exhausted (a C22 terminal reason of its
    own); the run is consolidated like any other non-revocation REJECT (DEF-005)."""
    from contracts.step_admission import AdmissionDecision
    from engine.stages.s12_execute.admission_control import reject_outcome
    assert reject_outcome(AdmissionDecision("REJECT", reason="admission_exhausted")) == ("admission_exhausted",
                                                                                          "consolidate")
    for status in ("ACCEPT", "QUEUE", "DELAY", "DEGRADE"):
        with pytest.raises(ValueError):
            reject_outcome(AdmissionDecision(status))


def test_admission_module_touches_no_database():
    """Admission is stateless (WORKER_LIFECYCLE §10): it reserves nothing and holds no lease."""
    from tests_golden.fixtures.code_scan import ROOT, imports, sql_statements
    path = ROOT / "src/engine/stages/s12_execute/admission_control.py"
    assert not any(m.startswith("adapters") or m == "asyncpg" for m in imports(path)) and sql_statements(path) == []


# --- worker selection ----------------------------------------------------------------------------------------------

def test_selection_prefers_the_current_owner_then_free_capacity():
    from engine.stages.s12_execute.selection import select_worker
    busy_owner = _candidate("w-owner", capacity=4, load=3)
    idle = _candidate("w-idle", capacity=4, load=0)
    assert select_worker([idle, busy_owner], current_owner="w-owner") == "w-owner"   # 0.30 + 0.05 > 0.20
    assert select_worker([busy_owner, idle], current_owner=None) == "w-idle"


def test_selection_is_deterministic_and_breaks_ties_by_worker_id():
    from engine.stages.s12_execute.selection import select_worker
    candidates = [_candidate(w, capacity=2) for w in ("w-c", "w-a", "w-b")]
    picks = {select_worker(order, current_owner=None) for order in (candidates, candidates[::-1], candidates[1:] + candidates[:1])}
    assert picks == {"w-a"}


def test_a_worker_at_capacity_is_never_selected():
    from engine.stages.s12_execute.selection import select_worker
    full_owner = _candidate("w-full", capacity=1, load=1)
    assert select_worker([full_owner], current_owner="w-full") is None
    assert select_worker([full_owner, _candidate("w-z", capacity=5, load=4)], current_owner="w-full") == "w-z"


def test_no_candidate_is_no_worker():
    from engine.stages.s12_execute.selection import lease_for_step

    async def none():
        return []

    async def acquire(worker_id):
        raise AssertionError("no acquisition without a candidate")

    assert asyncio.run(lease_for_step(candidates=none, acquire=acquire, current_owner=None, max_attempts=3)) == "no_worker"


def test_lease_failure_reselects_then_lease_unavailable():
    from engine.stages.s12_execute.selection import lease_for_step
    tried = []

    async def candidates():
        return [_candidate("w-1", capacity=2), _candidate("w-2", capacity=2)]

    async def acquire(worker_id):
        tried.append(worker_id)
        return None

    result = asyncio.run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=3))
    assert result == "lease_unavailable" and len(tried) == 3


def test_lease_success_returns_the_lease():
    from engine.stages.s12_execute.selection import lease_for_step
    sentinel = object()

    async def candidates():
        return [_candidate("w-1")]

    async def acquire(worker_id):
        return sentinel

    assert asyncio.run(lease_for_step(candidates=candidates, acquire=acquire, current_owner=None, max_attempts=2)) is sentinel
