"""S12 step loop over real PostgreSQL with a scripted adapter: budget, dependents, cancellation,
live authorization, fencing, verification. Every fail-closed path is exercised.

Ported to the certified loop (CONF-035): the dependencies are built the way tests_golden/s12/M12_loop.py ``_deps``
builds them (``LoopDeps``, the certified ``reliability.ReliabilityGuard``, ``PostgresExecutionStore``, the lease,
selection, ledger and attempt adapters), plus the real consolidator, so the run row is written as in production.
The expected values on persisted rows are the prototype's; only how the dependencies and the provider are built
changed. Two setup facts the certified loop needs and the prototype did not: an ACTIVE worker whose
capability_profile lists the seed capabilities (eligibility, M8a), and writes marked ``retry_safety = 'never'``
(the catalog rule: a write is never retried by the loop; the prototype got this from having no ledger).
"""
from __future__ import annotations

import asyncio
import json

import asyncpg
import pytest

from adapters.postgres.admission_snapshot import PostgresAdmissionSnapshot
from adapters.postgres.budget_reserver import PostgresBudgetReserver
from adapters.postgres.consolidation import PostgresConsolidator
from adapters.postgres.dead_letters import PostgresDeadLetters
from adapters.postgres.execution import PostgresExecutionRepository, PostgresExecutionStore
from adapters.postgres.execution_events import PostgresExecutionEvents
from adapters.postgres.idempotency import PostgresIdempotencyLedger
from adapters.postgres.kernel_policy import PostgresKernelPolicy
from adapters.postgres.leases import PostgresLeaseManager
from adapters.postgres.live_authorization import PostgresLiveAuthorization
from adapters.postgres.reconciliation import PostgresEpisodes
from adapters.postgres.scope import PostgresRunScopes
from adapters.postgres.selection import PostgresSelectionReader
from adapters.postgres.step_attempts import PostgresStepAttempts
from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
from adapters.runtime.reliability import (
    InProcessBilling,
    InProcessBulkhead,
    InProcessHealthMonitor,
    InProcessRetryStormGuard,
)
from contracts.adapter_interface import BaseAdapter, ProbeOutcome
from contracts.step_execution import AdapterResult, Revoked
from engine.stages.s12_execute.admission_control import AdmissionSnapshot
from engine.stages.s12_execute.loop import LoopDeps, LoopSettings, run_execution
from engine.stages.s12_execute.reliability import BudgetTracker, ReliabilityGuard, TimeoutManager
from tests_postgres.test_admission import OBSERVE, READ, A, _admit, _certified
from tests_postgres.test_end_to_end import ChainModel

OK = AdapterResult("ok", data={"id": "r-1"})
HANG = "hang"                                       # the provider never answers: only the step deadline ends the call
CREATE_LIST = ChainModel(("contact.create", {"name": "Ana"}), ("contact.list", {}))
INVERSE = ("UPDATE kernel_ops SET inverse = 'crm.contact_delete' WHERE kernel_op_id = 'crm.contact_create'",)
# what the certified loop needs from the database beyond the prototype seed (see the module docstring)
WORKER = ("INSERT INTO workers (worker_id, tenant_id, workspace_id, worker_class, capability_profile, state, capacity)"
          " SELECT 'tenant-a.worker', 'tenant-a', 'tenant-a.ws', 'general', jsonb_agg(capability_id), 'ACTIVE', 4"
          " FROM capabilities",
          "UPDATE kernel_ops SET retry_safety = 'never' WHERE mutation <> 'R'")
RUNTIME = "runtime-1"                               # the runtime test_admission._admit admits with


class Adapter(BaseAdapter):
    """Scripted adapter: per kernel op a list of results (the last repeats); records every call as
    (plan step id, kernel op, attempt) and can run a hook during a call (to change the world mid-run).
    A script entry may be an AdapterResult, an exception to raise, or HANG."""
    def __init__(self, script=None, hook=None):
        self.script, self.hook, self.calls = script or {}, hook, []

    async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
        self.calls.append((call_meta.idempotency_key.rsplit(":", 1)[-1], kernel_op_id,
                           int(call_meta.attempt_id.rsplit("-", 1)[-1])))
        if self.hook:
            await self.hook(call_meta)
        results = self.script.get(kernel_op_id, [OK])
        index = min(sum(1 for c in self.calls if c[1] == kernel_op_id) - 1, len(results) - 1)
        outcome = results[index]
        if outcome == HANG:
            await asyncio.sleep(3600)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def probe(self, kernel_op_id, params, binding, context, *, call_meta):
        return ProbeOutcome.INCONCLUSIVE             # a lost write is never guessed


class Verify:
    """The loop's injected verifier: ``await verify(step, binding, result) -> verdict``."""
    def __init__(self, verdict="PASS"):
        self.verdict, self.seen = verdict, []

    async def __call__(self, step, binding, result):
        self.seen.append(step.id)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


class Live:
    """Allows the first `allow` checks, then reports the given revocation."""
    def __init__(self, allow=10**9, reason="authorization_revoked"):
        self.allow, self.reason, self.n = allow, reason, 0

    async def check(self, **kw):
        self.n += 1
        return None if self.n <= self.allow else Revoked(self.reason)


class Credentials:
    async def credential_valid(self, tenant_id, connection_id):
        return True


def _live(db, scopes=None):
    return PostgresLiveAuthorization(scopes or PostgresRunScopes(db, InProcessCircuitBreaker()), database=db,
                                     credentials=Credentials())


async def _all_pass(tenant_id, execution_id, plan_step_id):
    return AdmissionSnapshot(kill_switch_engaged=False, tenant_quota_exceeded=False, tenant_active=True,
                             workspace_active=True, mode_allowed=True, provider_allowed=True,
                             worker_capacity_available=True, circuit_open=False, db_pool_pressure=False,
                             budget_available=True, system_overloaded=False)


async def _no_preflight_problem(step, binding):
    return None


async def _no_sleep(_):
    return None


def _deps(db, adapter, verification=None, live=None, breaker=None, runtime=RUNTIME, admission=None):
    breaker = breaker or InProcessCircuitBreaker(50, 30.0)
    guard = ReliabilityGuard(adapter, bulkhead=InProcessBulkhead(4), breaker=breaker,
                             budget=BudgetTracker(PostgresBudgetReserver(db)),
                             retry_storm=InProcessRetryStormGuard(100, 60.0), timeouts=TimeoutManager(),
                             health=InProcessHealthMonitor(), billing=InProcessBilling(), probe_timeout_s=0.5)
    consolidator = PostgresConsolidator(db)
    settings = LoopSettings(admission_max_attempts=3, lease_max_attempts=3, lease_ttl_s=30.0, backoff_base_s=0.001,
                            ledger_ttl_s=3600.0, step_timeout_s=0.2, probe_backoff_s=0.001,
                            verification_backoff_s=0.001)
    return LoopDeps(runtime_instance_id=runtime, store=PostgresExecutionStore(db), events=PostgresExecutionEvents(db),
                    admission=admission or _all_pass, selection=PostgresSelectionReader(db),
                    leases=PostgresLeaseManager(db), budget=PostgresBudgetReserver(db),
                    kernel_policy=PostgresKernelPolicy(db), preflight=_no_preflight_problem, guard=guard,
                    idempotency=PostgresIdempotencyLedger(db), attempts=PostgresStepAttempts(db),
                    live=live or _live(db), verify=verification or Verify(), consolidate=consolidator,
                    cancel_run=consolidator.cancel, episodes=PostgresEpisodes(db),
                    dead_letters=PostgresDeadLetters(db), sleep=_no_sleep, settings=settings)


async def _admitted(db, model=READ):
    state = await _certified(db, model)
    out = await _admit(db, state)
    assert out.status == "ADMITTED", out
    return state.plan.execution_id, state


async def _rows(db):
    async with db.tenant_transaction(A) as c:
        steps = [dict(r) for r in await c.fetch("SELECT * FROM execution_steps ORDER BY plan_step_id")]
        run = dict(await c.fetchrow("SELECT * FROM execution_runs"))
        budget = [dict(r) for r in await c.fetch("SELECT * FROM budget_reservations ORDER BY step_id")]
        moves = [(r["entity_type"], r["from_state"], r["to_state"], r["reason"]) for r in
                 await c.fetch("SELECT * FROM state_transitions ORDER BY transition_id")]
    return run, steps, budget, moves


async def _letters(db):
    """The error types of the run's dead-letter records (where the certified loop keeps a failed step's error)."""
    async with db.tenant_transaction(A) as c:
        return [r["error_type"] for r in await c.fetch("SELECT error_type FROM dead_letters ORDER BY created_at")]


COLLATERAL = ("collateral", "run_dead_lettered")      # the prototype's and the certified loop's reason for collateral moves


def _summary(steps):
    return [(s["plan_step_id"], s["status"], s["terminal_reason"]) for s in steps]


def go(pg, body, *setup):
    return pg(body, *WORKER, *setup)


# ---- happy paths -------------------------------------------------------------------------------

def test_a_read_run_completes_commits_its_budget_and_logs_every_move(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, moves) = go(pg, body)
    assert run["status"] == "completed"  # execution_runs.budget_spent is not written (finding P1-F1)
    assert calls == [("step-1", "crm.contact_list", 1)]
    assert (run["status"], run["terminal_reason"]) == ("completed", None)
    assert run["completed_at"] is not None              # run duration_ms is not written either (finding P1-F1)
    assert (steps[0]["status"], steps[0]["attempt"], steps[0]["dispatched_attempt"]) == ("completed", 1, 1)
    assert [(b["status"], b["cost"]) for b in budget] == [("committed", 1)]
    assert steps[0]["reservation_id"] == budget[0]["reservation_id"]
    step_moves = [(f, t) for k, f, t, _ in moves if k == "step"]
    assert step_moves == [(None, "pending"), ("pending", "running"), ("running", "completed")]
    assert ("run", "running", "completed", "consolidated") in moves


def test_a_verified_chain_runs_in_order_and_commits_each_steps_own_budget(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        adapter, verify = Adapter(), Verify("PASS")
        result = await run_execution(_deps(db, adapter, verify), A, eid)
        return result, adapter.calls, verify.seen, await _rows(db)
    result, calls, verified, (run, steps, budget, _) = go(pg, body, *OBSERVE, *INVERSE)
    assert run["status"] == "completed"  # execution_runs.budget_spent is not written (finding P1-F1)
    assert [c[1] for c in calls] == ["crm.contact_create", "crm.contact_list"]
    # CONF-035 port: the prototype asked its verifier about the mutation only; the certified loop asks the injected
    # verifier about every step (the M15 StepVerifier decides per step what to check) (finding P1-F6)
    assert verified == ["step-1", "step-2"]
    assert [(b["cost"], b["status"]) for b in budget] == [(3, "committed"), (1, "committed")]
    assert json.loads(steps[0]["undo_token"]) == {"inverse_kernel_op_id": "crm.contact_delete",
                                                   "step_id": steps[0]["step_id"]}
    assert steps[1]["undo_token"] is None                               # a read has nothing to undo


# ---- failures, dependents, fail-closed ---------------------------------------------------------

def test_a_failed_mutation_releases_its_budget_and_skips_its_dependents(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        adapter = Adapter({"crm.contact_create": [AdapterResult("error", False, "server_error")]})
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db), await _letters(db)
    result, calls, (run, steps, budget, _), letters = go(pg, body, *OBSERVE)
    assert run["status"] == "failed" and len(calls) == 1               # a mutation is never retried
    assert _summary(steps) == [("step-1", "failed", None), ("step-2", "skipped", "dependency_failed")]
    assert [(b["status"]) for b in budget] == ["released"]                  # the skipped step reserved nothing
    # CONF-035 port: the certified loop does not write execution_steps.error (finding P1-F2); a write that fails
    # with a provider error leaves a transient dead-letter record instead
    assert letters == ["transient"]


def test_a_failed_verification_fails_the_step_and_releases_the_budget(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        result = await run_execution(_deps(db, Adapter(), Verify("FAIL")), A, eid)
        return result, await _rows(db)
    result, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert run["status"] == "failed"
    assert _summary(steps) == [("step-1", "failed", None), ("step-2", "skipped", "dependency_failed")]
    assert budget[0]["status"] == "released"


# CONF-035 port: the prototype also ran Verify("MAYBE") and a verifier that raises (finding P1-F3), and None
# (no verifier: LoopDeps.verify is mandatory in the certified loop)
@pytest.mark.parametrize("verification", [Verify("UNKNOWN")])
def test_an_unverifiable_mutation_is_never_a_success_it_goes_to_dead_letter_with_budget_locked(pg, verification):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, verification), A, eid)
        return result, adapter.calls, await _rows(db), await _letters(db)
    result, calls, (run, steps, budget, moves), letters = go(pg, body, *OBSERVE)
    # the run row keeps no terminal reason for a dead letter (finding P1-F4); the record carries it
    assert (run["status"], letters) == ("dead_letter", ["unknown_unresolved"])
    assert _summary(steps) == [("step-1", "dead_letter", None), ("step-2", "cancelled", "run_dead_lettered")]
    assert [b["status"] for b in budget] == ["locked"]                     # stays LOCKED (D4)
    assert len(calls) == 1                                                  # nothing ran after uncertain state
    trigger = [(f, t) for k, f, t, r in moves if k == "step" and r not in COLLATERAL]
    assert trigger[-2:] == [("running", "pending_probe"), ("pending_probe", "dead_letter")]


def test_a_timeout_is_probed_never_guessed_so_it_dead_letters_with_budget_locked(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        adapter = Adapter({"crm.contact_create": [HANG]})
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, await _rows(db)
    result, (run, steps, budget, moves) = go(pg, body, *OBSERVE)
    assert run["status"] == "dead_letter"
    assert _summary(steps) == [("step-1", "dead_letter", None), ("step-2", "cancelled", "run_dead_lettered")]
    assert budget[0]["status"] == "locked"
    trigger = [(f, t) for k, f, t, r in moves if k == "step" and r not in COLLATERAL]
    assert trigger[-3:] == [("running", "timeout"), ("timeout", "pending_probe"), ("pending_probe", "dead_letter")]


def test_a_read_is_retried_when_the_error_is_retryable_up_to_the_ceiling(pg):
    retry = AdapterResult("error", True, "server_error")

    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter({"crm.contact_list": [retry, retry, OK]})
        result = await run_execution(_deps(db, adapter), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body)
    assert run["status"] == "completed" and [c[2] for c in calls] == [1, 2, 3]
    assert (steps[0]["attempt"], steps[0]["dispatched_attempt"]) == (3, 3)


def test_a_read_that_keeps_failing_fails_after_three_attempts(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter({"crm.contact_list": [AdapterResult("error", True, "server_error")]})
        result = await run_execution(_deps(db, adapter), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body)
    assert (run["status"], len(calls)) == ("failed", 3)
    assert budget[0]["status"] == "released"


def test_a_write_with_a_retryable_error_gets_exactly_one_attempt(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        adapter = Adapter({"crm.contact_create": [AdapterResult("error", True, "server_error"), OK]})
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, _, _, _) = go(pg, body, *OBSERVE)
    assert run["status"] == "failed" and len(calls) == 1


def test_an_adapter_that_raises_is_an_adapter_defect_not_a_crash(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        result = await run_execution(_deps(db, Adapter({"crm.contact_list": [RuntimeError("boom")]})), A, eid)
        return result, await _rows(db)
    result, (run, steps, budget, _) = go(pg, body)
    assert run["status"] == "failed"         # execution_steps.error is not written (finding P1-F2)


def test_an_open_circuit_refuses_the_call_and_fails_the_step(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        breaker = InProcessCircuitBreaker(1, 30.0)
        breaker.record_failure("crm")
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, breaker=breaker), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body)
    assert (run["status"], calls) == ("failed", [])   # execution_steps.error is not written (finding P1-F2)


# ---- budget (C3, C15) --------------------------------------------------------------------------

def test_budget_exhaustion_cancels_this_step_and_the_rest_and_keeps_earlier_commits(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)          # S8's precheck passed with the full pool ...
        async with db.tenant_transaction(A) as c:           # ... then the pool shrinks before S12 reserves
            await c.execute("UPDATE tenants SET budget_pool = 3")
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert (run["status"], run["terminal_reason"]) == ("cancelled", "budget_exhausted")   # budget_spent: P1-F1
    assert _summary(steps) == [("step-1", "completed", None), ("step-2", "cancelled", "budget_exhausted")]
    assert [b["status"] for b in budget] == ["committed"] and len(calls) == 1
    assert run["terminal_reason"] == "budget_exhausted"


async def _reservable(db, eid, n):
    """n extra PENDING steps of the admitted run (copies of its first step), and the loop's fence holder."""
    async with db.tenant_transaction(A) as c:
        for i in range(n):
            await c.execute(
                "INSERT INTO execution_steps (step_id, plan_step_id, execution_id, tenant_id, kernel_op_id,"
                " resolved_binding_id, effective_risk, effective_mutation, request_fingerprint, status, attempt)"
                " SELECT $2 || ':extra-' || $3, 'extra-' || $3, execution_id, tenant_id, kernel_op_id,"
                " resolved_binding_id, effective_risk, effective_mutation, request_fingerprint, status, 0"
                " FROM execution_steps WHERE execution_id = $1 ORDER BY plan_step_id LIMIT 1", eid, eid, str(i))
    return [f"{eid}:extra-{i}" for i in range(n)], PostgresExecutionRepository(db, RUNTIME).holder(A, eid)


def test_the_reserver_reserves_atomically_against_the_pool_and_is_idempotent_per_step(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        steps, holder = await _reservable(db, eid, 4)
        reserver = PostgresBudgetReserver(db)
        results = await asyncio.gather(*[reserver.reserve(holder, user_id="tenant-a.user", step_id=s, cost=2)
                                         for s in steps])
        again = await reserver.reserve(holder, user_id="tenant-a.user",
                                       step_id=next(s for s, r in zip(steps, results, strict=True) if r.reservation_id), cost=2)
        return results, again
    results, again = go(pg, body, "UPDATE tenants SET budget_pool = 5 WHERE tenant_id = 'tenant-a'")
    assert sum(1 for r in results if r.reservation_id) == 2                # 5 / 2 = two fit, exactly
    assert again.reservation_id in {r.reservation_id for r in results} and again.status == "reserved"


def test_reservation_moves_follow_the_state_machine(pg):
    from contracts.errors import StateTransitionError

    async def body(db):
        eid, _ = await _admitted(db)
        (step,), holder = await _reservable(db, eid, 1)
        r = PostgresBudgetReserver(db)
        rid = (await r.reserve(holder, user_id="u", step_id=step, cost=1)).reservation_id
        errors = []
        moves = ((r.commit, "step_completed"), (r.lock, "step_started"), (r.lock, "step_started"))
        for move, reason in moves:                                # reserved cannot commit; then lock; locked cannot lock
            try:
                await move(holder, rid, reason=reason)
                errors.append(None)
            except StateTransitionError as exc:
                errors.append(str(exc))
        await r.commit(holder, rid, reason="step_completed")
        for move, reason in ((r.release, "step_failed"), (r.lock, "step_started")):
            try:
                await move(holder, rid, reason=reason)
                errors.append(None)
            except StateTransitionError as exc:
                errors.append(str(exc))
        return errors, await r.status(A, rid)
    errors, final = go(pg, body)
    assert [bool(e) for e in errors] == [True, False, True, True, True] and final == "committed"


def test_released_budget_is_available_again_and_committed_budget_is_not(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        (s1, s2, s3), holder = await _reservable(db, eid, 3)
        r = PostgresBudgetReserver(db)
        first = await r.reserve(holder, user_id="u", step_id=s1, cost=4)
        blocked = await r.reserve(holder, user_id="u", step_id=s2, cost=4)
        await r.release(holder, first.reservation_id, reason="preflight_failed")
        second = await r.reserve(holder, user_id="u", step_id=s2, cost=4)
        await r.lock(holder, second.reservation_id, reason="step_started")
        await r.commit(holder, second.reservation_id, reason="step_completed")
        third = await r.reserve(holder, user_id="u", step_id=s3, cost=4)
        return first, blocked, second, third
    first, blocked, second, third = go(pg, body, "UPDATE tenants SET budget_pool = 5 WHERE tenant_id = 'tenant-a'")
    assert (first.reservation_id is not None, blocked.reservation_id is None,
            second.reservation_id is not None, third.reservation_id is None) == (True, True, True, True)


# ---- cancellation (C16) and live authorization (C23) -------------------------------------------

def test_a_cancel_request_before_the_loop_cancels_every_step_without_calling_the_adapter(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        async with db.tenant_transaction(A) as c:
            await c.execute("UPDATE execution_runs SET cancel_requested_at = now()")
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert (run["status"], run["terminal_reason"], calls, budget) == ("cancelled", "user_cancelled", [], [])
    assert _summary(steps) == [("step-1", "cancelled", "user_cancelled"), ("step-2", "cancelled", "user_cancelled")]


def test_a_cancel_request_during_a_step_lets_it_finish_then_cancels_the_rest(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)

        async def cancel(call):
            async with db.tenant_transaction(A) as c:
                await c.execute("UPDATE execution_runs SET cancel_requested_at = now()")
        adapter = Adapter(hook=cancel)
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert run["status"] == "cancelled" and len(calls) == 1
    assert _summary(steps) == [("step-1", "completed", None), ("step-2", "cancelled", "user_cancelled")]
    assert [b["status"] for b in budget] == ["committed"]                 # the finished step stays committed


def test_the_kill_switch_stops_a_run_before_any_side_effect(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        async with db.transaction() as c:
            await c.execute("UPDATE system_settings SET kill_switch_engaged = true")
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, Verify(), admission=PostgresAdmissionSnapshot(db)), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert (run["status"], run["terminal_reason"], calls, budget) == ("cancelled", "kill_switch_engaged", [], [])
    assert all(s["terminal_reason"] == "kill_switch_engaged" for s in steps)


def test_a_grant_revoked_while_the_run_waits_stops_the_next_step(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)

        async def revoke(call):
            async with db.tenant_transaction(A) as c:
                await c.execute("UPDATE capability_grants SET is_active = false WHERE capability_id = 'cap.contact.list'")
        adapter = Adapter(hook=revoke)
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert (run["status"], run["terminal_reason"], len(calls)) == ("cancelled", "authorization_revoked", 1)
    assert _summary(steps) == [("step-1", "completed", None), ("step-2", "cancelled", "authorization_revoked")]


def test_revocation_right_before_the_adapter_call_releases_the_reserved_budget(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, live=Live(allow=1)), A, eid)   # 1st check ok, 2nd revoked
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, moves) = go(pg, body)
    assert (run["status"], calls) == ("cancelled", [])
    assert _summary(steps) == [("step-1", "cancelled", "authorization_revoked")]
    assert [b["status"] for b in budget] == ["released"]
    # CONF-035 port: the prototype went running -> cancelled; the certified loop settles the started attempt first
    # (running -> pending_probe -> pending via the dispatch marker: nothing was sent), then cancels (finding P1-F5)
    assert [(f, t) for k, f, t, _ in moves if k == "step"] == [
        (None, "pending"), ("pending", "running"), ("running", "pending_probe"), ("pending_probe", "pending"),
        ("pending", "cancelled")]


def test_unreadable_live_state_is_a_revocation(pg):
    class Broken:
        async def for_run(self, tenant_id, workspace_id):
            raise RuntimeError("down")

    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter()
        deps = _deps(db, adapter, live=_live(db, Broken()))
        return await run_execution(deps, A, eid), adapter.calls, await _rows(db)
    result, calls, (run, _, _, _) = go(pg, body)
    assert (run["status"], run["terminal_reason"], calls) == ("cancelled", "authorization_revoked", [])


# ---- fencing -----------------------------------------------------------------------------------

def test_a_runtime_that_does_not_own_the_execution_writes_nothing(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter()
        result = await run_execution(_deps(db, adapter, runtime="some-other-runtime"), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, moves) = go(pg, body)
    assert (result.reason, calls, run["status"], steps[0]["status"]) == ("fenced_out", [], "running", "pending")


def test_being_fenced_out_mid_run_stops_all_further_work(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)

        async def steal(call):
            async with db.tenant_transaction(A) as c:
                await c.execute("UPDATE execution_ownership SET runtime_instance_id = 'new-owner', fencing_token = 1")
        adapter = Adapter(hook=steal)
        result = await run_execution(_deps(db, adapter, Verify()), A, eid)
        return result, adapter.calls, await _rows(db)
    result, calls, (run, steps, budget, _) = go(pg, body, *OBSERVE)
    assert result.reason == "fenced_out" and len(calls) == 1          # the second step never started
    assert (run["status"], steps[0]["status"], steps[1]["status"]) == ("running", "running", "pending")


# ---- isolation and safety of the tables --------------------------------------------------------

def test_another_tenant_cannot_load_or_run_the_execution(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        loaded = await PostgresExecutionStore(db).load("tenant-b", eid)
        try:
            await run_execution(_deps(db, Adapter()), "tenant-b", eid)
            return loaded, "ran"
        except LookupError:
            return loaded, "not found"
    assert go(pg, body) == (None, "not found")


def test_a_step_terminal_reason_can_never_be_changed_and_cancelled_needs_one(pg):
    async def body(db):
        eid, _ = await _admitted(db, CREATE_LIST)
        async with db.tenant_transaction(A) as c:
            await c.execute("UPDATE execution_steps SET status = 'cancelled', terminal_reason = 'user_cancelled'"
                            " WHERE plan_step_id = 'step-1'")
        errors = []
        for sql in ("UPDATE execution_steps SET terminal_reason = 'budget_exhausted' WHERE plan_step_id = 'step-1'",
                    "UPDATE execution_steps SET status = 'cancelled' WHERE plan_step_id = 'step-2'",
                    "UPDATE execution_steps SET terminal_reason = 'made_up' WHERE plan_step_id = 'step-2'"):
            try:
                async with db.tenant_transaction(A) as c:
                    await c.execute(sql)
                errors.append(None)
            except asyncpg.PostgresError as exc:
                errors.append(type(exc).__name__)
        return errors
    assert all(e for e in go(pg, body, *OBSERVE))


def test_running_a_finished_run_again_does_nothing(pg):
    async def body(db):
        eid, _ = await _admitted(db)
        adapter = Adapter()
        await run_execution(_deps(db, adapter), A, eid)
        first = (await _rows(db))[0]["status"]                              # the run row after the first run
        second = await run_execution(_deps(db, adapter), A, eid)
        return first, second, adapter.calls
    first, second, calls = go(pg, body)
    assert (first, second.run_status, len(calls)) == ("completed", "completed", 1)
