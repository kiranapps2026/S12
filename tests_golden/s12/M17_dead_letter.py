"""M17 golden — dead letters and the explicit rollback (gate commit J). Owner-pinned.

Gate v10: §11 (a record for retries exhausted, ``unknown_unresolved``, verification FAIL, the human layer and inverse
failures; none for 401/403/404/422; a record is not the step state DEAD_LETTER — only unresolved uncertainty puts the
step there; evidence always; alerts for ``permanent`` and ``unknown_unresolved``: a recorded event and a log line),
C21 (status, ``resolved`` consistent, ``retry_mode`` set once, ``resolution_outcome`` required to resolve, the budget
effect of a resolution only on a LOCKED reservation: EXECUTED → COMMITTED, NOT_EXECUTED → RELEASED, UNDETERMINED or
abandoned → COMMITTED), C27 (``origin = rollback``: may exist for a terminal run, ``retry_mode = NONE``, never changes
run, step or budget), C29, D2 (``rollback_execution()``: explicit only, confirms the original executed first, runs the
inverse through the full guard with key ``{request_id}:{plan_step_id}:inverse``, never compensates IRREVERSIBLE, a
failed inverse becomes a ``rollback`` dead letter), D4 (resolving never changes the run or the step), D5 (a retry never
re-executes: PROBE calls only the probe, VERIFY only the verifier, NONE never retries), Appendix A.3 and A.6, suite 11;
invariants I11, I12 (dead-letter parts). Rulings: CONF-024 (the inverse key uses ``plan_step_id``, like the step key),
CONF-038 (an inverse has no reservation: the rollback's guard uses the ``InverseBudget`` layer).

Interface this file fixes:
  * ``adapters.postgres.dead_letters.PostgresDeadLetters(database)``:
      ``async create(holder, *, step_id, kernel_op_id, error_type, retry_mode, error, evidence, reservation_id=None,
        attempt_id=None, episode_id=None, mutation="R") -> dead_letter_id`` — one fenced write; ValueError (nothing
        written) for empty or non-dict evidence, an empty error code, or a value outside its enum; logged ``None →
        pending (created)``; ``permanent`` / ``unknown_unresolved`` also write a ``dead_letter_alert`` event (with the
        ``dead_letter_id``) in the same transaction and log at ERROR with ``dead_letter_id`` as a record attribute.
      ``async create_rollback(tenant_id, *, execution_id, step_id, kernel_op_id, error_type, error, evidence,
        mutation)`` — ``origin = rollback``, ``retry_mode = NONE``, no fence (the run is terminal).
      ``async get(tenant_id, dead_letter_id) -> DeadLetterRecord | None`` (``status``, ``retry_mode``, ``origin``,
        ``error_type``, ``reservation_id``, ``episode_id``, ``attempt_id``, ``retry_count``, ``max_retries``,
        ``resolution_outcome``, ``evidence``, …).
      ``async start_retry(tenant_id, id) -> DeadLetterRecord`` (``pending → retrying (retry_started)``, only PROBE or
        VERIFY, else ValueError and nothing written); ``async retry_inconclusive(tenant_id, id)`` (``retrying →
        pending``, ``retry_count`` + 1); ``async resolve(tenant_id, id, outcome)`` (``human_resolved`` from pending,
        ``retry_resolved`` from retrying); ``async abandon(tenant_id, id, outcome="UNDETERMINED")`` (from retrying
        only). Every move validated by Appendix A.6 and logged (an illegal one raises the M03/M04
        ``IllegalStateTransition``, nothing written); a resolution settles a LOCKED reservation with the A.3
        ``dead_letter_*`` reasons, in the same transaction, and never touches the run or the step.
  * ``engine.stages.s14_dead_letter.retry.retry_dead_letter(tenant_id, id, *, dead_letters, probe, reverify) ->
    status``: ``probe(record)`` / ``reverify(record)`` are called for PROBE / VERIFY only; EXECUTED_* or PASS / FAIL →
    resolved EXECUTED, NOT_EXECUTED → resolved NOT_EXECUTED, INCONCLUSIVE, UNKNOWN or an exception → back to pending,
    and abandoned UNDETERMINED once ``retry_count`` reaches ``max_retries`` (3).
  * ``engine.stages.s14_dead_letter.rollback.rollback_execution(tenant_id, execution_id, *, database, guard,
    dead_letters, confirm_executed) -> RollbackReport(compensated, skipped, failed)`` (plan step ids);
    ``confirm_executed(RollbackStep)`` is awaited before each inverse; events ``rollback_step``.
  * ``engine.stages.s12_execute.reliability.InverseBudget`` — the budget layer for inverse calls.
  * The loop: ``LoopDeps.dead_letters`` (default None); records: retries exhausted → ``transient`` / NONE (evidence
    ``attempts``, ``error_class``; ``attempt_id`` of the last attempt); verification FAIL → ``data`` / NONE (evidence
    ``layers``); EXECUTION episode EXHAUSTED → ``unknown_unresolved`` / PROBE; VERIFICATION episode EXHAUSTED →
    ``unknown_unresolved`` / VERIFY; human layer → ``unknown_unresolved`` / NONE; the last three carry the episode
    and the step's LOCKED reservation.
"""
from __future__ import annotations

import dataclasses
import json
import logging

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import _admit, _events, _loop, _moves, _order, _ops, _state, _steps


def _mocked(**programs):
    from tests_golden.s12.M12_loop import _mock as mock
    return mock(**programs)


def _dl_deps(schema, mock, **settings):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from tests_golden.s12.M16_consolidation import _consolidating
    return dataclasses.replace(_consolidating(schema, mock, **settings),
                               dead_letters=PostgresDeadLetters(schema.database()))


def _letters(schema, run, execution):
    rows = run(schema.fetch("SELECT * FROM dead_letters WHERE execution_id = $1 ORDER BY created_at", execution))
    return [dict(r) for r in rows]


def _evidence(row):
    body = row["context"]
    return json.loads(body) if isinstance(body, str) else body


def _statuses(schema, run, execution):
    runs = run(schema.fetch("SELECT status FROM execution_runs WHERE execution_id = $1", execution))
    steps = run(schema.fetch("SELECT step_id, status FROM execution_steps WHERE execution_id = $1 ORDER BY step_id",
                             execution))
    budget = run(schema.fetch("SELECT reservation_id, status FROM budget_reservations WHERE execution_id = $1"
                              " ORDER BY reservation_id", execution))
    return [tuple(r) for r in runs], [tuple(r) for r in steps], [tuple(r) for r in budget]


def _holder(schema, run, tenant, execution):
    from tests_golden.s12.M16_consolidation import _holder as holder
    return holder(schema, run, tenant, execution)


# --- creation rules (§11, D5) ----------------------------------------------------------------------------------------

def test_retries_exhausted_leave_the_step_failed_with_a_transient_record(db_schema, run):
    state = _state("golden-dl-exhausted", "dlexh")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    result = _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {
        "call": "fail_500_then_success", "n": 9}})), tenant, execution)
    assert result.steps[first] == ("failed", None)
    (letter,) = _letters(db_schema, run, execution)
    assert (letter["error_type"], letter["retry_mode"], letter["origin"], letter["status"], letter["resolved"]) == (
        "transient", "NONE", "execution", "pending", False)
    assert _evidence(letter) == {"attempts": 2, "error_class": "server_error"} and letter["attempt_id"] == "att-0-2"
    assert letter["step_id"] == _steps(db_schema, run, execution)[first]["step_id"]
    assert run(db_schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution)) == "failed"
    assert _moves(db_schema, run, "dead_letter", letter["dead_letter_id"]) == [(None, "pending", "created")]
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("behaviour", ["auth_401", "validation_422"])
def test_a_client_error_never_creates_a_dead_letter(db_schema, run, behaviour):
    state = _state(f"golden-dl-client-{behaviour}", f"dlcl{behaviour[:4]}")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    result = _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {"call": behaviour}})),
                   tenant, execution)
    assert result.steps[first] == ("failed", None) and _letters(db_schema, run, execution) == []


def test_a_verification_failure_is_a_data_record_and_the_run_follows_its_step_states(db_schema, run):
    state = _state("golden-dl-vfail", "dlvfail")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    result = _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {"call": "verify_mismatch"}})),
                   tenant, execution)
    assert result.steps[first] == ("failed", None)
    (letter,) = _letters(db_schema, run, execution)
    assert (letter["error_type"], letter["retry_mode"], letter["error"]) == ("data", "NONE", "verification_failed")
    assert {"layer": "provider_state", "verdict": "FAIL"} in _evidence(letter)["layers"]
    assert run(db_schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution)) == "failed"
    run(assert_system_invariants(db_schema))


def test_an_unresolved_execution_is_a_probe_record_with_its_episode_budget_and_an_alert(db_schema, run, caplog):
    state = _state("golden-dl-probe", "dlprobe")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    caplog.set_level(logging.DEBUG)
    _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {
        "call": "timeout_executed", "probe": "inconclusive"}})), tenant, execution)
    step = _steps(db_schema, run, execution)[first]
    (letter,) = _letters(db_schema, run, execution)
    episode = run(db_schema.fetchval("SELECT episode_id FROM step_reconciliations WHERE step_id = $1"
                                     " AND kind = 'EXECUTION'", step["step_id"]))
    reservation = run(db_schema.fetchval("SELECT reservation_id FROM execution_steps WHERE step_id = $1",
                                         step["step_id"]))
    assert (letter["error_type"], letter["retry_mode"], letter["episode_id"], letter["reservation_id"]) == (
        "unknown_unresolved", "PROBE", episode, reservation)
    assert step["status"] == "dead_letter" and step["budget"] == "locked"
    assert run(db_schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution)) == \
        "dead_letter"
    alerts = [json.loads(e["payload"]) if isinstance(e["payload"], str) else e["payload"]
              for e in _events(db_schema, run, execution, "dead_letter_alert")]
    assert [a["dead_letter_id"] for a in alerts] == [letter["dead_letter_id"]]
    logged = [r for r in caplog.records if r.levelno >= logging.ERROR
              and getattr(r, "dead_letter_id", None) == letter["dead_letter_id"]]
    assert logged
    run(assert_system_invariants(db_schema))


def test_an_unresolved_verification_is_a_verify_record(db_schema, run):
    state = _state("golden-dl-verify", "dlverify")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {
        "call": "success", "observe": "inconclusive"}})), tenant, execution)
    (letter,) = _letters(db_schema, run, execution)
    kind = run(db_schema.fetchval("SELECT kind FROM step_reconciliations WHERE episode_id = $1", letter["episode_id"]))
    assert (letter["error_type"], letter["retry_mode"], kind) == ("unknown_unresolved", "VERIFY", "VERIFICATION")
    run(assert_system_invariants(db_schema))


def test_the_human_layer_is_a_record_without_automatic_retry(db_schema, run):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from tests_golden.s12.M15_verification import ScriptedVerification, _outcome
    from tests_golden.s12.M16_consolidation import _consolidating
    state = _state("golden-dl-human", "dlhuman")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    script = ScriptedVerification(_outcome(schema="PASS", provider_state="PASS", human="UNKNOWN"))
    others = ScriptedVerification(_outcome(schema="PASS"))

    class PerStep:
        async def verify(self, step, *args, **kw):
            return await (script if step.id == first else others).verify(step, *args, **kw)

    deps = dataclasses.replace(_consolidating(db_schema, _mocked(), verified=False), verification=PerStep(),
                               dead_letters=PostgresDeadLetters(db_schema.database()))
    _loop(db_schema, run, deps, tenant, execution)
    (letter,) = _letters(db_schema, run, execution)
    assert (letter["error_type"], letter["retry_mode"], letter["error"]) == (
        "unknown_unresolved", "NONE", "human_verification_pending")
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("name,change", [("empty", {"evidence": {}}), ("none", {"evidence": None}),
                                         ("list", {"evidence": ["attempts"]}), ("noerror", {"error": ""}),
                                         ("errtype", {"error_type": "fatal"}), ("mode", {"retry_mode": "LATER"})])
def test_a_record_without_evidence_or_with_an_unknown_value_is_refused(db_schema, run, name, change):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    state = _state(f"golden-dl-refused-{name}", f"dlref{name}")
    tenant, execution = _admit(db_schema, run, state)
    step_id = _steps(db_schema, run, execution)[_order(state)[0]]["step_id"]
    args = dict(step_id=step_id, kernel_op_id="op", error_type="transient", retry_mode="NONE", error="x",
                evidence={"attempts": 1})
    args.update(change)
    with pytest.raises(ValueError):
        run(PostgresDeadLetters(db_schema.database()).create(_holder(db_schema, run, tenant, execution), **args))
    assert _letters(db_schema, run, execution) == []


# --- lifecycle and budget (A.6, C21, D4) -----------------------------------------------------------------------------

def _probe_letter(schema, run, name):
    """A run whose first step is DEAD_LETTER (EXECUTION episode exhausted) with a PROBE record and a LOCKED budget."""
    state = _state(f"golden-dl-life-{name}", f"dll{name}")
    tenant, execution = _admit(schema, run, state)
    first = _order(state)[0]
    _loop(schema, run, _dl_deps(schema, _mocked(**{_ops(state)[first]: {
        "call": "timeout_executed", "probe": "inconclusive"}})), tenant, execution)
    (letter,) = _letters(schema, run, execution)
    return tenant, execution, letter


def test_the_lifecycle_follows_appendix_a6(db_schema, run):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from engine.stages.s12_execute.transitions import IllegalStateTransition
    tenant, execution, letter = _probe_letter(db_schema, run, "moves")
    letters, did = PostgresDeadLetters(db_schema.database()), letter["dead_letter_id"]
    with pytest.raises(IllegalStateTransition):
        run(letters.abandon(tenant, did))                                          # abandoned only from retrying
    record = run(letters.start_retry(tenant, did))
    assert record.status == "retrying"
    run(letters.retry_inconclusive(tenant, did))
    run(letters.start_retry(tenant, did))
    run(letters.resolve(tenant, did, "EXECUTED"))
    got = run(letters.get(tenant, did))
    assert (got.status, got.resolution_outcome, got.retry_count) == ("resolved", "EXECUTED", 1)
    assert run(db_schema.fetchval("SELECT resolved FROM dead_letters WHERE dead_letter_id = $1", did)) is True
    assert _moves(db_schema, run, "dead_letter", did) == [
        (None, "pending", "created"), ("pending", "retrying", "retry_started"),
        ("retrying", "pending", "retry_inconclusive"), ("pending", "retrying", "retry_started"),
        ("retrying", "resolved", "retry_resolved")]
    for illegal in (lambda: letters.resolve(tenant, did, "EXECUTED"), lambda: letters.start_retry(tenant, did)):
        with pytest.raises(IllegalStateTransition):                            # resolved is terminal
            run(illegal())
    run(assert_system_invariants(db_schema))


@pytest.mark.parametrize("how,budget,reason", [
    ("EXECUTED", "committed", "dead_letter_resolved_executed"),
    ("NOT_EXECUTED", "released", "dead_letter_resolved_not_executed"),
    ("UNDETERMINED", "committed", "dead_letter_resolved_undetermined"),
    ("abandon", "committed", "dead_letter_abandoned"),
])
def test_a_resolution_settles_the_locked_budget_and_never_changes_the_run_or_step(db_schema, run, how, budget, reason):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    tenant, execution, letter = _probe_letter(db_schema, run, how.lower()[:6])
    letters, did = PostgresDeadLetters(db_schema.database()), letter["dead_letter_id"]
    before_runs, before_steps, _ = _statuses(db_schema, run, execution)
    if how == "abandon":
        run(letters.start_retry(tenant, did))
        run(letters.abandon(tenant, did))
    else:
        run(letters.resolve(tenant, did, how))
    after_runs, after_steps, _ = _statuses(db_schema, run, execution)
    assert (after_runs, after_steps) == (before_runs, before_steps)                # D4
    assert run(db_schema.fetchval("SELECT status FROM budget_reservations WHERE reservation_id = $1",
                                  letter["reservation_id"])) == budget
    assert _moves(db_schema, run, "reservation", letter["reservation_id"])[-1] == ("locked", budget, reason)
    run(assert_system_invariants(db_schema))


def test_resolving_a_record_of_a_failed_step_moves_no_budget(db_schema, run):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    state = _state("golden-dl-failedstep", "dlfailedstep")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {"call": "verify_mismatch"}})),
          tenant, execution)
    (letter,) = _letters(db_schema, run, execution)
    before = _statuses(db_schema, run, execution)
    run(PostgresDeadLetters(db_schema.database()).resolve(tenant, letter["dead_letter_id"], "EXECUTED"))
    assert _statuses(db_schema, run, execution) == before
    run(assert_system_invariants(db_schema))


# --- retry per retry_mode (D5) ---------------------------------------------------------------------------------------

class Answers:
    def __init__(self, *answers, raises=False):
        self.answers, self.raises, self.records = list(answers), raises, []

    async def __call__(self, record):
        self.records.append(record)
        if self.raises:
            raise RuntimeError("provider unreachable")
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def _retry(schema, run, tenant, did, probe, reverify):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from engine.stages.s14_dead_letter.retry import retry_dead_letter
    return run(retry_dead_letter(tenant, did, dead_letters=PostgresDeadLetters(schema.database()), probe=probe,
                                 reverify=reverify))


def test_a_probe_retry_calls_only_the_probe(db_schema, run):
    tenant, execution, letter = _probe_letter(db_schema, run, "rprobe")
    probe, reverify = Answers("EXECUTED_SUCCESS"), Answers("PASS")
    assert _retry(db_schema, run, tenant, letter["dead_letter_id"], probe, reverify) == "resolved"
    assert len(probe.records) == 1 and reverify.records == []
    assert probe.records[0].episode_id == letter["episode_id"]
    assert run(db_schema.fetchval("SELECT status FROM budget_reservations WHERE reservation_id = $1",
                                  letter["reservation_id"])) == "committed"
    run(assert_system_invariants(db_schema))


def test_a_probe_retry_that_finds_nothing_executed_releases_the_budget(db_schema, run):
    tenant, execution, letter = _probe_letter(db_schema, run, "rnotex")
    assert _retry(db_schema, run, tenant, letter["dead_letter_id"], Answers("NOT_EXECUTED"), Answers("PASS")) == \
        "resolved"
    assert run(db_schema.fetchval("SELECT status FROM budget_reservations WHERE reservation_id = $1",
                                  letter["reservation_id"])) == "released"
    run(assert_system_invariants(db_schema))


def test_a_verify_retry_calls_only_the_verifier(db_schema, run):
    state = _state("golden-dl-rverify", "dlrverify")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[0]
    mock = _mocked(**{_ops(state)[first]: {"call": "success", "observe": "inconclusive"}})
    _loop(db_schema, run, _dl_deps(db_schema, mock), tenant, execution)
    (letter,) = _letters(db_schema, run, execution)
    calls, probes = len(mock.calls), len(mock.probes)
    probe, reverify = Answers("EXECUTED_SUCCESS"), Answers("PASS")
    assert _retry(db_schema, run, tenant, letter["dead_letter_id"], probe, reverify) == "resolved"
    assert probe.records == [] and len(reverify.records) == 1
    assert (len(mock.calls), len(mock.probes)) == (calls, probes)          # the adapter and the probe: 0 calls
    run(assert_system_invariants(db_schema))


def test_a_record_without_retry_mode_is_never_retried(db_schema, run):
    state = _state("golden-dl-rnone", "dlrnone")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    _loop(db_schema, run, _dl_deps(db_schema, _mocked(**{_ops(state)[first]: {"call": "fail_500_then_success",
                                                                               "n": 9}})), tenant, execution)
    (letter,) = _letters(db_schema, run, execution)
    probe, reverify = Answers("EXECUTED_SUCCESS"), Answers("PASS")
    moves = _moves(db_schema, run, "dead_letter", letter["dead_letter_id"])
    with pytest.raises(ValueError):
        _retry(db_schema, run, tenant, letter["dead_letter_id"], probe, reverify)
    assert probe.records == reverify.records == []
    assert _moves(db_schema, run, "dead_letter", letter["dead_letter_id"]) == moves
    assert _letters(db_schema, run, execution)[0]["status"] == "pending"


def test_inconclusive_retries_end_abandoned_undetermined_with_the_budget_committed(db_schema, run):
    tenant, execution, letter = _probe_letter(db_schema, run, "rincon")
    did = letter["dead_letter_id"]
    results = [_retry(db_schema, run, tenant, did, Answers("INCONCLUSIVE"), Answers("PASS")),
               _retry(db_schema, run, tenant, did, Answers(raises=True), Answers("PASS")),
               _retry(db_schema, run, tenant, did, Answers("INCONCLUSIVE"), Answers("PASS"))]
    assert results == ["pending", "pending", "abandoned"]
    row = _letters(db_schema, run, execution)[0]
    assert (row["status"], row["resolution_outcome"], row["retry_count"], row["resolved"]) == (
        "abandoned", "UNDETERMINED", 3, True)
    assert run(db_schema.fetchval("SELECT status FROM budget_reservations WHERE reservation_id = $1",
                                  letter["reservation_id"])) == "committed"
    run(assert_system_invariants(db_schema))


# --- rollback (D2, C27) ----------------------------------------------------------------------------------------------

def _completed_run(schema, run, name, **programs):
    state = _state(f"golden-dl-rb-{name}", f"dlrb{name}")
    tenant, execution = _admit(schema, run, state)
    mock = _mocked(**programs)
    _loop(schema, run, _dl_deps(schema, mock), tenant, execution)
    assert run(schema.fetchval("SELECT status FROM execution_runs WHERE execution_id = $1", execution)) == "completed"
    return state, tenant, execution, mock


def _rollback(schema, run, tenant, execution, mock, *, confirmed=True):
    from adapters.postgres.dead_letters import PostgresDeadLetters
    from adapters.runtime.circuit_breaker import InProcessCircuitBreaker
    from adapters.runtime.reliability import (InProcessBilling, InProcessBulkhead, InProcessHealthMonitor,
                                              InProcessRetryStormGuard)
    from engine.stages.s12_execute.reliability import InverseBudget, ReliabilityGuard, TimeoutManager
    from engine.stages.s14_dead_letter.rollback import rollback_execution
    guard = ReliabilityGuard(mock, bulkhead=InProcessBulkhead(4), breaker=InProcessCircuitBreaker(50, 30.0),
                             budget=InverseBudget(), retry_storm=InProcessRetryStormGuard(100, 60.0),
                             timeouts=TimeoutManager(), health=InProcessHealthMonitor(), billing=InProcessBilling(),
                             probe_timeout_s=0.5)
    asked = []

    async def confirm(step):
        asked.append((step.plan_step_id, len(mock.calls)))
        return confirmed
    report = run(rollback_execution(tenant, execution, database=schema.database(), guard=guard,
                                    dead_letters=PostgresDeadLetters(schema.database()), confirm_executed=confirm))
    return report, asked


def _inverse_calls(mock, state):
    return [m for m in mock.calls if m.idempotency_key.endswith(":inverse")]


def test_rollback_confirms_then_compensates_each_undoable_step_through_the_guard(db_schema, run):
    state, tenant, execution, mock = _completed_run(db_schema, run, "ok")
    with_inverse = {b.kernel_op_id: b.inverse_kernel_op_id for b in state.frozen_bindings if b.inverse_kernel_op_id}
    undoable = [s.id for s in state.plan.plan.steps if s.kernel_op_id in with_inverse and s.mutation in ("W", "D")]
    before, calls = _statuses(db_schema, run, execution), len(mock.calls)
    report, asked = _rollback(db_schema, run, tenant, execution, mock)
    assert list(report.compensated) == list(reversed(undoable)) and report.failed == ()
    inverse = _inverse_calls(mock, state)
    assert [m.idempotency_key for m in inverse] == [f"{state.execution_context.request_id}:{sid}:inverse"
                                                    for sid in reversed(undoable)]
    assert all(n == calls + i for i, (_, n) in enumerate(asked))             # confirmed before each inverse call
    assert _statuses(db_schema, run, execution) == before                    # run, steps, budget unchanged
    again, _ = _rollback(db_schema, run, tenant, execution, mock)
    assert again.compensated == () and len(_inverse_calls(mock, state)) == len(undoable)       # never twice
    run(assert_system_invariants(db_schema))


def test_rollback_never_compensates_what_it_cannot_confirm(db_schema, run):
    state, tenant, execution, mock = _completed_run(db_schema, run, "unconfirmed")
    report, asked = _rollback(db_schema, run, tenant, execution, mock, confirmed=False)
    assert report.compensated == () and asked and _inverse_calls(mock, state) == []


def test_a_failed_inverse_becomes_a_rollback_dead_letter_and_changes_nothing_else(db_schema, run):
    state = _state("golden-dl-rb-fail", "dlrbfail")
    inverse_op = next(b.inverse_kernel_op_id for b in state.frozen_bindings if b.inverse_kernel_op_id)
    state, tenant, execution, mock = _completed_run(db_schema, run, "fail", **{inverse_op: {"call": "auth_401"}})
    before = _statuses(db_schema, run, execution)
    report, _ = _rollback(db_schema, run, tenant, execution, mock)
    assert report.compensated == () and len(report.failed) == 1
    (letter,) = _letters(db_schema, run, execution)
    assert (letter["origin"], letter["retry_mode"], letter["error_type"], letter["kernel_op_id"]) == (
        "rollback", "NONE", "permanent", inverse_op)
    assert _evidence(letter) and _statuses(db_schema, run, execution) == before
    run(assert_system_invariants(db_schema))


def test_rollback_never_compensates_an_irreversible_step(db_schema, run):
    state, tenant, execution, mock = _completed_run(db_schema, run, "irrev")
    undoable = [r for r in _steps(db_schema, run, execution).values() if r["undo_token"]]
    ids = [r["step_id"] for r in undoable]
    run(db_schema.execute("UPDATE execution_steps SET effective_mutation = 'IRREVERSIBLE'"
                          " WHERE step_id = ANY($1::text[])", ids))
    try:
        report, asked = _rollback(db_schema, run, tenant, execution, mock)
    finally:
        mutations = {b.kernel_op_id: b.effective_mutation for b in state.frozen_bindings}
        for r in undoable:
            op = run(db_schema.fetchval("SELECT kernel_op_id FROM execution_steps WHERE step_id = $1", r["step_id"]))
            run(db_schema.execute("UPDATE execution_steps SET effective_mutation = $2 WHERE step_id = $1",
                                  r["step_id"], mutations[op]))
    assert report.compensated == () and asked == [] and _inverse_calls(mock, state) == []


def test_rollback_refuses_a_run_that_is_not_terminal(db_schema, run):
    state = _state("golden-dl-rb-live", "dlrblive")
    tenant, execution = _admit(db_schema, run, state)
    mock = _mocked()
    with pytest.raises(ValueError):
        _rollback(db_schema, run, tenant, execution, mock)
    assert mock.calls == [] and _events(db_schema, run, execution) == []


def test_the_inverse_budget_layer_admits_only_inverse_calls_without_a_reservation():
    from contracts.adapter_interface import BudgetStateError, CallMeta, GuardedCall
    from engine.stages.s12_execute.reliability import InverseBudget
    from tests_golden.s12.M10_guard import _binding, _context

    def call(key, reservation):
        meta = CallMeta(idempotency_key=key, attempt_id="inv-0-1", provider_call_id="pc", tenant_id="golden-tenant")
        return GuardedCall(kernel_op_id="mock.op", params={}, binding=_binding(), context=_context(), call_meta=meta,
                           step_id="e:s1", reservation_id=reservation, attempt=1, timeout_s=1.0)

    import asyncio
    asyncio.run(InverseBudget().check(call("req:s1:inverse", None)))
    for key, reservation in (("req:s1", None), ("req:s1:inverse", "r-1")):
        with pytest.raises(BudgetStateError):
            asyncio.run(InverseBudget().check(call(key, reservation)))


def test_nothing_calls_rollback_automatically():
    from tests_golden.fixtures.code_scan import ROOT, s12_files
    home = "src/engine/stages/s14_dead_letter/rollback.py"
    callers = [p.relative_to(ROOT).as_posix() for p in s12_files()
               if p.relative_to(ROOT).as_posix() != home and "rollback_execution(" in p.read_text(encoding="utf-8")]
    assert callers == [] and (ROOT / home).exists()


def test_every_move_on_these_paths_is_legal(db_schema, run):
    run(assert_system_invariants(db_schema))
