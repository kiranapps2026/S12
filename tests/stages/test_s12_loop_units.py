"""S12 loop building blocks that need no database: state machines, guard, topological order."""
import asyncio

import pytest

from contracts.errors import StateTransitionError
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.stage_outputs import Step
from contracts.step_execution import AdapterResult, StepCall
from engine.stages.s12_execute import transitions
from engine.stages.s12_execute.guard import ReliabilityGuard
from engine.stages.s12_execute.loop import topological_order


# ---- state machines (STATE_TRANSITIONS §1-§3) -----------------------------------------------

@pytest.mark.parametrize("current,new", [
    ("pending", "running"), ("pending", "cancelled"), ("running", "completed"), ("running", "partial"),
    ("running", "failed"), ("running", "cancelled"), ("running", "dead_letter"), ("running", "reconciling"),
    ("reconciling", "completed"), ("reconciling", "dead_letter"), ("reconciling", "cancelled")])
def test_legal_run_moves(current, new):
    transitions.check_run(current, new)


@pytest.mark.parametrize("current,new", [
    ("pending", "completed"), ("pending", "failed"), ("pending", "dead_letter"), ("pending", "reconciling"),
    ("reconciling", "running"), ("failed", "running"), ("cancelled", "running"), ("dead_letter", "running"),
    ("completed", "pending"), ("completed", "running"), ("partial", "failed")])
def test_illegal_run_moves(current, new):
    with pytest.raises(StateTransitionError):
        transitions.check_run(current, new)


@pytest.mark.parametrize("current,new", [
    ("pending", "running"), ("pending", "skipped"), ("pending", "cancelled"), ("running", "completed"),
    ("running", "failed"), ("running", "cancelled"), ("running", "timeout"), ("running", "pending_probe"),
    ("timeout", "pending_probe"), ("pending_probe", "completed"), ("pending_probe", "pending"),
    ("pending_probe", "failed"), ("pending_probe", "dead_letter"), ("unknown", "pending_probe")])
def test_legal_step_moves(current, new):
    transitions.check_step(current, new)


@pytest.mark.parametrize("current,new", [
    ("timeout", "dead_letter"), ("timeout", "unknown"), ("pending", "pending_probe"), ("unknown", "completed"),
    ("unknown", "failed"), ("pending", "completed"), ("pending", "failed"), ("running", "pending"),
    ("failed", "running"), ("failed", "completed"), ("skipped", "running"), ("dead_letter", "running"),
    ("completed", "failed"), ("partial", "completed")])
def test_illegal_step_moves_including_no_silent_success(current, new):
    with pytest.raises(StateTransitionError):
        transitions.check_step(current, new)


def test_terminal_step_states_have_no_way_out():
    assert transitions.TERMINAL_STEP == {"completed", "partial", "failed", "cancelled", "skipped", "dead_letter"}


@pytest.mark.parametrize("current,new,ok", [
    ("pending", "reserved", True), ("pending", "released", True), ("reserved", "locked", True),
    ("reserved", "released", True), ("locked", "committed", True), ("locked", "released", True),
    ("reserved", "committed", False), ("pending", "committed", False), ("locked", "reserved", False),
    ("committed", "released", False), ("released", "locked", False), ("committed", "locked", False)])
def test_budget_moves(current, new, ok):
    if ok:
        transitions.check_budget(current, new)
    else:
        with pytest.raises(StateTransitionError):
            transitions.check_budget(current, new)


def test_the_tables_cannot_be_modified_at_runtime():
    with pytest.raises(TypeError):
        transitions.STEP["completed"] = frozenset({"running"})


# ---- topological order (C11) ------------------------------------------------------------------

def _step(sid, deps=()):
    return Step(id=sid, kernel_op_id="op", depends_on=tuple(deps))


def test_order_follows_dependencies_with_ties_by_plan_position():
    steps = [_step("c", ["a"]), _step("a"), _step("b"), _step("d", ["c", "b"])]
    assert [s.id for s in topological_order(steps)] == ["a", "c", "b", "d"]   # c (position 0) is ready before b
    chain = [_step("s1"), _step("s2", ["s1"]), _step("s3", ["s2"])]
    assert [s.id for s in topological_order(chain)] == ["s1", "s2", "s3"]


@pytest.mark.parametrize("steps", [
    [_step("a", ["b"]), _step("b", ["a"])], [_step("a", ["ghost"])], [_step("a"), _step("a")],
    [_step("a", ["a"])]])
def test_a_cycle_an_unknown_dependency_or_a_duplicate_id_is_refused(steps):
    with pytest.raises(ValueError):
        topological_order(steps)


# ---- reliability guard (C4, C31, C32, C37) -----------------------------------------------------

BINDING = FrozenBindingIdentity("b", "cap", "op", "crm", "engines.x", "A", 0.1, "W", "S5")


class Breaker:
    def __init__(self, state="CLOSED"):
        self._state, self.successes, self.failures = state, 0, 0

    def state(self, provider):
        return self._state

    def record_success(self, provider):
        self.successes += 1

    def record_failure(self, provider):
        self.failures += 1


class Adapter:
    def __init__(self, outcome=AdapterResult("ok"), delay=0.0):
        self.outcome, self.delay, self.calls = outcome, delay, 0

    async def call(self, call):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _call(step=None):
    return StepCall("t", "e", step or Step(id="s", kernel_op_id="op", mutation="W"), BINDING, None, 1)


def _guard(adapter, breaker):
    return ReliabilityGuard(adapter, breaker)


def _run(guard, status="locked", call=None):
    return asyncio.run(guard.execute(call or _call(), reservation_status=status))


@pytest.mark.parametrize("status", [None, "reserved", "released", "committed", "pending"])
def test_the_guard_never_calls_the_adapter_unless_the_reservation_is_locked(status):
    adapter = Adapter()
    result = _run(_guard(adapter, Breaker()), status)
    assert (result.status, result.error_class, adapter.calls) == ("error", "budget_not_locked", 0)


def test_an_open_or_missing_or_broken_breaker_refuses_without_calling():
    for breaker, klass in ((Breaker("OPEN"), "circuit_open"), (None, "circuit_unavailable")):
        adapter = Adapter()
        assert (_run(_guard(adapter, breaker)).error_class, adapter.calls) == (klass, 0)

    class Broken(Breaker):
        def state(self, provider):
            raise RuntimeError("x")
    adapter = Adapter()
    assert (_run(_guard(adapter, Broken())).error_class, adapter.calls) == ("circuit_unavailable", 0)


def test_a_half_open_breaker_admits_the_call():
    adapter = Adapter()
    assert _run(_guard(adapter, Breaker("HALF_OPEN"))).status == "ok" and adapter.calls == 1


def test_success_is_recorded_and_the_result_returned_unchanged():
    breaker, adapter = Breaker(), Adapter(AdapterResult("ok", data={"id": "1"}))
    result = _run(_guard(adapter, breaker))
    assert (result.data, breaker.successes, breaker.failures) == ({"id": "1"}, 1, 0)


def test_an_exception_becomes_adapter_defect_and_counts_against_the_breaker():
    breaker = Breaker()
    result = _run(_guard(Adapter(RuntimeError("boom")), breaker))
    assert (result.status, result.error_class, result.retryable, breaker.failures) == ("error", "adapter_defect", False, 1)


def test_a_malformed_result_is_an_adapter_defect():
    for bad in ({"status": "ok"}, None, AdapterResult("weird")):
        result = _run(_guard(Adapter(bad), Breaker()))
        assert result.error_class == "adapter_defect"


def test_provider_errors_count_but_client_errors_do_not():
    breaker = Breaker()
    _run(_guard(Adapter(AdapterResult("error", True, "server_error")), breaker))
    _run(_guard(Adapter(AdapterResult("error", False, "not_found")), breaker))
    _run(_guard(Adapter(AdapterResult("error", False, "unprocessable")), breaker))
    assert breaker.failures == 1


def test_a_call_longer_than_the_step_timeout_is_a_timeout_and_counts_as_a_failure():
    breaker = Breaker()
    step = Step(id="s", kernel_op_id="op", mutation="W", timeout=1)
    result = _run(_guard(Adapter(delay=3), breaker), call=_call(step))
    assert (result.status, result.error_class, breaker.failures) == ("timeout", "timeout", 1)


def test_breaker_bookkeeping_failures_never_change_the_outcome():
    class Flaky(Breaker):
        def record_success(self, provider):
            raise RuntimeError("bookkeeping")
    assert _run(_guard(Adapter(), Flaky())).status == "ok"
