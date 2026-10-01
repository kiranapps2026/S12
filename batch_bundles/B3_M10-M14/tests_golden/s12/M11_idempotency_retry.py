"""M11 golden — idempotency ledger and retry (gate commit G part 2). Owner-pinned.

Gate v10: §8 step 8 (per attempt: live check, ledger lookup, dispatch marker, guarded call, ledger record on a definitive
result; retryable errors stay RUNNING with backoff), C9 (step key ``f"{request_id}:{plan_step_id}"``, stable across
attempts; ``provider_call_id`` a UUID per invocation; ``attempt_id`` = ``att-{step_index}-{attempt}``), C17 (a hit makes
no adapter call and is a ledger event ``idempotency_hit``), C34 (lookups filter on tenant), C35 (dispatch marker before
every call; ``not_dispatched`` is a retryable definitive failure, never an episode), suites 6 (non-crash) and 7;
MUTATION_SAFETY §3 (retry ceilings), §5 (ledger; an expired record counts as none and never authorises a call for a
step that may already have run). Rulings: CONF-024 (the key uses ``plan_step_id``, MUTATION_SAFETY §5), CONF-025
(ledger rows only for results the adapter produced; retries exhausted leave no row).

Interface this file fixes:
  * ``contracts.idempotency``: ``step_idempotency_key(request_id, plan_step_id)``, ``attempt_id(step_index, attempt)``,
    ``LedgerRecord`` (frozen: ``kernel_op_id``, ``kind`` "success"|"failure", ``result`` AdapterResult),
    ``IdempotencyConflict`` (Exception).
  * ``adapters.postgres.idempotency.PostgresIdempotencyLedger(database)``:
      ``async lookup(tenant_id, idempotency_key) -> LedgerRecord | None`` — filters on both; an expired row is None.
      ``async store(holder, *, idempotency_key, kernel_op_id, result, ttl_s)`` — one ``fenced_write``; ``INSERT ... ON
      CONFLICT (idempotency_key) DO NOTHING``; when nothing was inserted, an existing row with the same tenant,
      ``kernel_op_id`` and kind is a hit (no error), anything else (including a row the tenant cannot see) raises
      ``IdempotencyConflict``.
  * ``adapters.postgres.step_attempts.PostgresStepAttempts(database)``: ``async dispatched(tenant_id, step_id) ->
    int | None``; ``async mark_dispatched(holder, step_id, attempt)`` — one ``fenced_write`` setting
    ``execution_steps.attempt`` and ``dispatched_attempt`` to ``attempt`` (no state transition).
  * ``engine.stages.s12_execute.retry_policy``: ``ceiling(mutation, retry_safety) -> int`` (1 for IRREVERSIBLE or
    ``retry_safety = never``; else R 3, W 2, D 2);
    ``max_attempts(mutation, retry_safety, step_max=None)`` = min(ceiling, step_max); ``backoff_s(mutation, attempt,
    base_s) > 0`` (D fixed, others exponential).
  * ``engine.stages.s12_execute.attempts``:
      ``StepAttempt`` (frozen): ``request_id``, ``plan_step_id``, ``step_index``, ``step_id``, ``kernel_op_id``,
        ``params``, ``mutation``, ``retry_safety``, ``step_max_attempts``, ``reservation_id``, ``timeout_s``,
        ``binding``, ``context``.
      ``AttemptDeps`` (frozen): ``guard`` (M10 ReliabilityGuard), ``ledger``, ``attempts``, ``live`` (the frozen
        ``LiveAuthorization`` port), ``events`` (``record(kind, payload)``), ``sleep``, ``backoff_base_s``,
        ``ledger_ttl_s``.
      ``AttemptOutcome`` (frozen): ``kind`` ("success" | "failure" | "uncertain" | "revoked"), ``result``,
        ``attempts`` (the last attempt number), ``cached`` (bool), ``reason`` (the revocation reason, or for
        "uncertain" ``timeout`` / ``dispatched_without_record``).
      ``async run_attempts(step, holder, deps, *, first_attempt=1) -> AttemptOutcome`` — per attempt n: live check
        (revoked → "revoked", no call); ledger lookup (hit → the cached kind, event ``idempotency_hit`` with
        ``step_id``, ``attempt_id``, ``kind``; no call; a row for the key whose ``kernel_op_id`` is not the step's
        raises ``IdempotencyConflict``, never a hit); a dispatch marker already at n without a ledger row →
        "uncertain" ``dispatched_without_record`` (no call); ``mark_dispatched(n)`` then event ``step_attempt``
        (``step_id``, ``attempt_id``, ``attempt``; C24: a retry is a ledger event, not a transition); the guarded call
        with ``CallMeta(key, attempt_id, uuid4, tenant)``; when the adapter was invoked (not ``circuit_open`` /
        ``retry_storm``) events ``ProviderCalled`` (``step_id``, ``attempt_id``, ``provider_call_id``,
        ``kernel_op_id``) and ``ProviderReturned`` (``step_id``, ``attempt_id``, ``provider_call_id``, ``status``);
        ``ok`` → store success → "success"; ``timeout`` → "uncertain"
        ``timeout``; a non-retryable error the adapter produced → store failure → "failure"; ``circuit_open`` /
        ``retry_storm`` → "failure" without a row; a retryable error with attempts left → ``await sleep(backoff)``
        and n + 1; retries exhausted → "failure" without a row. ``FencedOut`` and ``BudgetStateError`` propagate;
        a result whose ledger write is fenced out is discarded (no row: the new owner learns it by probing).
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants

RUNTIME = "runtime-A"
TOKEN = 5


# --- pure: keys and the retry matrix (C9, MUTATION_SAFETY §3, suite 7) ------------------------------------------------

def test_step_keys_are_stable_and_distinct_per_step():
    from contracts.idempotency import attempt_id, step_idempotency_key
    assert step_idempotency_key("req-9", "s1") == "req-9:s1" != step_idempotency_key("req-9", "s2")
    assert (attempt_id(0, 1), attempt_id(0, 2), attempt_id(3, 1)) == ("att-0-1", "att-0-2", "att-3-1")


@pytest.mark.parametrize("mutation,retry_safety,expected", [
    ("R", "safe", 3), ("R", "idempotent", 3), ("R", "never", 1),
    ("W", "safe", 2), ("W", "idempotent", 2), ("W", "never", 1),
    ("D", "idempotent", 2), ("D", "safe", 2), ("D", "never", 1),
    ("IRREVERSIBLE", "safe", 1), ("IRREVERSIBLE", "idempotent", 1), ("IRREVERSIBLE", "never", 1),
])
def test_retry_ceiling_matrix(mutation, retry_safety, expected):
    from engine.stages.s12_execute.retry_policy import ceiling
    assert ceiling(mutation, retry_safety) == expected


@pytest.mark.parametrize("mutation,retry_safety,step_max,expected", [
    ("R", "safe", 2, 2), ("R", "safe", 9, 3), ("R", "safe", None, 3), ("IRREVERSIBLE", "safe", 5, 1),
    ("D", "never", 4, 1)])
def test_the_step_policy_can_only_lower_the_ceiling(mutation, retry_safety, step_max, expected):
    from engine.stages.s12_execute.retry_policy import max_attempts
    assert max_attempts(mutation, retry_safety, step_max) == expected


def test_backoff_is_positive_exponential_and_fixed_for_deletes():
    from engine.stages.s12_execute.retry_policy import backoff_s
    r = [backoff_s("R", a, 0.01) for a in (1, 2, 3)]
    d = [backoff_s("D", a, 0.01) for a in (1, 2, 3)]
    assert all(x > 0 for x in r + d) and r[0] < r[1] < r[2] and d[0] == d[1] == d[2]


# --- database fixtures ------------------------------------------------------------------------------------------------

class Credentials:
    async def credential(self, tenant_id, connection_id):
        return "secret"


class Live:
    """The frozen LiveAuthorization port; ``revoke_on`` = the check number that answers Revoked."""
    def __init__(self, revoke_on=None, reason="authorization_revoked"):
        self.checks, self.revoke_on, self.reason = 0, revoke_on, reason

    async def check(self, *, tenant_id, workspace_id, user_id, connection_id, binding):
        from contracts.step_execution import Revoked
        self.checks += 1
        return Revoked(self.reason) if self.checks == self.revoke_on else None


class Events:
    def __init__(self):
        self.events = []

    async def record(self, kind, payload):
        self.events.append((kind, dict(payload)))


async def _seed(schema, tenant, *, steps, mutation="W", status="running"):
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    from adapters.postgres.fencing import FenceHolder
    execution = f"e-{tenant}"
    await schema.execute("INSERT INTO tenants (tenant_id, name, status, budget_pool, kill_switch_engaged, max_mutation,"
                         " policy_version_id) VALUES ($1, 'g', 'active', 1000, false, 'IRREVERSIBLE', 'p1')", tenant,
                         tenant=tenant)
    await schema.execute("INSERT INTO workspaces (workspace_id, tenant_id, name) VALUES ($1, $2, 'w')",
                         f"ws-{tenant}", tenant, tenant=tenant)
    await schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ($1, $2, 'active')", f"u-{tenant}",
                         tenant, tenant=tenant)
    await schema.execute(
        "INSERT INTO execution_runs (execution_id, request_id, trace_id, task_id, user_id, tenant_id, workspace_id,"
        " conversation_id, status, actor_type, actor_id, budget_spent) VALUES ($1, $2, 'tr', 'task', $3, $4, $5,"
        " 'conv', 'running', 'user', $3, 0)", execution, f"req-{tenant}", f"u-{tenant}", tenant, f"ws-{tenant}",
        tenant=tenant)
    await schema.execute("INSERT INTO execution_ownership (execution_id, tenant_id, runtime_instance_id, fencing_token,"
                         " checkpoint_sequence, updated_at) VALUES ($1, $2, $3, $4, 0, now())", execution, tenant,
                         RUNTIME, TOKEN, tenant=tenant)
    holder = FenceHolder(tenant_id=tenant, execution_id=execution, runtime_instance_id=RUNTIME, fence_token=TOKEN)
    reserver, reservations = PostgresBudgetReserver(schema.database()), {}
    for i in range(steps):
        step_id = f"{execution}:s{i}"
        await schema.execute(
            "INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, kernel_op_id,"
            " resolved_binding_id, effective_risk, effective_mutation, request_fingerprint, status, attempt)"
            " VALUES ($1, $2, $3, $4, 'mock.op', 'b-1', 0.1, $5, 'fp', $6, 0)",
            step_id, f"s{i}", execution, tenant, mutation, status, tenant=tenant)
        r = await reserver.reserve(holder, user_id=f"u-{tenant}", step_id=step_id, cost=1)
        await reserver.lock(holder, r.reservation_id, reason="step_started")
        reservations[step_id] = r.reservation_id
    return holder, reservations


def _context(tenant):
    from contracts.execution_context import ExecutionContext
    return ExecutionContext(trace_id="tr", request_id=f"req-{tenant}", tenant_id=tenant, workspace_id=f"ws-{tenant}",
                            user_id=f"u-{tenant}", connection_id="conn-1")


def _binding():
    from contracts.frozen_binding import FrozenBindingIdentity
    return FrozenBindingIdentity(binding_id="b-1", capability_id="cap", kernel_op_id="mock.op", provider="mockp",
                                 engine_module="m", adapter_class="MockAdapter", effective_risk=0.1,
                                 effective_mutation="W", resolved_at_stage="S5")


def _step(tenant, reservations, index=0, *, mutation="W", retry_safety="safe", step_max=None, timeout_s=2.0):
    from engine.stages.s12_execute.attempts import StepAttempt
    step_id = f"e-{tenant}:s{index}"
    return StepAttempt(request_id=f"req-{tenant}", plan_step_id=f"s{index}", step_index=index, step_id=step_id,
                       kernel_op_id="mock.op", params={"n": index}, mutation=mutation, retry_safety=retry_safety,
                       step_max_attempts=step_max, reservation_id=reservations[step_id], timeout_s=timeout_s,
                       binding=_binding(), context=_context(tenant))


def _deps(schema, adapter, *, live=None, bulkhead=None, sleep=None, events=None):
    from adapters.postgres.budget_reserver import PostgresBudgetReserver
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from adapters.postgres.step_attempts import PostgresStepAttempts
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    from adapters.runtime.reliability import (InProcessBilling, InProcessBulkhead, InProcessHealthMonitor,
                                              InProcessRetryStormGuard)
    from engine.stages.s12_execute.attempts import AttemptDeps
    from engine.stages.s12_execute.reliability import BudgetTracker, ReliabilityGuard, TimeoutManager
    db = schema.database()
    guard = ReliabilityGuard(adapter, bulkhead=bulkhead or InProcessBulkhead(4),
                             breaker=InProcessCircuitBreaker(50, 30.0), budget=BudgetTracker(PostgresBudgetReserver(db)),
                             retry_storm=InProcessRetryStormGuard(100, 60.0), timeouts=TimeoutManager(),
                             health=InProcessHealthMonitor(), billing=InProcessBilling(), probe_timeout_s=0.5)

    async def no_sleep(seconds):
        return None
    return AttemptDeps(guard=guard, ledger=PostgresIdempotencyLedger(db), attempts=PostgresStepAttempts(db),
                       live=live or Live(), events=events or Events(), sleep=sleep or no_sleep, backoff_base_s=0.001,
                       ledger_ttl_s=3600)


def _mock(call="success", **kw):
    from adapters.runtime.mock_adapter import MockAdapter
    mock = MockAdapter(Credentials())
    mock.program("mock.op", call, **kw)
    return mock


async def _attempts(schema, step, holder, deps, **kw):
    from engine.stages.s12_execute.attempts import run_attempts
    return await run_attempts(step, holder, deps, **kw)


def _row(schema, run, tenant, step_id):
    return run(schema.fetch("SELECT status, attempt, dispatched_attempt FROM execution_steps WHERE step_id = $1",
                            step_id))[0]


def _ledger_rows(schema, run, key):
    return run(schema.fetch("SELECT tenant_id, kernel_op_id, result FROM idempotency_ledger WHERE idempotency_key = $1",
                            key))


# --- retries stay RUNNING, one key per step (suites 6, 7) -------------------------------------------------------------

def test_a_read_is_retried_on_the_same_key_and_the_step_stays_running(db_schema, run):
    tenant = "t-retry-read"
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation="R"))
    mock = _mock("fail_500_then_success", n=2)
    logged = run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE entity_type = 'step'"))
    out = run(_attempts(db_schema, _step(tenant, res, mutation="R"), holder, _deps(db_schema, mock)))
    assert (out.kind, out.attempts, out.cached) == ("success", 3, False)
    keys = {m.idempotency_key for m in mock.calls}
    assert keys == {f"req-{tenant}:s0"} and [m.attempt_id for m in mock.calls] == ["att-0-1", "att-0-2", "att-0-3"]
    assert len({m.provider_call_id for m in mock.calls}) == 3 and mock.side_effects(f"req-{tenant}:s0") == 1
    row = _row(db_schema, run, tenant, f"e-{tenant}:s0")
    assert (row["status"], row["attempt"], row["dispatched_attempt"]) == ("running", 3, 3)
    assert run(db_schema.fetchval("SELECT count(*) FROM state_transitions WHERE entity_type = 'step'")) == logged


@pytest.mark.parametrize("mutation,retry_safety,behaviour,calls,kind", [
    ("W", "safe", "fail_500_then_success", 2, "success"),
    ("W", "never", "fail_500_then_success", 1, "failure"),
    ("D", "idempotent", "rate_limit_429", 2, "success"),
    ("D", "never", "rate_limit_429", 1, "failure"),
    ("IRREVERSIBLE", "safe", "fail_500_then_success", 1, "failure"),
    ("IRREVERSIBLE", "idempotent", "connect_refused", 1, "failure"),
    ("R", "safe", "auth_401", 1, "failure"),
])
def test_retry_matrix_through_the_runner(db_schema, run, mutation, retry_safety, behaviour, calls, kind):
    tenant = f"t-mx-{mutation}-{retry_safety}-{behaviour}"[:60]
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation=mutation))
    mock = _mock(behaviour, n=1)
    out = run(_attempts(db_schema, _step(tenant, res, mutation=mutation, retry_safety=retry_safety), holder,
                        _deps(db_schema, mock)))
    assert (out.kind, len(mock.calls)) == (kind, calls)


def test_retries_exhausted_leave_no_ledger_row_and_a_client_error_leaves_one(db_schema, run):
    tenant = "t-exhaust"
    holder, res = run(_seed(db_schema, tenant, steps=2, mutation="R"))
    out = run(_attempts(db_schema, _step(tenant, res, 0, mutation="R"), holder,
                        _deps(db_schema, _mock("fail_500_then_success", n=9))))
    assert (out.kind, out.attempts) == ("failure", 3) and _ledger_rows(db_schema, run, f"req-{tenant}:s0") == []
    out = run(_attempts(db_schema, _step(tenant, res, 1, mutation="R"), holder, _deps(db_schema, _mock("auth_401"))))
    assert out.kind == "failure" and len(_ledger_rows(db_schema, run, f"req-{tenant}:s1")) == 1


def test_two_steps_get_two_keys_and_one_side_effect_each(db_schema, run):
    tenant = "t-two-keys"
    holder, res = run(_seed(db_schema, tenant, steps=2))
    mock = _mock()
    deps = _deps(db_schema, mock)
    for i in (0, 1):
        assert run(_attempts(db_schema, _step(tenant, res, i), holder, deps)).kind == "success"
    assert [m.idempotency_key for m in mock.calls] == [f"req-{tenant}:s0", f"req-{tenant}:s1"]
    assert (mock.side_effects(f"req-{tenant}:s0"), mock.side_effects(f"req-{tenant}:s1")) == (1, 1)
    assert [r["kernel_op_id"] for r in _ledger_rows(db_schema, run, f"req-{tenant}:s0")] == ["mock.op"]


def test_connect_refused_is_retried_and_opens_no_episode(db_schema, run):
    tenant = "t-connect"
    holder, res = run(_seed(db_schema, tenant, steps=1))
    mock = _mock("connect_refused", n=1)
    out = run(_attempts(db_schema, _step(tenant, res), holder, _deps(db_schema, mock)))
    assert (out.kind, out.attempts, mock.side_effects(f"req-{tenant}:s0")) == ("success", 2, 1)
    assert run(db_schema.fetchval("SELECT count(*) FROM step_reconciliations WHERE tenant_id = $1", tenant)) == 0


def test_a_timeout_is_uncertain_never_retried_and_leaves_no_row(db_schema, run):
    tenant = "t-timeout"
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation="R"))
    mock = _mock("timeout_executed")
    out = run(_attempts(db_schema, _step(tenant, res, mutation="R", timeout_s=0.05), holder, _deps(db_schema, mock)))
    assert (out.kind, out.reason, len(mock.calls)) == ("uncertain", "timeout", 1)
    assert _ledger_rows(db_schema, run, f"req-{tenant}:s0") == []


# --- dispatch marker, live check, bulkhead during backoff (C35, C23, C37) --------------------------------------------

def test_the_dispatch_marker_is_committed_before_every_call(db_schema, run):
    from adapters.runtime.mock_adapter import MockAdapter
    tenant = "t-marker"
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation="R"))
    seen = []

    class Watching(MockAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            seen.append(await db_schema.fetchval("SELECT dispatched_attempt FROM execution_steps WHERE step_id = $1",
                                                 f"e-{tenant}:s0"))
            return await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)

    mock = Watching(Credentials())
    mock.program("mock.op", "fail_500_then_success", n=2)
    run(_attempts(db_schema, _step(tenant, res, mutation="R"), holder, _deps(db_schema, mock)))
    assert seen == [1, 2, 3]


def test_each_attempt_is_a_ledger_event_and_every_provider_call_follows_its_marker(db_schema, run):
    """C24 and I16: step_attempt (written after the marker commits) precedes ProviderCalled of the same attempt."""
    tenant = "t-events"
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation="R"))
    mock, events = _mock("fail_500_then_success", n=1), Events()
    run(_attempts(db_schema, _step(tenant, res, mutation="R"), holder, _deps(db_schema, mock, events=events)))
    assert [(k, p["attempt_id"]) for k, p in events.events] == [
        ("step_attempt", "att-0-1"), ("ProviderCalled", "att-0-1"), ("ProviderReturned", "att-0-1"),
        ("step_attempt", "att-0-2"), ("ProviderCalled", "att-0-2"), ("ProviderReturned", "att-0-2")]
    called = [p["provider_call_id"] for k, p in events.events if k == "ProviderCalled"]
    assert called == [m.provider_call_id for m in mock.calls]
    assert [p["status"] for k, p in events.events if k == "ProviderReturned"] == ["error", "ok"]


def test_a_call_the_guard_refused_is_not_a_provider_call(db_schema, run):
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    tenant = "t-refused"
    holder, res = run(_seed(db_schema, tenant, steps=1))
    mock, events = _mock(), Events()
    deps = _deps(db_schema, mock, events=events)
    breaker = InProcessCircuitBreaker(1, 60.0)
    breaker.record_failure("mockp")
    deps = dataclasses.replace(deps, guard=_with_breaker(deps.guard, mock, breaker))
    out = run(_attempts(db_schema, _step(tenant, res), holder, deps))
    assert (out.kind, out.result.error_class, mock.calls) == ("failure", "circuit_open", [])
    assert [k for k, _ in events.events] == ["step_attempt"]


def _with_breaker(guard, adapter, breaker):
    from adapters.runtime.reliability import (InProcessBilling, InProcessBulkhead, InProcessHealthMonitor,
                                              InProcessRetryStormGuard)
    from engine.stages.s12_execute.reliability import ReliabilityGuard, TimeoutManager

    class Pass:
        async def check(self, call):
            return None
    return ReliabilityGuard(adapter, bulkhead=InProcessBulkhead(4), breaker=breaker, budget=Pass(),
                            retry_storm=InProcessRetryStormGuard(100, 60.0), timeouts=TimeoutManager(),
                            health=InProcessHealthMonitor(), billing=InProcessBilling(), probe_timeout_s=0.5)


def test_live_authorization_runs_before_every_call(db_schema, run):
    tenant = "t-live"
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation="R"))
    mock, live = _mock("fail_500_then_success", n=5), Live(revoke_on=2, reason="kill_switch_engaged")
    out = run(_attempts(db_schema, _step(tenant, res, mutation="R"), holder, _deps(db_schema, mock, live=live)))
    assert (out.kind, out.reason, len(mock.calls), live.checks) == ("revoked", "kill_switch_engaged", 1, 2)


def test_the_bulkhead_slot_is_free_during_backoff(db_schema, run):
    from adapters.runtime.reliability import InProcessBulkhead
    tenant = "t-backoff"
    holder, res = run(_seed(db_schema, tenant, steps=1, mutation="R"))
    bulkhead, during = InProcessBulkhead(1), []

    async def sleep(seconds):
        during.append((seconds, bulkhead.in_use("mockp")))

    out = run(_attempts(db_schema, _step(tenant, res, mutation="R"), holder,
                        _deps(db_schema, _mock("fail_500_then_success", n=2), bulkhead=bulkhead, sleep=sleep)))
    assert out.kind == "success" and len(during) == 2 and all(s > 0 and used == 0 for s, used in during)


# --- the ledger: hits, expiry, conflicts, fencing (C17, C34, suite 6) -------------------------------------------------

def test_a_cached_success_makes_no_call_and_is_a_ledger_event(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    tenant = "t-hit-ok"
    holder, res = run(_seed(db_schema, tenant, steps=1))
    run(PostgresIdempotencyLedger(db_schema.database()).store(
        holder, idempotency_key=f"req-{tenant}:s0", kernel_op_id="mock.op", result=AdapterResult("ok", data={"id": 7}),
        ttl_s=3600))
    mock, events = _mock(), Events()
    out = run(_attempts(db_schema, _step(tenant, res), holder, _deps(db_schema, mock, events=events)))
    assert (out.kind, out.cached, out.result.data, mock.calls) == ("success", True, {"id": 7}, [])
    assert events.events == [("idempotency_hit", {"step_id": f"e-{tenant}:s0", "attempt_id": "att-0-1",
                                                  "kind": "success"})]
    assert _row(db_schema, run, tenant, f"e-{tenant}:s0")["dispatched_attempt"] is None


def test_a_cached_failure_makes_no_call(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    tenant = "t-hit-fail"
    holder, res = run(_seed(db_schema, tenant, steps=1))
    run(PostgresIdempotencyLedger(db_schema.database()).store(
        holder, idempotency_key=f"req-{tenant}:s0", kernel_op_id="mock.op",
        result=AdapterResult("error", False, "client_error"), ttl_s=3600))
    mock = _mock()
    out = run(_attempts(db_schema, _step(tenant, res), holder, _deps(db_schema, mock)))
    assert (out.kind, out.cached, out.result.error_class, mock.calls) == ("failure", True, "client_error", [])


def test_an_expired_record_is_no_record_and_never_authorises_a_blind_call(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    tenant = "t-expired"
    holder, res = run(_seed(db_schema, tenant, steps=1))
    ledger = PostgresIdempotencyLedger(db_schema.database())
    run(ledger.store(holder, idempotency_key=f"req-{tenant}:s0", kernel_op_id="mock.op", result=AdapterResult("ok"),
                     ttl_s=3600))
    run(db_schema.execute("UPDATE idempotency_ledger SET expires_at = now() - interval '1 second'"
                          " WHERE idempotency_key = $1", f"req-{tenant}:s0"))
    assert run(ledger.lookup(tenant, f"req-{tenant}:s0")) is None
    run(db_schema.execute("UPDATE execution_steps SET attempt = 1, dispatched_attempt = 1 WHERE step_id = $1",
                          f"e-{tenant}:s0"))                 # attempt 1 was dispatched before (e.g. before a crash)
    mock = _mock()
    out = run(_attempts(db_schema, _step(tenant, res), holder, _deps(db_schema, mock)))
    assert (out.kind, out.reason, mock.calls) == ("uncertain", "dispatched_without_record", [])


def test_lookups_are_tenant_scoped(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult
    a, b = "t-scope-a", "t-scope-b"
    holder_a, _ = run(_seed(db_schema, a, steps=1))
    run(_seed(db_schema, b, steps=1))
    ledger = PostgresIdempotencyLedger(db_schema.database())
    run(ledger.store(holder_a, idempotency_key="shared-key", kernel_op_id="mock.op", result=AdapterResult("ok"),
                     ttl_s=3600))
    assert run(ledger.lookup(a, "shared-key")) is not None and run(ledger.lookup(b, "shared-key")) is None


def test_storing_the_same_result_twice_is_a_hit_and_a_different_one_is_a_conflict(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.idempotency import IdempotencyConflict
    from contracts.step_execution import AdapterResult
    a, b = "t-conflict-a", "t-conflict-b"
    holder_a, _ = run(_seed(db_schema, a, steps=1))
    holder_b, _ = run(_seed(db_schema, b, steps=1))
    ledger = PostgresIdempotencyLedger(db_schema.database())
    store = dict(idempotency_key="k-conflict", kernel_op_id="mock.op", ttl_s=3600)
    run(ledger.store(holder_a, result=AdapterResult("ok"), **store))
    run(ledger.store(holder_a, result=AdapterResult("ok", data={"again": True}), **store))          # same kind: a hit
    with pytest.raises(IdempotencyConflict):
        run(ledger.store(holder_a, result=AdapterResult("error", False, "client_error"), **store))  # other kind
    with pytest.raises(IdempotencyConflict):
        run(ledger.store(holder_a, idempotency_key="k-conflict", kernel_op_id="other.op", result=AdapterResult("ok"),
                         ttl_s=3600))
    with pytest.raises(IdempotencyConflict):
        run(ledger.store(holder_b, result=AdapterResult("ok"), **store))                            # another tenant
    assert len(_ledger_rows(db_schema, run, "k-conflict")) == 1


def test_a_fenced_out_runtime_can_neither_mark_nor_record(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.step_execution import AdapterResult, FencedOut
    tenant = "t-fenced"
    holder, res = run(_seed(db_schema, tenant, steps=2))
    stale = dataclasses.replace(holder, fence_token=TOKEN - 1)

    async def race():
        return await asyncio.gather(
            PostgresIdempotencyLedger(db_schema.database()).store(
                holder, idempotency_key=f"req-{tenant}:s0", kernel_op_id="mock.op", result=AdapterResult("ok"),
                ttl_s=3600),
            PostgresIdempotencyLedger(db_schema.database()).store(
                stale, idempotency_key=f"req-{tenant}:s0", kernel_op_id="mock.op", result=AdapterResult("ok"),
                ttl_s=3600), return_exceptions=True)

    results = run(race())
    assert results[0] is None and isinstance(results[1], FencedOut)
    assert len(_ledger_rows(db_schema, run, f"req-{tenant}:s0")) == 1
    mock = _mock()
    with pytest.raises(FencedOut):                           # s1 has no ledger row: the marker write is fenced out
        run(_attempts(db_schema, _step(tenant, res, 1), stale, _deps(db_schema, mock)))
    assert mock.calls == []


def test_a_cached_record_of_another_operation_is_a_conflict_never_a_hit(db_schema, run):
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from contracts.idempotency import IdempotencyConflict
    from contracts.step_execution import AdapterResult
    tenant = "t-hit-other-op"
    holder, res = run(_seed(db_schema, tenant, steps=1))
    run(PostgresIdempotencyLedger(db_schema.database()).store(
        holder, idempotency_key=f"req-{tenant}:s0", kernel_op_id="other.op", result=AdapterResult("ok"), ttl_s=3600))
    mock, events = _mock(), Events()
    with pytest.raises(IdempotencyConflict):
        run(_attempts(db_schema, _step(tenant, res), holder, _deps(db_schema, mock, events=events)))
    assert mock.calls == [] and events.events == []
    assert _row(db_schema, run, tenant, f"e-{tenant}:s0")["dispatched_attempt"] is None


def test_a_result_whose_ledger_write_is_fenced_out_is_discarded(db_schema, run):
    from adapters.runtime.mock_adapter import MockAdapter
    from contracts.step_execution import FencedOut
    tenant = "t-fenced-mid-call"
    holder, res = run(_seed(db_schema, tenant, steps=1))

    class TakenOverDuringTheCall(MockAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            result = await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)
            await db_schema.execute("UPDATE execution_ownership SET runtime_instance_id = 'runtime-B',"
                                    " fencing_token = fencing_token + 1 WHERE execution_id = $1", holder.execution_id)
            return result

    mock = TakenOverDuringTheCall(Credentials())
    mock.program("mock.op", "success")
    with pytest.raises(FencedOut):
        run(_attempts(db_schema, _step(tenant, res), holder, _deps(db_schema, mock)))
    key = f"req-{tenant}:s0"
    assert mock.side_effects(key) == 1 and _ledger_rows(db_schema, run, key) == []


def test_a_budget_state_error_propagates_before_any_provider_call(db_schema, run):
    from contracts.adapter_interface import BudgetStateError
    tenant = "t-budget-state"
    holder, res = run(_seed(db_schema, tenant, steps=2))
    wrong = dataclasses.replace(_step(tenant, res), reservation_id=res[f"e-{tenant}:s1"])   # another step's
    mock, events = _mock(), Events()
    with pytest.raises(BudgetStateError):
        run(_attempts(db_schema, wrong, holder, _deps(db_schema, mock, events=events)))
    assert mock.calls == [] and _ledger_rows(db_schema, run, f"req-{tenant}:s0") == []
    assert [k for k, _ in events.events if k.startswith("Provider")] == []


def test_every_move_on_these_paths_is_legal(db_schema, run):
    run(assert_system_invariants(db_schema))
