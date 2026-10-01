"""M13 golden — the probe path and EXECUTION episodes (gate commit H part 2). Owner-pinned.

Gate v10: §9 (probe outcomes; ledger before probe; INCONCLUSIVE ×3 → DEAD_LETTER with the budget LOCKED, D4; NOT_EXECUTED
→ PENDING and a retry within the ceiling, never for IRREVERSIBLE or a non-idempotent D), C6 (retries inside RUNNING;
the read re-execution path ``read_reexecution_safe``), C12 (probe and episode handling live in the S13 package and are
called from the loop), C13 (RECONCILING only when every other step is terminal), C18 (one episode record per
uncertainty; the lifecycle table), §8 step 12 (after a DEAD_LETTER step every remaining PENDING step CANCELLED
``run_dead_lettered``), Appendix A.2 and A.7 reasons, suite 8; invariants I6 (no uncertainty reaches a terminal state
without PENDING_PROBE) and the C13 condition, both checked from the transition log. Rulings: CONF-028 (the read
re-execution episode), CONF-029 (the in-line loop probes with the run RUNNING).

Interface this file fixes (on top of M12):
  * ``LoopSettings`` gains ``step_timeout_s`` (default None; the effective timeout is ``min(step.timeout,
    step_timeout_s)``), ``probe_max_attempts`` (default 3) and ``probe_backoff_s`` (default 1.0); ``LoopDeps`` gains
    ``episodes`` (default None).
  * ``adapters.postgres.reconciliation.PostgresEpisodes(database)`` — the ``step_reconciliations`` store: every
    episode move validated by ``transitions.validate("episode", ...)``, logged, fenced.
  * ``engine.stages.s13_reconciliation.probe`` — the probe path, called from the loop (C12).
  * An uncertain attempt (``AttemptOutcome.kind == "uncertain"``): a timeout goes ``running → timeout (step_timeout) →
    pending_probe (step_timeout_probe)``, a dispatched attempt without a record ``running → pending_probe
    (execution_uncertain)``, with an EXECUTION episode opened, logged ``none → pending_probe (opened)`` (A.7; ``none`` written through
    ``ReconciliationStatus.NONE``). Then per probe attempt:
    ``pending_probe → reconciling (attempt_started)``; the ledger first (a hit closes ``ledger_hit`` /
    ``ledger_hit_failure``, outcome LEDGER_HIT, no probe); else ``guard.probe``:
      EXECUTED_SUCCESS → verify → PASS: episode ``confirmed_success (executed_success)``, step ``completed
        (probe_executed_success)``, budget committed; FAIL: episode ``confirmed_failure (verified_fail)``, outcome
        VERIFIED_FAIL, step ``failed (verification_failed)``, budget released, dependents SKIPPED;
      EXECUTED_FAILURE → episode ``confirmed_failure (executed_failure)``, step ``failed (probe_executed_failure)``,
        budget released, dependents SKIPPED;
      NOT_EXECUTED → episode ``confirmed_failure (not_executed)``, step ``pending (probe_not_executed)``, budget
        released; retried within the ceiling as attempt n + 1 with a new reservation, else ``cancelled
        (not_executed_no_retry)``;
      INCONCLUSIVE → episode ``reconciling → pending_probe (inconclusive)``, ``await sleep(d)`` with ``d >=
        probe_backoff_s`` (never shrinking, none after the last attempt), again; after
        ``probe_max_attempts`` the episode is closed with outcome EXHAUSTED (status stays ``pending_probe``; event
        ``episode_closed``), the step ``dead_letter (probe_exhausted)``, the budget stays LOCKED, every remaining
        PENDING step ``cancelled (run_dead_lettered)``.
    A read step is never probed: its episode is opened and closed in one transaction as NOT_EXECUTED with evidence
    ``read_reexecution_safe``, and the step goes ``pending (read_reexecution_safe)`` and is retried within its ceiling.
  * ``MockAdapter``: ``probes`` (the ``CallMeta`` of every probe); ``timeout_not_executed`` with ``n > 0`` times out
    without executing n times, then succeeds.
"""
from __future__ import annotations

import dataclasses
import json

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import _admit, _deps, _events, _loop, _moves, _order, _ops, _state, _steps



def _mock(**programs):
    from tests_golden.s12.M12_loop import _mock as mock
    return mock(**programs)


def _probe_deps(schema, mock, **settings):
    from adapters.postgres.reconciliation import PostgresEpisodes
    deps = _deps(schema, mock, **{"step_timeout_s": 0.1, "probe_backoff_s": 0.001, **settings})
    return dataclasses.replace(deps, episodes=PostgresEpisodes(schema.database()))


def _episodes(schema, run, step_id):
    rows = run(schema.fetch("SELECT episode_id, kind, status, outcome, attempts, evidence, closed_at FROM"
                            " step_reconciliations WHERE step_id = $1 ORDER BY opened_at", step_id))
    return [dict(r) for r in rows]


def _episode_moves(schema, run, episode_id):
    return _moves(schema, run, "episode", episode_id)


def _evidence(row):
    value = row["evidence"]
    return json.loads(value) if isinstance(value, str) else value


# --- the four probe outcomes (§9, C18) -------------------------------------------------------------------------------

def test_executed_success_completes_the_step_through_pending_probe(db_schema, run):
    state = _state("golden-probe-ok", "ok")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mock(**{_ops(state)[first]: {"call": "timeout_executed"}})
    result = _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("completed", None)
    step = _steps(db_schema, run, execution)[first]
    assert step["budget"] == "committed"
    assert _moves(db_schema, run, "step", step["step_id"])[1:] == [
        ("pending", "running", "started"), ("running", "timeout", "step_timeout"),
        ("timeout", "pending_probe", "step_timeout_probe"), ("pending_probe", "completed", "probe_executed_success")]
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["kind"], episode["status"], episode["outcome"], episode["attempts"]) == (
        "EXECUTION", "confirmed_success", "EXECUTED_SUCCESS", 1) and episode["closed_at"] is not None
    assert _episode_moves(db_schema, run, episode["episode_id"]) == [
        ("none", "pending_probe", "opened"), ("pending_probe", "reconciling", "attempt_started"),
        ("reconciling", "confirmed_success", "executed_success")]
    assert len(mock.probes) == 1 and mock.side_effects(f"{state.execution_context.request_id}:{first}") == 1
    run(assert_system_invariants(db_schema))


def test_executed_failure_fails_the_step_and_skips_its_dependents(db_schema, run):
    state = _state("golden-probe-fail", "fail")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    result = _loop(db_schema, run, _probe_deps(db_schema, _mock(**{_ops(state)[first]: {"call": "timeout_failed"}})),
                   tenant, execution)
    assert result.steps[first] == ("failed", None)
    assert all(result.steps[sid] == ("skipped", "dependency_failed") for sid in rest)
    step = _steps(db_schema, run, execution)[first]
    assert step["budget"] == "released"
    assert _moves(db_schema, run, "step", step["step_id"])[-1] == ("pending_probe", "failed", "probe_executed_failure")
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"]) == ("confirmed_failure", "EXECUTED_FAILURE")
    run(assert_system_invariants(db_schema))


def test_not_executed_releases_and_retries_as_the_next_attempt(db_schema, run):
    state = _state("golden-probe-notrun", "notrun")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    mock = _mock(**{_ops(state)[first]: {"call": "timeout_not_executed", "n": 1}})
    result = _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("completed", None)
    step = _steps(db_schema, run, execution)[first]
    assert _moves(db_schema, run, "step", step["step_id"])[1:] == [
        ("pending", "running", "started"), ("running", "timeout", "step_timeout"),
        ("timeout", "pending_probe", "step_timeout_probe"), ("pending_probe", "pending", "probe_not_executed"),
        ("pending", "running", "started"), ("running", "completed", "verified")]
    budgets = run(db_schema.fetch("SELECT status FROM budget_reservations WHERE step_id = $1 ORDER BY created_at",
                                  step["step_id"]))
    assert [r["status"] for r in budgets] == ["released", "committed"]
    ids = [m.attempt_id for m in mock.calls if m.idempotency_key.endswith(f":{first}")]
    assert ids == ["att-0-1", "att-0-2"]
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"]) == ("confirmed_failure", "NOT_EXECUTED")
    run(assert_system_invariants(db_schema))


def test_not_executed_without_retry_budget_cancels_the_step(db_schema, run):
    """NOT_EXECUTED with no attempt left (retry_safety never: ceiling 1, the same path IRREVERSIBLE and a non-idempotent
    D always take, M11 matrix): PENDING, then CANCELLED ``not_executed_no_retry``; dependents SKIPPED."""
    state = _state("golden-probe-noretry", "noretry")
    tenant, execution = _admit(db_schema, run, state, retry_safety="never")
    first, *rest = _order(state)
    mock = _mock(**{_ops(state)[first]: {"call": "timeout_not_executed", "n": 1}})
    result = _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("cancelled", "not_executed_no_retry")
    assert all(result.steps[sid] == ("skipped", "dependency_failed") for sid in rest)
    step = _steps(db_schema, run, execution)[first]
    assert _moves(db_schema, run, "step", step["step_id"])[-2:] == [
        ("pending_probe", "pending", "probe_not_executed"), ("pending", "cancelled", "not_executed_no_retry")]
    assert step["budget"] == "released"
    assert len([m for m in mock.calls if m.idempotency_key.endswith(f":{first}")]) == 1
    run(assert_system_invariants(db_schema))


def test_three_inconclusive_probes_dead_letter_the_step_with_the_budget_locked(db_schema, run):
    state = _state("golden-probe-dl", "dl")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    mock = _mock(**{_ops(state)[first]: {"call": "timeout_executed", "probe": "inconclusive"}})
    consolidate_calls = []

    async def consolidate(*args):
        consolidate_calls.append(args)
    deps = dataclasses.replace(_probe_deps(db_schema, mock), consolidate=consolidate)
    result = _loop(db_schema, run, deps, tenant, execution)
    assert result.steps[first] == ("dead_letter", None)
    assert all(result.steps[sid] == ("cancelled", "run_dead_lettered") for sid in rest)
    step = _steps(db_schema, run, execution)[first]
    assert step["budget"] == "locked"                                            # D4: never released on a guess
    assert _moves(db_schema, run, "step", step["step_id"])[-1] == ("pending_probe", "dead_letter", "probe_exhausted")
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"], episode["attempts"]) == ("pending_probe", "EXHAUSTED", 3)
    assert episode["closed_at"] is not None and len(mock.probes) == 3
    assert _episode_moves(db_schema, run, episode["episode_id"]) == [
        ("none", "pending_probe", "opened")] + [("pending_probe", "reconciling", "attempt_started"),
                                              ("reconciling", "pending_probe", "inconclusive")] * 3
    assert [e["event_type"] for e in _events(db_schema, run, execution, "episode_closed")] == ["episode_closed"]
    assert run(db_schema.fetchval("SELECT count(*) FROM worker_leases WHERE execution_id = $1 AND status = 'active'",
                                  execution)) == 0
    assert len(consolidate_calls) == 1
    run(assert_system_invariants(db_schema))


# --- ledger before probe, read re-execution (§9, C6) -----------------------------------------------------------------

def test_the_ledger_is_checked_before_any_probe(db_schema, run):
    from adapters.postgres.fencing import FenceHolder
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from adapters.runtime.mock_adapter import MockAdapter
    from contracts.step_execution import AdapterResult
    from tests_golden.s12.M12_loop import Credentials
    state = _state("golden-probe-ledger", "ledger")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    ledger = PostgresIdempotencyLedger(db_schema.database())

    class RecordsThenHangs(MockAdapter):
        """The result reached the ledger, then the response was lost (e.g. another runtime recorded it)."""
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            if call_meta.idempotency_key.endswith(f":{first}"):
                owner = (await db_schema.fetch("SELECT runtime_instance_id, fencing_token FROM execution_ownership"
                                               " WHERE execution_id = $1", execution))[0]
                holder = FenceHolder(tenant_id=tenant, execution_id=execution,
                                     runtime_instance_id=owner["runtime_instance_id"],
                                     fence_token=owner["fencing_token"])
                await ledger.store(holder, idempotency_key=call_meta.idempotency_key, kernel_op_id=kernel_op_id,
                                   result=AdapterResult("ok", data={"id": 5}), ttl_s=3600)
                self.program(kernel_op_id, "timeout_executed")
            return await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)

    mock = RecordsThenHangs(Credentials())
    result = _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("completed", None) and mock.probes == []
    step = _steps(db_schema, run, execution)[first]
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"]) == ("confirmed_success", "LEDGER_HIT")
    assert _episode_moves(db_schema, run, episode["episode_id"])[-1] == ("reconciling", "confirmed_success", "ledger_hit")
    assert _moves(db_schema, run, "step", step["step_id"])[-1] == ("pending_probe", "completed", "ledger_hit_success")


def test_a_read_is_re_executed_without_a_probe(db_schema, run):
    state = _state("golden-probe-read", "read")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    read = next(s.id for s in state.plan.plan.steps if s.mutation == "R")
    mock = _mock(**{_ops(state)[read]: {"call": "timeout_not_executed", "n": 1}})
    result = _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert result.steps[read] == ("completed", None) and mock.probes == []
    step = _steps(db_schema, run, execution)[read]
    assert ("pending_probe", "pending", "read_reexecution_safe") in _moves(db_schema, run, "step", step["step_id"])
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"]) == ("confirmed_failure", "NOT_EXECUTED")
    assert _evidence(episode).get("reason") == "read_reexecution_safe"
    run(assert_system_invariants(db_schema))


def test_a_probe_success_that_fails_verification_fails_the_step(db_schema, run):
    state = _state("golden-probe-vfail", "vfail")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)

    async def fail_first(step, binding, result):
        return "FAIL" if step.id == first else "PASS"

    mock = _mock(**{_ops(state)[first]: {"call": "timeout_executed"}})
    deps = dataclasses.replace(_probe_deps(db_schema, mock), verify=fail_first)
    result = _loop(db_schema, run, deps, tenant, execution)
    assert result.steps[first] == ("failed", None)
    assert all(result.steps[sid] == ("skipped", "dependency_failed") for sid in rest)
    step = _steps(db_schema, run, execution)[first]
    assert step["budget"] == "released" and len(mock.probes) == 1
    assert _moves(db_schema, run, "step", step["step_id"])[-1] == ("pending_probe", "failed", "verification_failed")
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"]) == ("confirmed_failure", "VERIFIED_FAIL")
    assert _episode_moves(db_schema, run, episode["episode_id"])[-1] == ("reconciling", "confirmed_failure",
                                                                        "verified_fail")
    run(assert_system_invariants(db_schema))


def test_a_failure_found_in_the_ledger_fails_the_step_without_a_probe(db_schema, run):
    from adapters.postgres.fencing import FenceHolder
    from adapters.postgres.idempotency import PostgresIdempotencyLedger
    from adapters.runtime.mock_adapter import MockAdapter
    from contracts.step_execution import AdapterResult
    from tests_golden.s12.M12_loop import Credentials
    state = _state("golden-probe-ledger-fail", "ledgerfail")
    tenant, execution = _admit(db_schema, run, state)
    first, *rest = _order(state)
    ledger = PostgresIdempotencyLedger(db_schema.database())

    class RecordsAFailureThenHangs(MockAdapter):
        async def call(self, kernel_op_id, params, binding, context, *, call_meta=None):
            if call_meta.idempotency_key.endswith(f":{first}"):
                owner = (await db_schema.fetch("SELECT runtime_instance_id, fencing_token FROM execution_ownership"
                                               " WHERE execution_id = $1", execution))[0]
                holder = FenceHolder(tenant_id=tenant, execution_id=execution,
                                     runtime_instance_id=owner["runtime_instance_id"],
                                     fence_token=owner["fencing_token"])
                await ledger.store(holder, idempotency_key=call_meta.idempotency_key, kernel_op_id=kernel_op_id,
                                   result=AdapterResult("error", False, "client_error"), ttl_s=3600)
                self.program(kernel_op_id, "timeout_executed")
            return await super().call(kernel_op_id, params, binding, context, call_meta=call_meta)

    mock = RecordsAFailureThenHangs(Credentials())
    result = _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert result.steps[first] == ("failed", None) and mock.probes == []
    assert all(result.steps[sid] == ("skipped", "dependency_failed") for sid in rest)
    step = _steps(db_schema, run, execution)[first]
    assert step["budget"] == "released"
    assert _moves(db_schema, run, "step", step["step_id"])[-1] == ("pending_probe", "failed", "ledger_hit_failure")
    (episode,) = _episodes(db_schema, run, step["step_id"])
    assert (episode["status"], episode["outcome"]) == ("confirmed_failure", "LEDGER_HIT")
    assert _episode_moves(db_schema, run, episode["episode_id"])[-1] == ("reconciling", "confirmed_failure",
                                                                        "ledger_hit_failure")
    run(assert_system_invariants(db_schema))


def test_inconclusive_probes_back_off_between_attempts(db_schema, run):
    state = _state("golden-probe-backoff", "backoff")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mock(**{_ops(state)[first]: {"call": "timeout_executed", "probe": "inconclusive"}})
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
    deps = dataclasses.replace(_probe_deps(db_schema, mock, probe_backoff_s=0.002), sleep=sleep)
    _loop(db_schema, run, deps, tenant, execution)
    assert len(mock.probes) == 3 and len(slept) == 2                    # between attempts, none after the last
    assert all(d >= 0.002 for d in slept) and slept == sorted(slept)


# --- RECONCILING, I6, the S13 package (C12, C13) ---------------------------------------------------------------------

def test_the_in_line_loop_probes_with_the_run_running(db_schema, run):
    state = _state("golden-probe-running", "running")
    tenant, execution = _admit(db_schema, run, state)
    last = _order(state)[-1]
    mock = _mock(**{_ops(state)[last]: {"call": "timeout_executed"}})
    _loop(db_schema, run, _probe_deps(db_schema, mock), tenant, execution)
    assert ("running", "reconciling", "awaiting_resolution") not in _moves(db_schema, run, "run", execution)
    run(assert_system_invariants(db_schema))


def test_uncertainty_never_reaches_a_terminal_state_without_pending_probe(db_schema, run):
    """I6 across every scenario this module ran (the checker reads the whole transition log)."""
    rows = run(db_schema.fetch("SELECT entity_id, from_state, to_state FROM state_transitions WHERE entity_type = 'step'"
                               " ORDER BY transition_id"))
    history: dict = {}
    for r in rows:
        history.setdefault(r["entity_id"], []).append((r["from_state"], r["to_state"]))
    episodes = {r["step_id"] for r in run(db_schema.fetch("SELECT step_id FROM step_reconciliations"))}
    assert episodes
    for step_id in episodes:
        states = [to for _, to in history[step_id]]
        assert "pending_probe" in states, step_id
    for step_id, moves in history.items():
        for i, (frm, to) in enumerate(moves):
            if to == "timeout":
                assert moves[i + 1][1] == "pending_probe", step_id
    run(assert_system_invariants(db_schema))


def test_probe_handling_lives_in_the_s13_package():
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    allowed = ("src/engine/stages/s13_reconciliation/", "src/engine/stages/s12_execute/reliability.py",
               "src/contracts/adapter_interface.py", "src/adapters/runtime/mock_adapter.py")
    offenders = [p.relative_to(ROOT).as_posix() for p in s12_files()
                 if not p.relative_to(ROOT).as_posix().startswith(allowed)
                 and ".probe(" in p.read_text(encoding="utf-8")]
    assert offenders == [] and (ROOT / "src/engine/stages/s13_reconciliation/probe.py").exists()
