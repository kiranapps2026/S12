"""M14 golden — live revalidation and cancellation (gate commit H part 3). ★ Owner-pinned.

Gate v10: C23 (LiveAuthorizationCheck at the start of every step and before every adapter call; read-only; fail closed;
on REVOKED no new adapter call, an in-flight or uncertain step is resolved first, the remaining PENDING steps and the
run CANCELLED with ``kill_switch_engaged`` or ``authorization_revoked``, ledger event ``authorization_revoked``), C30
(capability active), C35 (binding and credential validity: ``binding_invalid``, ``credential_invalid``; a step whose
current attempt was never dispatched follows the NOT_EXECUTED path with evidence ``no_dispatch_marker``; provider
unavailability is not a revocation), C16 (cancellation requested by the run's own user and tenant, checked before each
step, never interrupts an in-flight call, applied after uncertainty is resolved; DEAD_LETTER takes precedence), C15,
C39 (a pause set while a run is RUNNING cancels no step and revokes no held lease), suites 16a and 16b; invariant I14.
Rulings: CONF-030 (credential validity from ``CredentialProvider.credential_valid``), CONF-031 (the event records the
reason; the failing check is logged), CONF-032 (gate 8 is a DELAY: a persistent outage ends as ``admission_exhausted``, never a cancelled run).

Interface this file fixes (on top of M12/M13):
  * ``adapters.postgres.live_authorization.PostgresLiveAuthorization(scopes, *, database, credentials)``: the frozen
    ``LiveAuthorization`` port. ``check(...)`` → None, or ``Revoked`` with ``kill_switch_engaged`` (system or tenant
    kill switch), ``authorization_revoked`` (user, tenant, connection, grant, resource scope, capability retired =
    ``capabilities.truth_state`` DEPRECATED, or anything unreadable), ``binding_invalid`` (the frozen binding's row
    missing or inactive), ``credential_invalid`` (``await credentials.credential_valid(tenant_id, connection_id)`` is
    not True). It writes nothing.
  * ``contracts.adapter_interface.CredentialProvider`` gains ``async credential_valid(tenant_id, connection_id) ->
    bool``.
  * ``adapters.postgres.cancellation.PostgresCancellation(database)``: ``async request(tenant_id, execution_id,
    user_id) -> bool`` — records ``execution_runs.cancel_requested_at`` for the run's own user and tenant only (no
    lease needed) while the run is not terminal; a repeated request is True and keeps the first time; False
    otherwise (another user or tenant, no such run, a finished run).
  * The loop checks the cancellation flag and ``live`` before each step; ``run_attempts`` checks ``live`` before each
    call. REVOKED at a step's start: that step and every remaining PENDING step CANCELLED with the reason, the run
    CANCELLED. REVOKED before an attempt: the step goes ``running → pending_probe (execution_uncertain)``, an
    EXECUTION episode is opened and closed NOT_EXECUTED (evidence ``no_dispatch_marker``), ``pending_probe → pending
    (no_dispatch_marker)`` with the budget released, then CANCELLED with the reason. Cancellation: the same with
    ``user_cancelled``, applied only once no step is RUNNING or PENDING_PROBE. A DEAD_LETTER step wins over both: the
    run is consolidated, not CANCELLED.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.fixtures.certified import certified_state, fresh
from tests_golden.s12.M12_loop import CHAIN3, Recorder, _admit, _deps, _events, _loop, _moves, _order, _ops, _steps


def _state(tenant, suffix):
    """A certified chain with its own user, workspace and connection: live checks read those rows, and they are keyed
    globally, so tenants must not share them."""
    state = certified_state(tenant_id=tenant, chain=CHAIN3, user_id=f"u-{tenant}", workspace_id=f"ws-{tenant}",
                            connection_id=f"conn-{tenant}")
    return fresh(state, f"{tenant}-{suffix}")


class Creds:
    def __init__(self, valid=True):
        self.valid = valid

    async def credential(self, tenant_id, connection_id):
        return "secret"

    async def credential_valid(self, tenant_id, connection_id):
        return self.valid


class Live:
    """A programmable LiveAuthorization: Revoked(reason) from check number ``revoke_from`` on."""
    def __init__(self, revoke_from=None, reason="authorization_revoked"):
        self.checks, self.revoke_from, self.reason = 0, revoke_from, reason

    async def check(self, **kw):
        from contracts.step_execution import Revoked
        self.checks += 1
        return Revoked(self.reason) if self.revoke_from is not None and self.checks >= self.revoke_from else None


def _mock(**programs):
    from tests_golden.s12.M12_loop import _mock as mock
    return mock(**programs)


def _live_deps(schema, mock, live=None, **settings):
    from adapters.postgres.reconciliation import PostgresEpisodes
    deps = _deps(schema, mock, **{"step_timeout_s": 0.1, "probe_backoff_s": 0.001, **settings})
    return dataclasses.replace(deps, episodes=PostgresEpisodes(schema.database()), live=live or deps.live)


def _calls_for(mock, state, sid):
    return [m for m in mock.calls if m.idempotency_key == f"{state.execution_context.request_id}:{sid}"]


# --- LiveAuthorizationCheck against live state (C23, C30, C35; suite 16b) ---------------------------------------------

async def _seed_live(schema, state):
    ctx = state.execution_context
    await schema.execute("INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id, status) VALUES"
                         " ($1, $2, $3, $4, 'active') ON CONFLICT DO NOTHING", ctx.connection_id, ctx.tenant_id,
                         ctx.user_id, ctx.workspace_id, tenant=ctx.tenant_id)
    await schema.execute("INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role, is_active)"
                         " VALUES ($1, $2, $3, $4, 'member', true) ON CONFLICT DO NOTHING", f"m-{ctx.tenant_id}",
                         ctx.tenant_id, ctx.user_id, ctx.workspace_id, tenant=ctx.tenant_id)
    for b in state.frozen_bindings:
        await schema.execute("INSERT INTO capability_grants (capability_grant_id, tenant_id, workspace_id, user_id,"
                             " capability_id, is_active) VALUES ($1, $2, $3, $4, $5, true) ON CONFLICT DO NOTHING",
                             f"g-{ctx.tenant_id}-{b.capability_id}", ctx.tenant_id, ctx.workspace_id, ctx.user_id,
                             b.capability_id, tenant=ctx.tenant_id)


def _live_check(schema, credentials=None):
    from adapters.postgres.live_authorization import PostgresLiveAuthorization
    from adapters.postgres.scope import PostgresRunScopes
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    db = schema.database()
    return PostgresLiveAuthorization(PostgresRunScopes(db, InProcessCircuitBreaker()), database=db,
                                     credentials=credentials or Creds())


def _ask(schema, run, state, binding=None, credentials=None):
    ctx = state.execution_context
    return run(_live_check(schema, credentials).check(
        tenant_id=ctx.tenant_id, workspace_id=ctx.workspace_id, user_id=ctx.user_id, connection_id=ctx.connection_id,
        binding=binding or state.frozen_bindings[0]))


REVOCATIONS = [
    ("kill switch (system)", "UPDATE system_settings SET kill_switch_engaged = true", "kill_switch_engaged"),
    ("kill switch (tenant)", "UPDATE tenants SET kill_switch_engaged = true WHERE tenant_id = $1", "kill_switch_engaged"),
    ("user deactivated", "UPDATE users SET status = 'deactivated' WHERE tenant_id = $1", "authorization_revoked"),
    ("tenant suspended", "UPDATE tenants SET status = 'suspended' WHERE tenant_id = $1", "authorization_revoked"),
    ("connection deleted", "UPDATE connections SET status = 'deleted' WHERE tenant_id = $1", "authorization_revoked"),
    ("grant revoked", "UPDATE capability_grants SET is_active = false WHERE tenant_id = $1", "authorization_revoked"),
    ("capability retired", "UPDATE capabilities SET truth_state = 'DEPRECATED' WHERE capability_id IN (SELECT"
                           " capability_id FROM capability_grants WHERE tenant_id = $1)", "authorization_revoked"),
    ("binding disabled", "UPDATE bindings SET is_active = false WHERE capability_id IN (SELECT capability_id FROM"
                         " capability_grants WHERE tenant_id = $1)", "binding_invalid"),
]


@pytest.mark.parametrize("name,sql,reason", REVOCATIONS, ids=[r[0] for r in REVOCATIONS])
def test_each_revocation_is_seen_with_its_reason(db_schema, run, name, sql, reason):
    tenant = f"golden-live-{name.replace(' ', '-').replace('(', '').replace(')', '')}"
    state = _state(tenant, "live")
    _admit(db_schema, run, state)
    run(_seed_live(db_schema, state))
    assert _ask(db_schema, run, state) is None                               # all live state allows the run
    run(db_schema.execute(sql, *([tenant] if "$1" in sql else [])))
    try:
        revoked = _ask(db_schema, run, state)
        assert revoked is not None and revoked.reason == reason
    finally:
        if "system_settings" in sql:
            run(db_schema.execute("UPDATE system_settings SET kill_switch_engaged = false"))
        if "capabilities" in sql:
            run(db_schema.execute("UPDATE capabilities SET truth_state = 'PRODUCTION_ENABLED'"))
        if "bindings" in sql:
            run(db_schema.execute("UPDATE bindings SET is_active = true"))


def test_an_invalid_credential_is_credential_invalid(db_schema, run):
    state = _state("golden-live-credential", "cred")
    _admit(db_schema, run, state)
    run(_seed_live(db_schema, state))
    assert _ask(db_schema, run, state, credentials=Creds(valid=False)).reason == "credential_invalid"


def test_unreadable_live_state_fails_closed(db_schema, run):
    state = _state("golden-live-unreadable", "unreadable")
    _admit(db_schema, run, state)
    run(_seed_live(db_schema, state))

    class Broken(Creds):
        async def credential_valid(self, tenant_id, connection_id):
            raise ConnectionError("vault down")

    assert _ask(db_schema, run, state, credentials=Broken()).reason in ("authorization_revoked", "credential_invalid")
    ctx = state.execution_context
    gone = run(_live_check(db_schema).check(tenant_id="golden-no-such-tenant", workspace_id=ctx.workspace_id,
                                            user_id=ctx.user_id, connection_id=ctx.connection_id,
                                            binding=state.frozen_bindings[0]))
    assert gone is not None and gone.reason == "authorization_revoked"


def test_a_provider_outage_is_not_a_revocation(db_schema, run):
    """C35: ADAPTER_UNAVAILABLE / PROVIDER_UNAVAILABLE are handled by the breaker and admission, never revoked."""
    from adapters.postgres.live_authorization import PostgresLiveAuthorization
    from adapters.postgres.scope import PostgresRunScopes
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    state = _state("golden-live-outage", "outage")
    _admit(db_schema, run, state)
    run(_seed_live(db_schema, state))
    breaker = InProcessCircuitBreaker(1, 60.0)
    for b in state.frozen_bindings:
        breaker.record_failure(b.provider)
    db = db_schema.database()
    live = PostgresLiveAuthorization(PostgresRunScopes(db, breaker), database=db, credentials=Creds())
    ctx = state.execution_context
    assert run(live.check(tenant_id=ctx.tenant_id, workspace_id=ctx.workspace_id, user_id=ctx.user_id,
                          connection_id=ctx.connection_id, binding=state.frozen_bindings[0])) is None


def test_a_persistent_provider_outage_ends_as_admission_exhausted_never_cancelled(db_schema, run):
    """CONF-032: an open circuit at admission is a DELAY; bounded, it ends as ``admission_exhausted`` (consolidation),
    never as a cancelled run."""
    from engine.stages.s12_execute.admission_control import AdmissionSnapshot
    from tests_golden.s12.M12_loop import PASSING
    state = _state("golden-live-outage-loop", "outageloop")
    tenant, execution = _admit(db_schema, run, state)

    async def circuit_open(tenant_id, execution_id, plan_step_id):
        return AdmissionSnapshot(**{**PASSING, "circuit_open": True})

    consolidate = Recorder()
    deps = dataclasses.replace(_live_deps(db_schema, _mock(), admission_max_attempts=2), admission=circuit_open,
                               consolidate=consolidate)
    result = _loop(db_schema, run, deps, tenant, execution)
    assert all(result.steps[sid] == ("cancelled", "admission_exhausted") for sid in _order(state))
    assert result.run_status == "running" and len(consolidate.calls) == 1
    assert "cancelled" not in [to for _, to, _ in _moves(db_schema, run, "run", execution)]


def test_the_live_check_writes_nothing(db_schema, run):
    state = _state("golden-live-readonly", "readonly")
    _admit(db_schema, run, state)
    run(_seed_live(db_schema, state))
    tables = [r["t"] for r in run(db_schema.fetch(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = $1 AND table_type = 'BASE TABLE'",
        db_schema.name))]

    def counts():
        return {t: run(db_schema.fetchval(f'SELECT count(*) FROM "{t}"')) for t in tables}

    before = counts()
    for _ in range(3):
        _ask(db_schema, run, state)
    run(db_schema.execute("UPDATE users SET status = 'deactivated' WHERE tenant_id = $1",
                          state.execution_context.tenant_id))
    _ask(db_schema, run, state)
    assert counts() == before


# --- the loop on REVOKED (C23, suite 16b) ----------------------------------------------------------------------------

@pytest.mark.parametrize("reason", ["kill_switch_engaged", "authorization_revoked", "binding_invalid",
                                    "credential_invalid"])
def test_revoked_between_steps_cancels_the_rest_and_the_run(db_schema, run, reason):
    state = _state(f"golden-rev-between-{reason}"[:60], "between")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mock()
    live = Live(revoke_from=3, reason=reason)            # step 1: start + before its call; step 2 start is REVOKED
    result = _loop(db_schema, run, _live_deps(db_schema, mock, live), tenant, execution)
    assert result.steps[first] == ("completed", None)
    assert all(result.steps[sid] == ("cancelled", reason) for sid in rest)
    assert (result.run_status, result.reason) == ("cancelled", reason)
    assert all(not _calls_for(mock, state, sid) for sid in rest)
    assert _moves(db_schema, run, "run", execution)[-1] == ("running", "cancelled", reason)
    revoked = _events(db_schema, run, execution, "authorization_revoked")
    assert len(revoked) == 1
    run(assert_system_invariants(db_schema))                              # includes I14


def test_revoked_before_a_retry_makes_no_further_call(db_schema, run):
    state = _state("golden-rev-retry", "retry")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first, *rest = _order(state)
    mock = _mock(**{_ops(state)[first]: {"call": "fail_500_then_success", "n": 5}})
    live = Live(revoke_from=3)                           # start, attempt 1, then REVOKED before attempt 2
    result = _loop(db_schema, run, _live_deps(db_schema, mock, live), tenant, execution)
    assert len(_calls_for(mock, state, first)) == 1
    assert result.steps[first] == ("cancelled", "authorization_revoked")
    step = _steps(db_schema, run, execution)[first]
    assert _moves(db_schema, run, "step", step["step_id"])[-3:] == [
        ("running", "pending_probe", "execution_uncertain"), ("pending_probe", "pending", "no_dispatch_marker"),
        ("pending", "cancelled", "authorization_revoked")]
    assert step["budget"] == "released"
    episodes = run(db_schema.fetch("SELECT outcome, evidence FROM step_reconciliations WHERE step_id = $1",
                                   step["step_id"]))
    assert [r["outcome"] for r in episodes] == ["NOT_EXECUTED"] and "no_dispatch_marker" in str(episodes[0]["evidence"])
    assert result.run_status == "cancelled"
    run(assert_system_invariants(db_schema))


def test_an_uncertain_step_is_resolved_before_the_revocation_applies(db_schema, run):
    state = _state("golden-rev-uncertain", "uncertain")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mock(**{_ops(state)[first]: {"call": "timeout_executed"}})
    live = Live(revoke_from=3)                           # REVOKED from after step 1's call: the probe still runs
    result = _loop(db_schema, run, _live_deps(db_schema, mock, live), tenant, execution)
    assert result.steps[first] == ("completed", None) and len(mock.probes) == 1
    assert all(result.steps[sid] == ("cancelled", "authorization_revoked") for sid in rest)
    assert result.run_status == "cancelled" and len(mock.calls) == 1
    run(assert_system_invariants(db_schema))


def test_revoked_at_the_first_step_makes_no_call_at_all(db_schema, run):
    state = _state("golden-rev-first", "first")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mock()
    result = _loop(db_schema, run, _live_deps(db_schema, mock, Live(revoke_from=1, reason="kill_switch_engaged")),
                   tenant, execution)
    assert all(result.steps[sid] == ("cancelled", "kill_switch_engaged") for sid in _order(state))
    assert mock.calls == [] and result.run_status == "cancelled"
    assert run(db_schema.fetchval("SELECT count(*) FROM budget_reservations WHERE execution_id = $1", execution)) == 0
    run(assert_system_invariants(db_schema))


# --- cancellation (C16, suite 16a) -----------------------------------------------------------------------------------

def _cancel(schema, run, tenant, execution, user):
    from adapters.postgres.cancellation import PostgresCancellation
    return run(PostgresCancellation(schema.database()).request(tenant, execution, user))


def test_cancellation_before_start_runs_nothing(db_schema, run):
    state = _state("golden-cancel-before", "before")
    tenant, execution = _admit(db_schema, run, state)
    assert _cancel(db_schema, run, tenant, execution, state.execution_context.user_id) is True
    mock = _mock()
    result = _loop(db_schema, run, _live_deps(db_schema, mock), tenant, execution)
    assert all(result.steps[sid] == ("cancelled", "user_cancelled") for sid in _order(state))
    assert (result.run_status, mock.calls) == ("cancelled", [])
    assert _moves(db_schema, run, "run", execution)[-1] == ("running", "cancelled", "user_cancelled")


def _cancelling_mock(schema, state, execution, op, **program):
    """A mock whose call on ``op`` requests cancellation while the call is in flight."""
    from adapters.runtime.mock_adapter import MockAdapter
    from adapters.postgres.cancellation import PostgresCancellation
    from tests_golden.s12.M12_loop import Credentials
    ctx = state.execution_context

    class Cancelling(MockAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            if kernel_op_id == op:
                await PostgresCancellation(schema.database()).request(ctx.tenant_id, execution, ctx.user_id)
            return await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)

    mock = Cancelling(Credentials())
    mock.program(op, **program)
    return mock


def test_cancellation_during_an_in_flight_step_lets_it_finish(db_schema, run):
    state = _state("golden-cancel-inflight", "inflight")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _cancelling_mock(db_schema, state, execution, _ops(state)[first], call="success")
    result = _loop(db_schema, run, _live_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("completed", None)
    assert all(result.steps[sid] == ("cancelled", "user_cancelled") for sid in rest)
    assert result.run_status == "cancelled"
    assert _steps(db_schema, run, execution)[first]["budget"] == "committed"
    run(assert_system_invariants(db_schema))


def test_cancellation_while_a_step_is_uncertain_applies_after_the_probe(db_schema, run):
    state = _state("golden-cancel-probe", "probe")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _cancelling_mock(db_schema, state, execution, _ops(state)[first], call="timeout_executed")
    result = _loop(db_schema, run, _live_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("completed", None) and len(mock.probes) == 1
    assert all(result.steps[sid] == ("cancelled", "user_cancelled") for sid in rest)
    assert result.run_status == "cancelled"
    run(assert_system_invariants(db_schema))


def test_a_dead_letter_takes_precedence_over_cancellation(db_schema, run):
    state = _state("golden-cancel-dl", "dl")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _cancelling_mock(db_schema, state, execution, _ops(state)[first], call="timeout_executed",
                            probe="inconclusive")
    consolidate = Recorder()
    deps = dataclasses.replace(_live_deps(db_schema, mock), consolidate=consolidate)
    result = _loop(db_schema, run, deps, tenant, execution)
    assert result.steps[first] == ("dead_letter", None)
    assert all(result.steps[sid] == ("cancelled", "run_dead_lettered") for sid in rest)
    assert result.run_status != "cancelled" and len(consolidate.calls) == 1
    assert ("running", "cancelled", "user_cancelled") not in _moves(db_schema, run, "run", execution)
    run(assert_system_invariants(db_schema))


def test_only_the_runs_own_user_and_tenant_can_cancel(db_schema, run):
    state = _state("golden-cancel-who", "who")
    tenant, execution = _admit(db_schema, run, state)
    run(db_schema.execute("INSERT INTO users (user_id, tenant_id, status) VALUES ('golden-intruder', $1, 'active')",
                          tenant, tenant=tenant))
    assert _cancel(db_schema, run, tenant, execution, "golden-intruder") is False
    assert _cancel(db_schema, run, "golden-other-tenant", execution, state.execution_context.user_id) is False
    assert _cancel(db_schema, run, tenant, "golden-no-such-run", state.execution_context.user_id) is False
    assert run(db_schema.fetchval("SELECT cancel_requested_at FROM execution_runs WHERE execution_id = $1",
                                  execution)) is None


def test_a_repeated_cancel_request_is_idempotent_and_a_finished_run_cannot_be_cancelled(db_schema, run):
    state = _state("golden-cancel-twice", "twice")
    tenant, execution = _admit(db_schema, run, state)
    user = state.execution_context.user_id
    assert _cancel(db_schema, run, tenant, execution, user) is True
    first = run(db_schema.fetchval("SELECT cancel_requested_at FROM execution_runs WHERE execution_id = $1",
                                   execution))
    assert _cancel(db_schema, run, tenant, execution, user) is True
    assert run(db_schema.fetchval("SELECT cancel_requested_at FROM execution_runs WHERE execution_id = $1",
                                  execution)) == first                          # the first request's time is kept
    done = _state("golden-cancel-done", "done")
    done_tenant, done_execution = _admit(db_schema, run, done)
    _loop(db_schema, run, _live_deps(db_schema, _mock()), done_tenant, done_execution)
    run(db_schema.execute("UPDATE execution_runs SET status = 'completed' WHERE execution_id = $1", done_execution))
    assert _cancel(db_schema, run, done_tenant, done_execution, done.execution_context.user_id) is False
    assert run(db_schema.fetchval("SELECT cancel_requested_at FROM execution_runs WHERE execution_id = $1",
                                  done_execution)) is None


def test_budget_exhaustion_mid_plan_ends_cancelled(db_schema, run):
    state = _state("golden-cancel-budget", "budget")
    tenant, execution = _admit(db_schema, run, state, budget_pool=state.plan.plan.steps[0].cost)
    result = _loop(db_schema, run, _live_deps(db_schema, _mock()), tenant, execution)
    assert (result.run_status, result.reason) == ("cancelled", "budget_exhausted")


# --- pauses never cancel running work (C39) ---------------------------------------------------------------------------

def test_a_pause_set_while_running_cancels_nothing_and_revokes_no_lease(db_schema, run):
    from adapters.runtime.mock_adapter import MockAdapter
    from tests_golden.s12.M12_loop import Credentials
    state = _state("golden-pause-running", "pause")
    tenant, execution = _admit(db_schema, run, state)
    run(_seed_live(db_schema, state))
    ctx = state.execution_context
    run(db_schema.execute("INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile,"
                          " state, capacity) SELECT 'w2-' || tenant_id, tenant_id, workspace_id, worker_class,"
                          " capability_profile, state, capacity FROM workers WHERE worker_id = $1", f"w-{tenant}"))
    first = _order(state)[0]

    class Pausing(MockAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            if kernel_op_id == _ops(state)[first]:
                await db_schema.execute("UPDATE tenants SET paused_until = now() + interval '1 hour'"
                                        " WHERE tenant_id = $1", tenant)
                await db_schema.execute("UPDATE workspaces SET paused_until = now() + interval '1 hour'"
                                        " WHERE workspace_id = $1", ctx.workspace_id)
                await db_schema.execute("UPDATE workers SET paused_until = now() + interval '1 hour'"
                                        " WHERE worker_id = (SELECT worker_id FROM worker_leases"
                                        " WHERE execution_id = $1 AND status = 'active')", execution)
            return await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)

    mock = Pausing(Credentials())
    deps = dataclasses.replace(_live_deps(db_schema, mock), live=_live_check(db_schema))
    result = _loop(db_schema, run, deps, tenant, execution)
    assert all(result.steps[sid] == ("completed", None) for sid in _order(state))
    first_lease = run(db_schema.fetchval("SELECT lease_id FROM worker_leases WHERE execution_id = $1"
                                         " ORDER BY acquired_at LIMIT 1", execution))
    assert _moves(db_schema, run, "lease", first_lease) == [(None, "active", "acquired"),
                                                           ("active", "released", "work_complete")]
    run(assert_system_invariants(db_schema))
