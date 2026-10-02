"""M10 golden — adapter interface, mock adapter, reliability guard (gate commit G part 1). Owner-pinned.

Gate v10: C4 (five components by name; RELIABILITY §8 acquisition order, Bulkhead first; health and billing after the
adapter returns, for every outcome), C31 (BudgetTracker is a read-only precondition: the step's reservation exists,
belongs to the step and is LOCKED, else ``BudgetStateError``; it never writes budget), C32 (``CallMeta``; ``probe``
default INCONCLUSIVE, never raises; ``observe`` default ``matches_expected=None``; an escaping exception becomes
``adapter_defect``; timeouts only from TimeoutManager), C37 (half-open: exactly one trial, every outcome recorded,
client errors never count; the Bulkhead slot is released on every exit; probes and observations take their own slot
and their own timeout), §15.3 (mock adapter with a side-effect ledger per idempotency key), §21 S3 (components behind
injected interfaces, no module-level mutable state), S6 (credentials only through ``CredentialProvider``).
Rulings: CONF-021 (the guard and adapters use the frozen ``contracts.step_execution.AdapterResult``), CONF-022 (the
breaker is keyed per provider: the frozen S8 interface is ``state(provider_id)``), CONF-023 (half-open 4xx and an
adapter's own ``TimeoutError``).

Interface this file fixes:
  * ``contracts.adapter_interface``:
      ``CallMeta`` (frozen): ``idempotency_key``, ``attempt_id``, ``provider_call_id``, ``tenant_id``.
      ``ProbeOutcome`` (StrEnum): EXECUTED_SUCCESS, EXECUTED_FAILURE, NOT_EXECUTED, INCONCLUSIVE.
      ``Observation`` (frozen, WORKER_LIFECYCLE §9): ``attempt``, ``observed_at``, ``provider_response_code``,
        ``observed_state``, ``matches_expected``, ``error``.
      ``ErrorClass`` (StrEnum): not_dispatched, rate_limited, server_error, client_error, adapter_defect, timeout,
        circuit_open, retry_storm; ``RETRYABLE`` = {not_dispatched, rate_limited, server_error}.
      ``BaseAdapter`` (ABC): abstract ``async call(kernel_op_id, params, binding, context, *, call_meta=None) ->
        AdapterResult``; ``async probe(kernel_op_id, params, binding, context, *, call_meta) -> ProbeOutcome``
        (default INCONCLUSIVE); ``async observe(kernel_op_id, observation_spec, binding, context) -> Observation``
        (default ``matches_expected=None``, ``error="observe_not_supported"``).
      ``CredentialProvider`` (Protocol): ``async credential(tenant_id, connection_id) -> str``.
      ``BudgetStateError`` (Exception).
      ``GuardedCall`` (frozen): ``kernel_op_id``, ``params``, ``binding`` (FrozenBindingIdentity), ``context``
        (ExecutionContext), ``call_meta``, ``step_id``, ``reservation_id``, ``attempt``, ``timeout_s``. Construction
        fails closed with ``ValueError`` when ``call_meta.tenant_id`` differs from ``context.tenant_id`` (C34),
        ``attempt < 1`` or ``timeout_s <= 0``.
  * ``engine.stages.s12_execute.reliability``:
      ``BudgetTracker(lookup)`` — ``async check(call)``: ``await lookup.reservation(tenant_id, reservation_id)`` must
        return a row whose ``step_id`` is the call's and whose ``status`` is ``locked``; else ``BudgetStateError``.
      ``TimeoutManager()`` — ``async run(awaitable, timeout_s)``: the result, or ``TimeoutError`` when ITS deadline
        passes.
      ``ReliabilityGuard(adapter, *, bulkhead, breaker, budget, retry_storm, timeouts, health, billing,
        probe_timeout_s)``:
        ``async call(call: GuardedCall) -> AdapterResult`` — acquisition order: ``bulkhead.slot(provider)`` (async
          context manager), ``breaker.allow(provider)``, ``await budget.check(call)``, on ``attempt > 1``
          ``retry_storm.allow_retry(provider, kernel_op_id)``, ``await timeouts.run(adapter.call(...), timeout_s)``;
          then ``breaker.record_success/record_failure/record_ignored(provider)``, ``health.record(provider,
          status, latency_ms)``, ``billing.record(call_meta, kernel_op_id, status)``; the slot is released on every
          exit. Normalised result: ``ok``; ``error`` with an ``ErrorClass`` and ``retryable`` = class in RETRYABLE
          (an unknown class or a non-``AdapterResult`` is ``adapter_defect``); ``timeout`` (TimeoutManager's deadline,
          an adapter-reported ``timeout``, or a ``TimeoutError`` escaping the adapter: the outcome is unknown).
          Breaker: ``ok`` success; ``client_error`` ignored; everything else failure. Refusals without an adapter
          call: breaker closed to the call → ``error circuit_open``; retry storm → ``error retry_storm``; a trial the
          breaker admitted but that never reached the adapter is released with ``record_ignored``.
          ``BudgetStateError`` propagates. An exception escaping the adapter is logged at ERROR with the
          ``attempt_id`` and ``kernel_op_id`` as record attributes (the alert), never its message. A call cancelled
          while the adapter runs (``CancelledError``) propagates after releasing its half-open trial
          (``record_ignored``) and its slot.
        ``async probe(call) -> ProbeOutcome`` and ``async observe(kernel_op_id, spec, binding, context) ->
          Observation`` — own Bulkhead slot, ``probe_timeout_s``, no breaker, no budget; never raise (INCONCLUSIVE /
          ``matches_expected=None``).
  * ``adapters.runtime.reliability``: ``InProcessBulkhead(max_concurrent)`` (+ ``in_use(provider)``),
    ``InProcessRetryStormGuard(max_retries, window_s, monotonic=time.monotonic)``, ``InProcessHealthMonitor()``
    (+ ``events``), ``InProcessBilling()`` (+ ``events``).
  * ``adapters.runtime.circuit_breaker.InProcessCircuitBreaker(failure_threshold, cooldown_seconds, monotonic)``
    gains ``allow`` and ``record_ignored``; ``state`` keeps the S8 names; HALF_OPEN admits one trial at a time.
  * ``adapters.postgres.budget_reserver.PostgresBudgetReserver.reservation(tenant_id, reservation_id)`` → a row with
    ``reservation_id``, ``step_id``, ``execution_id``, ``status`` (or None).
  * ``adapters.runtime.mock_adapter.MockAdapter(credentials)`` (a ``BaseAdapter``): ``program(kernel_op_id, call=
    "success", *, n=0, ms=0, probe="ledger", observe="ledger")``; ``call`` behaviours: success,
    fail_500_then_success, rate_limit_429, auth_401, validation_422, timeout_executed, timeout_not_executed,
    timeout_failed (executes, fails, then times out), verify_mismatch, slow, connect_refused, raise_exception;
    ``probe``: ledger (from the side-effect ledger), inconclusive, default (the BaseAdapter default); ``observe``:
    ledger, default. ``side_effects(idempotency_key)`` counts real executions; a key already executed successfully is
    not executed again; ``calls`` and ``probes`` list the ``CallMeta`` of every call and probe; with ``n > 0``,
    ``timeout_not_executed`` times out without executing n times and then succeeds (added with M13). Each
    call/probe/observe asks ``credentials.credential(tenant_id, connection_id)``.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

SECRET = "sk-golden-secret-7c1e"
T = "golden-tenant"


# --- builders ---------------------------------------------------------------------------------------------------------

class Credentials:
    def __init__(self):
        self.requests = []

    async def credential(self, tenant_id, connection_id):
        self.requests.append((tenant_id, connection_id))
        return SECRET


def _context(tenant=T):
    from contracts.execution_context import ExecutionContext
    return ExecutionContext(trace_id="tr-1", request_id="req-1", tenant_id=tenant, workspace_id="ws", user_id="u",
                            connection_id="conn-1")


def _binding(provider="mockp", op="mock.op"):
    from contracts.frozen_binding import FrozenBindingIdentity
    return FrozenBindingIdentity(binding_id="b-1", capability_id="cap", kernel_op_id=op, provider=provider,
                                 engine_module="m", adapter_class="MockAdapter", effective_risk=0.1,
                                 effective_mutation="W", resolved_at_stage="S5")


def _call(attempt=1, *, op="mock.op", key="req-1:s1", timeout_s=2.0, reservation_id="r-1", step_id="e-1:s1",
          provider="mockp"):
    from contracts.adapter_interface import CallMeta, GuardedCall
    meta = CallMeta(idempotency_key=key, attempt_id=f"att-0-{attempt}", provider_call_id=f"pc-{attempt}", tenant_id=T)
    return GuardedCall(kernel_op_id=op, params={"name": "Ana"}, binding=_binding(provider, op), context=_context(),
                       call_meta=meta, step_id=step_id, reservation_id=reservation_id, attempt=attempt,
                       timeout_s=timeout_s)


class LockedBudget:
    """A BudgetTracker stand-in that always passes (the guard's own budget check is tested separately)."""
    async def check(self, call):
        return None


def _mock(**program):
    from adapters.runtime.mock_adapter import MockAdapter
    creds = Credentials()
    mock = MockAdapter(creds)
    if program:
        mock.program("mock.op", **program)
    return mock, creds


def _guard(adapter, *, breaker=None, budget=None, bulkhead=None, retry_storm=None, probe_timeout_s=0.5):
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    from adapters.runtime.reliability import (InProcessBilling, InProcessBulkhead, InProcessHealthMonitor,
                                              InProcessRetryStormGuard)
    from engine.stages.s12_execute.reliability import ReliabilityGuard, TimeoutManager
    health, billing = InProcessHealthMonitor(), InProcessBilling()
    guard = ReliabilityGuard(
        adapter, bulkhead=bulkhead or InProcessBulkhead(4), breaker=breaker or InProcessCircuitBreaker(5, 30.0),
        budget=budget or LockedBudget(), retry_storm=retry_storm or InProcessRetryStormGuard(10, 60.0),
        timeouts=TimeoutManager(), health=health, billing=billing, probe_timeout_s=probe_timeout_s)
    return guard, health, billing


def _run(coro):
    return asyncio.run(coro)


# --- acquisition order (C4, RELIABILITY §8) --------------------------------------------------------------------------

class Order:
    """Spy components: each records its name when the guard uses it."""
    def __init__(self):
        self.seen = []

    def bulkhead(self):
        order = self

        class Slot:
            async def __aenter__(self):
                order.seen.append("bulkhead")

            async def __aexit__(self, *exc):
                order.seen.append("bulkhead_released")

        class Bulkhead:
            def slot(self, provider):
                return Slot()
        return Bulkhead()

    def breaker(self):
        order = self

        class Breaker:
            def allow(self, provider):
                order.seen.append("breaker")
                return True

            def record_success(self, provider):
                order.seen.append("breaker_success")

            def record_failure(self, provider):
                order.seen.append("breaker_failure")

            def record_ignored(self, provider):
                order.seen.append("breaker_ignored")

            def state(self, provider):
                return "CLOSED"
        return Breaker()

    def budget(self):
        order = self

        class Budget:
            async def check(self, call):
                order.seen.append("budget")
        return Budget()

    def retry_storm(self):
        order = self

        class Storm:
            def allow_retry(self, provider, operation):
                order.seen.append("retry_storm")
                return True
        return Storm()


@pytest.mark.parametrize("attempt,expected", [
    (1, ["bulkhead", "breaker", "budget", "adapter", "breaker_success", "bulkhead_released"]),
    (2, ["bulkhead", "breaker", "budget", "retry_storm", "adapter", "breaker_success", "bulkhead_released"])])
def test_acquisition_order_is_bulkhead_first(attempt, expected):
    from adapters.runtime.reliability import InProcessBilling, InProcessHealthMonitor
    from contracts.adapter_interface import BaseAdapter
    from contracts.step_execution import AdapterResult
    from engine.stages.s12_execute.reliability import ReliabilityGuard, TimeoutManager
    order = Order()

    class Adapter(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            order.seen.append("adapter")
            return AdapterResult("ok")

    guard = ReliabilityGuard(Adapter(), bulkhead=order.bulkhead(), breaker=order.breaker(), budget=order.budget(),
                             retry_storm=order.retry_storm(), timeouts=TimeoutManager(), health=InProcessHealthMonitor(),
                             billing=InProcessBilling(), probe_timeout_s=0.5)
    assert _run(guard.call(_call(attempt))).status == "ok"
    assert order.seen == expected


# --- normalisation, adapter_defect, timeouts (C32, C35) --------------------------------------------------------------

@pytest.mark.parametrize("behaviour,status,error_class,retryable", [
    ("success", "ok", None, False),
    ("fail_500_then_success", "error", "server_error", True),
    ("rate_limit_429", "error", "rate_limited", True),
    ("connect_refused", "error", "not_dispatched", True),
    ("auth_401", "error", "client_error", False),
    ("validation_422", "error", "client_error", False),
    ("raise_exception", "error", "adapter_defect", False),
])
def test_results_are_normalised(behaviour, status, error_class, retryable):
    mock, _ = _mock(call=behaviour, n=1)
    guard, _, _ = _guard(mock)
    result = _run(guard.call(_call()))
    assert (result.status, result.error_class, result.retryable) == (status, error_class, retryable)


def test_an_escaping_exception_is_adapter_defect_and_its_message_never_leaks(caplog):
    mock, _ = _mock(call="raise_exception")
    guard, health, billing = _guard(mock)
    caplog.set_level(logging.DEBUG)
    result = _run(guard.call(_call()))
    assert (result.status, result.error_class, result.retryable) == ("error", "adapter_defect", False)
    assert SECRET not in repr(result) + repr(health.events) + repr(billing.events) + caplog.text


def test_an_adapter_defect_raises_one_alert_carrying_the_attempt(caplog):
    mock, _ = _mock(call="raise_exception")
    caplog.set_level(logging.DEBUG)
    _run(_guard(mock)[0].call(_call(attempt=1)))
    alerts = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(alerts) == 1
    assert (getattr(alerts[0], "attempt_id", None), getattr(alerts[0], "kernel_op_id", None)) == ("att-0-1", "mock.op")


def test_an_unclassified_error_or_foreign_result_is_adapter_defect():
    from contracts.adapter_interface import BaseAdapter
    from contracts.step_execution import AdapterResult

    class Odd(BaseAdapter):
        def __init__(self, out):
            self.out = out

        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            return self.out

    for out in (AdapterResult("error", True, "weird_class"), {"status": "ok"}, AdapterResult("partial")):
        result = _run(_guard(Odd(out))[0].call(_call()))
        assert (result.status, result.error_class, result.retryable) == ("error", "adapter_defect", False), out


@pytest.mark.parametrize("behaviour,executed", [("timeout_executed", 1), ("timeout_not_executed", 0)])
def test_timeout_manager_decides_timeouts(behaviour, executed):
    mock, _ = _mock(call=behaviour)
    guard, health, billing = _guard(mock)
    result = _run(guard.call(_call(timeout_s=0.05)))
    assert (result.status, result.error_class) == ("timeout", "timeout")
    assert mock.side_effects("req-1:s1") == executed
    assert len(health.events) == 1 and len(billing.events) == 1        # recorded for the UNKNOWN outcome too


def test_an_adapters_own_timeout_error_is_an_unknown_outcome_not_a_defect():
    from contracts.adapter_interface import BaseAdapter

    class ClientTimeout(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            raise TimeoutError("read timed out")

    result = _run(_guard(ClientTimeout())[0].call(_call(timeout_s=5)))
    assert (result.status, result.error_class) == ("timeout", "timeout")


def test_timeouts_are_never_inferred_from_error_text():
    from contracts.adapter_interface import BaseAdapter
    from contracts.step_execution import AdapterResult

    class Texty(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            return AdapterResult("error", True, "server_error", {"message": "upstream timeout, timed out"})

    result = _run(_guard(Texty())[0].call(_call()))
    assert (result.status, result.error_class) == ("error", "server_error")


# --- BudgetTracker (C31) ---------------------------------------------------------------------------------------------

async def _seed_locked(schema):
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    from adapters.postgres.fencing import FenceHolder
    tenant = "golden-guard"
    await schema.execute("INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation,"
                         " policy_version_id) VALUES ($1, 'g', 'active', 100, false, 'IRREVERSIBLE', 'p1')"
                         " ON CONFLICT DO NOTHING", tenant, tenant=tenant)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ('ws-guard', $1, 'w')"
                         " ON CONFLICT DO NOTHING", tenant, tenant=tenant)
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ('u-guard', $1, 'active')"
                         " ON CONFLICT DO NOTHING", tenant, tenant=tenant)
    await schema.execute(
        "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,"
        " conversation_id, status, actor_type, actor_id, budget_spent) VALUES ('e-guard', 'req-guard', 'tr', 'task',"
        " 'u-guard', $1, 'ws-guard', 'conv', 'running', 'user', 'u-guard', 0)", tenant, tenant=tenant)
    await schema.execute("INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id, fencing_token,"
                         " checkpoint_sequence, updated_at) VALUES ('e-guard', $1, 'runtime-A', 3, 0, now())",
                         tenant, tenant=tenant)
    for step in ("s1", "s2"):
        await schema.execute(
            "INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, kernel_op_id,"
            " resolved_binding_id, effective_risk, effective_mutation, request_fingerprint, status, attempt)"
            " VALUES ($1, $2, 'e-guard', $3, 'mock.op', 'b-1', 0.1, 'W', 'fp', 'running', 1)",
            f"e-guard:{step}", step, tenant, tenant=tenant)
    reserver = PostgresBudgetReserver(schema.database())
    holder = FenceHolder(tenant_id=tenant, execution_id="e-guard", runtime_instance_id="runtime-A", fence_token=3)
    locked = await reserver.reserve(holder, user_id="u-guard", step_id="e-guard:s1", cost=5)
    await reserver.lock(holder, locked.reservation_id, reason="step_started")
    reserved = await reserver.reserve(holder, user_id="u-guard", step_id="e-guard:s2", cost=5)
    return tenant, reserver, locked.reservation_id, reserved.reservation_id


def _budget_call(tenant, reservation_id, step_id, attempt=1):
    from contracts.adapter_interface import CallMeta, GuardedCall
    meta = CallMeta(idempotency_key=f"req-guard:{step_id}", attempt_id=f"att-0-{attempt}",
                    provider_call_id=f"pc-{attempt}", tenant_id=tenant)
    return GuardedCall(kernel_op_id="mock.op", params={}, binding=_binding(), context=_context(tenant), call_meta=meta,
                       step_id=step_id, reservation_id=reservation_id, attempt=attempt, timeout_s=2.0)


@pytest.fixture(scope="module")
def seeded(db_schema):
    """(tenant, reserver, the LOCKED reservation of e-guard:s1, the RESERVED one of e-guard:s2), seeded once."""
    return db_schema.loop.run_until_complete(_seed_locked(db_schema))


def test_budget_tracker_never_writes_budget_across_retries(db_schema, run, seeded):
    from engine.stages.s12_execute.reliability import BudgetTracker
    tenant, reserver, locked, _ = seeded
    mock, _ = _mock(call="fail_500_then_success", n=3)
    guard, _, _ = _guard(mock, budget=BudgetTracker(reserver))
    before = run(db_schema.fetch("SELECT * FROM budget_reservations WHERE tenant_id = $1 ORDER BY reservation_id",
                                 tenant))
    logged = run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE entity_type = 'reservation'"))
    results = [run(guard.call(_budget_call(tenant, locked, "e-guard:s1", attempt))) for attempt in (1, 2, 3)]
    assert [r.error_class for r in results] == ["server_error"] * 3
    assert run(db_schema.fetch("SELECT * FROM budget_reservations WHERE tenant_id = $1 ORDER BY reservation_id",
                               tenant)) == before
    assert run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE entity_type = 'reservation'")) == logged


@pytest.mark.parametrize("case", ["not_locked", "other_step", "missing"])
def test_budget_tracker_refuses_without_the_steps_locked_reservation(db_schema, run, seeded, case):
    from contracts.adapter_interface import BudgetStateError
    from engine.stages.s12_execute.reliability import BudgetTracker
    tenant, reserver, locked, reserved = seeded
    reservation, step = {"not_locked": (reserved, "e-guard:s2"), "other_step": (locked, "e-guard:s2"),
                         "missing": ("no-such-reservation", "e-guard:s1")}[case]
    mock, _ = _mock(call="success")
    guard, health, billing = _guard(mock, budget=BudgetTracker(reserver))
    with pytest.raises(BudgetStateError):
        run(guard.call(_budget_call(tenant, reservation, step)))
    assert mock.side_effects(f"req-guard:{step}") == 0 and health.events == [] and billing.events == []


# --- circuit breaker, half-open (C37) --------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _open_breaker():
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    clock = Clock()
    breaker = InProcessCircuitBreaker(1, 10.0, clock)
    breaker.record_failure("mockp")
    assert breaker.state("mockp") == "OPEN"
    return breaker, clock


def test_an_open_breaker_refuses_without_calling():
    breaker, _ = _open_breaker()
    mock, _ = _mock(call="success")
    result = _run(_guard(mock, breaker=breaker)[0].call(_call()))
    assert (result.status, result.error_class, result.retryable) == ("error", "circuit_open", False)
    assert mock.side_effects("req-1:s1") == 0


@pytest.mark.parametrize("behaviour,timeout_s,after", [
    ("success", 2.0, "CLOSED"),
    ("fail_500_then_success", 2.0, "OPEN"),
    ("connect_refused", 2.0, "OPEN"),
    ("timeout_not_executed", 0.05, "OPEN"),                    # UNKNOWN outcome: conservative
    ("raise_exception", 2.0, "OPEN"),                          # unclassified: conservative
    ("auth_401", 2.0, "HALF_OPEN"),                            # a client error is not counted either way
    ("validation_422", 2.0, "HALF_OPEN"),
])
def test_half_open_trial_outcome_is_always_recorded(behaviour, timeout_s, after):
    breaker, clock = _open_breaker()
    clock.t += 11
    assert breaker.state("mockp") == "HALF_OPEN"
    mock, _ = _mock(call=behaviour, n=1)
    _run(_guard(mock, breaker=breaker)[0].call(_call(timeout_s=timeout_s)))
    assert breaker.state("mockp") == after
    if after == "HALF_OPEN":                                   # never stuck: the next call is admitted as a trial
        assert breaker.allow("mockp") is True


def test_half_open_admits_exactly_one_trial():
    breaker, clock = _open_breaker()
    clock.t += 11
    mock, _ = _mock(call="slow", ms=200)
    guard, _, _ = _guard(mock, breaker=breaker)

    async def both():
        return await asyncio.gather(guard.call(_call(key="k-1")), guard.call(_call(key="k-2")))

    results = sorted((r.status, r.error_class) for r in _run(both()))
    assert results == [("error", "circuit_open"), ("ok", None)] and breaker.state("mockp") == "CLOSED"


def test_a_trial_that_never_reaches_the_adapter_is_released():
    from contracts.adapter_interface import BudgetStateError

    class Refusing:
        async def check(self, call):
            raise BudgetStateError("not locked")

    breaker, clock = _open_breaker()
    clock.t += 11
    mock, _ = _mock(call="success")
    with pytest.raises(BudgetStateError):
        _run(_guard(mock, breaker=breaker, budget=Refusing())[0].call(_call()))
    assert breaker.state("mockp") == "HALF_OPEN" and breaker.allow("mockp") is True


def test_client_errors_never_open_a_closed_breaker():
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    breaker = InProcessCircuitBreaker(2, 30.0)
    mock, _ = _mock(call="auth_401")
    guard, _, _ = _guard(mock, breaker=breaker)
    for i in range(5):
        _run(guard.call(_call(key=f"k-{i}")))
    assert breaker.state("mockp") == "CLOSED"


def _scripted(results):
    """An adapter returning the given results in order, one per call."""
    from contracts.adapter_interface import BaseAdapter

    class Scripted(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            return left.pop(0)

    left = list(results)
    return Scripted()


def test_the_breaker_opens_on_consecutive_failures_only():
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    from contracts.step_execution import AdapterResult
    fail, ok, client = (AdapterResult("error", True, "server_error"), AdapterResult("ok"),
                        AdapterResult("error", False, "client_error"))
    breaker = InProcessCircuitBreaker(3, 30.0, Clock())
    guard, _, _ = _guard(_scripted([fail, fail, ok, fail, client, fail, fail]), breaker=breaker)
    seen = []
    for i in range(7):
        _run(guard.call(_call(key=f"k-{i}")))
        seen.append(breaker.state("mockp"))
    # a success resets the count; a client error neither counts nor resets
    assert seen == ["CLOSED"] * 6 + ["OPEN"]


def test_a_trial_refused_by_the_retry_storm_is_released():
    from adapters.runtime.reliability import InProcessRetryStormGuard
    breaker, clock = _open_breaker()
    clock.t += 11
    mock, _ = _mock(call="success")
    guard, _, _ = _guard(mock, breaker=breaker, retry_storm=InProcessRetryStormGuard(0, 60.0, Clock()))
    result = _run(guard.call(_call(attempt=2)))
    assert (result.status, result.error_class) == ("error", "retry_storm") and mock.side_effects("req-1:s1") == 0
    assert breaker.state("mockp") == "HALF_OPEN" and breaker.allow("mockp") is True


def test_a_cancelled_call_releases_its_trial_and_its_slot():
    from adapters.runtime.reliability import InProcessBulkhead
    breaker, clock = _open_breaker()
    clock.t += 11
    bulkhead = InProcessBulkhead(1)
    mock, _ = _mock(call="slow", ms=2000)
    guard, _, _ = _guard(mock, breaker=breaker, bulkhead=bulkhead)

    async def scenario():
        task = asyncio.create_task(guard.call(_call(timeout_s=5.0)))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(scenario())
    assert bulkhead.in_use("mockp") == 0
    assert breaker.state("mockp") == "HALF_OPEN" and breaker.allow("mockp") is True     # never stuck half-open


@pytest.mark.parametrize("change", [{"tenant": "other-tenant"}, {"attempt": 0}, {"timeout_s": 0}, {"timeout_s": -1}])
def test_a_guarded_call_that_is_not_self_consistent_cannot_be_built(change):
    from contracts.adapter_interface import CallMeta, GuardedCall
    attempt = change.get("attempt", 1)
    meta = CallMeta(idempotency_key="req-1:s1", attempt_id="att-0-1", provider_call_id="pc-1",
                    tenant_id=change.get("tenant", T))
    with pytest.raises(ValueError):
        GuardedCall(kernel_op_id="mock.op", params={}, binding=_binding(), context=_context(), call_meta=meta,
                    step_id="e-1:s1", reservation_id="r-1", attempt=attempt, timeout_s=change.get("timeout_s", 2.0))


# --- retry storm, bulkhead, health, billing --------------------------------------------------------------------------

def test_retry_storm_blocks_retries_not_first_attempts():
    from adapters.runtime.reliability import InProcessRetryStormGuard
    mock, _ = _mock(call="success")
    guard, _, _ = _guard(mock, retry_storm=InProcessRetryStormGuard(2, 60.0, Clock()))
    retries = [_run(guard.call(_call(attempt=2, key=f"k-{i}"))) for i in range(3)]
    assert [(r.status, r.error_class) for r in retries] == [("ok", None), ("ok", None), ("error", "retry_storm")]
    assert mock.side_effects("k-2") == 0
    assert _run(guard.call(_call(attempt=1, key="k-first"))).status == "ok"


def test_the_retry_storm_window_slides_and_is_per_operation():
    from adapters.runtime.reliability import InProcessRetryStormGuard
    clock = Clock()
    storm = InProcessRetryStormGuard(2, 60.0, clock)
    assert [storm.allow_retry("mockp", "mock.op") for _ in range(3)] == [True, True, False]
    assert storm.allow_retry("mockp", "other.op") is True and storm.allow_retry("otherp", "mock.op") is True
    clock.t += 30
    assert storm.allow_retry("mockp", "mock.op") is False
    clock.t += 31                                              # the first two retries left the 60 s window
    assert [storm.allow_retry("mockp", "mock.op") for _ in range(3)] == [True, True, False]


@pytest.mark.parametrize("behaviour,timeout_s", [("success", 2.0), ("fail_500_then_success", 2.0),
                                                 ("timeout_executed", 0.05), ("raise_exception", 2.0)])
def test_the_bulkhead_slot_is_released_on_every_exit(behaviour, timeout_s):
    from adapters.runtime.reliability import InProcessBulkhead
    bulkhead = InProcessBulkhead(1)
    mock, _ = _mock(call=behaviour, n=1)
    _run(_guard(mock, bulkhead=bulkhead)[0].call(_call(timeout_s=timeout_s)))
    assert bulkhead.in_use("mockp") == 0


def test_the_bulkhead_slot_is_released_when_the_breaker_refuses_or_the_budget_raises():
    from adapters.runtime.reliability import InProcessBulkhead
    from contracts.adapter_interface import BudgetStateError

    class Refusing:
        async def check(self, call):
            raise BudgetStateError("not locked")

    bulkhead = InProcessBulkhead(1)
    breaker, _ = _open_breaker()
    mock, _ = _mock(call="success")
    _run(_guard(mock, bulkhead=bulkhead, breaker=breaker)[0].call(_call()))
    assert bulkhead.in_use("mockp") == 0
    with pytest.raises(BudgetStateError):
        _run(_guard(mock, bulkhead=bulkhead, budget=Refusing())[0].call(_call()))
    assert bulkhead.in_use("mockp") == 0


def test_bulkhead_limits_concurrency_per_provider():
    from adapters.runtime.reliability import InProcessBulkhead
    bulkhead = InProcessBulkhead(1)
    mock, _ = _mock(call="slow", ms=100)
    mock.program("other.op", call="slow", ms=100)
    guard, _, _ = _guard(mock, bulkhead=bulkhead)
    peak = {}

    async def watch():
        while True:
            for p in ("mockp", "otherp"):
                peak[p] = max(peak.get(p, 0), bulkhead.in_use(p))
            await asyncio.sleep(0.005)

    async def scenario():
        watcher = asyncio.create_task(watch())
        await asyncio.gather(guard.call(_call(key="a")), guard.call(_call(key="b")),
                             guard.call(_call(key="c", op="other.op", provider="otherp")))
        watcher.cancel()

    _run(scenario())
    assert peak == {"mockp": 1, "otherp": 1}


def test_health_and_billing_are_recorded_after_every_adapter_call_and_never_without_one():
    mock, _ = _mock(call="fail_500_then_success", n=1)
    guard, health, billing = _guard(mock)
    _run(guard.call(_call(key="k-a")))
    _run(guard.call(_call(key="k-b")))
    assert len(health.events) == 2 and len(billing.events) == 2
    breaker, _ = _open_breaker()
    guard, health, billing = _guard(mock, breaker=breaker)
    _run(guard.call(_call(key="k-c")))
    assert health.events == [] and billing.events == []


# --- probe and observe (C32, C37) ------------------------------------------------------------------------------------

@pytest.mark.parametrize("behaviour,probe,outcome", [
    ("timeout_executed", "ledger", "executed_success"),
    ("timeout_failed", "ledger", "executed_failure"),
    ("timeout_not_executed", "ledger", "not_executed"),
    ("timeout_executed", "inconclusive", "inconclusive"),
    ("timeout_executed", "default", "inconclusive"),           # BaseAdapter default
])
def test_probe_outcomes(behaviour, probe, outcome):
    mock, _ = _mock(call=behaviour, probe=probe)
    guard, _, _ = _guard(mock)
    assert _run(guard.call(_call(timeout_s=0.05))).status == "timeout"
    assert _run(guard.probe(_call(timeout_s=0.05))) == outcome


def test_probe_never_raises_and_bypasses_an_open_breaker():
    from contracts.adapter_interface import BaseAdapter, ProbeOutcome
    from contracts.step_execution import AdapterResult

    class Broken(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            return AdapterResult("ok")

        async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
            raise RuntimeError(SECRET)

    class Hanging(Broken):
        async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
            await asyncio.sleep(60)

    class Knows(Broken):
        async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
            return ProbeOutcome.EXECUTED_SUCCESS

    breaker, _ = _open_breaker()
    assert _run(_guard(Knows(), breaker=breaker)[0].probe(_call())) == ProbeOutcome.EXECUTED_SUCCESS
    assert _run(_guard(Broken())[0].probe(_call())) == ProbeOutcome.INCONCLUSIVE
    assert _run(_guard(Hanging(), probe_timeout_s=0.05)[0].probe(_call())) == ProbeOutcome.INCONCLUSIVE


def test_the_default_observation_is_unknown_and_observations_never_raise():
    from contracts.adapter_interface import BaseAdapter

    class Hanging(BaseAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            raise AssertionError("observe never calls")

        async def observe(self, kernel_op_id, observation_spec, binding, context):
            await asyncio.sleep(60)

    mock, _ = _mock(call="success", observe="default")
    default = _run(_guard(mock)[0].observe("mock.op", {"idempotency_key": "req-1:s1"}, _binding(), _context()))
    assert default.matches_expected is None and default.error == "observe_not_supported"
    hung = _run(_guard(Hanging(), probe_timeout_s=0.05)[0].observe("mock.op", {}, _binding(), _context()))
    assert hung.matches_expected is None


@pytest.mark.parametrize("behaviour,matches", [("success", True), ("verify_mismatch", False)])
def test_mock_observation_reflects_the_side_effect(behaviour, matches):
    mock, _ = _mock(call=behaviour)
    guard, _, _ = _guard(mock)
    _run(guard.call(_call()))
    seen = _run(guard.observe("mock.op", {"idempotency_key": "req-1:s1"}, _binding(), _context()))
    assert seen.matches_expected is matches


def test_probes_and_observations_take_their_own_bulkhead_slot():
    from adapters.runtime.reliability import InProcessBulkhead
    bulkhead = InProcessBulkhead(1)
    mock, _ = _mock(call="slow", ms=150)
    guard, _, _ = _guard(mock, bulkhead=bulkhead)
    peak = []

    async def scenario():
        call = asyncio.create_task(guard.call(_call(key="k-slow")))
        await asyncio.sleep(0.03)
        probe = asyncio.create_task(guard.probe(_call(key="k-slow")))
        await asyncio.sleep(0.03)
        peak.append(bulkhead.in_use("mockp"))
        await asyncio.gather(call, probe)

    _run(scenario())
    assert peak == [1] and bulkhead.in_use("mockp") == 0


# --- mock adapter (§15.3) and credentials (S6) ------------------------------------------------------------------------

@pytest.mark.parametrize("behaviour,n,results", [
    ("fail_500_then_success", 2, ["server_error", "server_error", None]),
    ("rate_limit_429", 1, ["rate_limited", None, None]),
    ("connect_refused", 2, ["not_dispatched", "not_dispatched", None]),
])
def test_mock_failures_then_success(behaviour, n, results):
    mock, _ = _mock(call=behaviour, n=n)
    guard, _, _ = _guard(mock)
    got = [_run(guard.call(_call(attempt=i + 1))).error_class for i in range(3)]
    assert got == results and mock.side_effects("req-1:s1") == 1


def test_the_side_effect_ledger_honours_idempotency_keys():
    mock, _ = _mock(call="success")
    guard, _, _ = _guard(mock)
    for attempt in (1, 2, 3):
        assert _run(guard.call(_call(attempt=attempt))).status == "ok"
    assert _run(guard.call(_call(key="req-1:s2"))).status == "ok"
    assert (mock.side_effects("req-1:s1"), mock.side_effects("req-1:s2")) == (1, 1)


def test_credentials_come_only_from_the_credential_provider():
    from contracts.adapter_interface import CallMeta, GuardedCall
    mock, creds = _mock(call="success")
    guard, health, billing = _guard(mock)
    call = _call()
    result = _run(guard.call(call))
    assert creds.requests == [(T, "conn-1")]
    carried = repr(call) + repr(result) + repr(health.events) + repr(billing.events)
    assert SECRET not in carried
    for contract in (CallMeta, GuardedCall):
        names = {f for f in contract.__dataclass_fields__}
        assert not names & {"credential", "credentials", "secret", "api_key", "token", "password"}, contract


# --- architecture (§21 S3) -------------------------------------------------------------------------------------------

def test_no_module_level_mutable_state_in_s12_code():
    """S3: no module-level mutable globals in S12 code (the S0–S11 OWN-08 scan skips the s12_* packages)."""
    import ast
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    mutable = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
    factories = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter", "bytearray"}
    offenders = []
    for path in s12_files():
        for stmt in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
                continue
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            names = [t.id for t in targets if isinstance(t, ast.Name) and t.id not in {"__all__", "logger"}]
            value = stmt.value
            bad = isinstance(value, mutable) or (isinstance(value, ast.Call) and ast.unparse(value.func) in factories)
            if names and bad:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{stmt.lineno} {names}")
    assert offenders == []


def test_the_guard_writes_no_budget_and_opens_no_transaction():
    from tests_golden.fixtures.code_scan import ROOT, imports, sql_statements
    path = ROOT / "src/engine/stages/s12_execute/reliability.py"
    assert sql_statements(path) == [] and not any(m.startswith("adapters") or m == "asyncpg" for m in imports(path))
