"""M18 golden — the S15 response and redaction (gate commit K). Owner-pinned.

Gate v10: §12 (COMPLETED → ``ok``, PARTIAL → ``partial`` listing the failed or cancelled steps, FAILED / CANCELLED /
DEAD_LETTER → ``error``; a CANCELLED run's envelope also lists the steps that completed before the cancellation; never
raw exception text, stack traces, provider response bodies, secrets, tokens or internal ids other than ``trace_id``;
the negative-path matrix wording where a row applies), §21 S6 (credentials only through the CredentialProvider, never
persisted or logged), suite 12, FINAL_ARCHITECTURE I-018, SECURITY §7, PIPELINE_STAGES §19 (matrix rows "Budget
exhausted", "No eligible worker"). Rulings: CONF-039 (a user cancellation has no envelope error type in DATA_CONTRACTS:
``execution_failed`` with a cancellation message).

Interface this file fixes:
  * ``contracts.envelope``: ``Envelope(status, data=None, message=None, error=None, metadata=None)`` and
    ``EnvelopeError(type, message, details=None, recoverable=True, suggested_action=None)`` (DATA_CONTRACTS).
  * ``engine.stages.s15_final_state.response``: ``StepSummary(position, operation, status, terminal_reason=None)``,
    ``RunSummary(run_status, terminal_reason, trace_id, steps)``, ``build_envelope(summary) -> Envelope`` — pure; a
    listed step is ``{"position", "operation", "status"}`` (1-based plan position, kernel operation); ``ok`` has
    ``data["steps"]`` (the completed steps); ``partial`` has ``data["steps"]`` and ``error.type ==
    "partial_execution"`` with ``details["failed_steps"]``; a CANCELLED run has ``error.details["completed_steps"]``,
    ``budget_exhausted`` → ``error.type == "budget_exceeded"`` with the matrix message; a FAILED run whose steps
    ended ``no_worker`` has the matrix message; DEAD_LETTER is ``error`` with ``recoverable`` False;
    ``metadata == {"trace_id": ...}``; a run that is not terminal raises ValueError.
  * ``adapters.postgres.run_summary.PostgresRunSummaries(database).load(tenant_id, execution_id) -> RunSummary |
    None`` (steps in plan order).
  * Redaction across the pipeline: an exception text, a stack trace, a provider error body and the credential never
    reach the envelope, a log record, a dead letter's evidence or any persisted row (the idempotency ledger stores a
    failure's class, not its body).
"""
from __future__ import annotations

import json
import logging

import pytest

from tests_golden.fixtures.invariants import assert_system_invariants
from tests_golden.s12.M12_loop import _admit, _loop, _order, _ops, _state

SECRET = "sk-golden-live-9f3a7d"
TRACE = "Traceback (most recent call last)"
BODY = {"message": f"invalid token {SECRET}", "debug": f"{TRACE}\n  File \"api.py\", line 7"}


def _summary(run_status, steps, terminal_reason=None):
    from engine.stages.s15_final_state.response import RunSummary, StepSummary
    return RunSummary(run_status, terminal_reason, "golden-trace-1",
                      tuple(StepSummary(i + 1, f"op.{i + 1}", status, reason)
                            for i, (status, reason) in enumerate(steps)))


def _listed(*positions_and_status):
    return [{"position": p, "operation": f"op.{p}", "status": s} for p, s in positions_and_status]


# --- the mapping (§12) -----------------------------------------------------------------------------------------------

def test_a_completed_run_is_ok_with_its_steps_and_only_the_trace_id():
    from engine.stages.s15_final_state.response import build_envelope
    env = build_envelope(_summary("completed", [("completed", None), ("completed", None)]))
    assert (env.status, env.error, env.metadata) == ("ok", None, {"trace_id": "golden-trace-1"})
    assert env.data == {"steps": _listed((1, "completed"), (2, "completed"))} and env.message


def test_a_partial_run_lists_the_failed_and_cancelled_steps():
    from engine.stages.s15_final_state.response import build_envelope
    env = build_envelope(_summary("partial", [("completed", None), ("failed", None), ("skipped", "dependency_failed"),
                                              ("cancelled", "admission_rejected")]))
    assert env.status == "partial" and env.error.type == "partial_execution" and env.error.recoverable is True
    assert env.data == {"steps": _listed((1, "completed"))}
    assert env.error.details == {"failed_steps": _listed((2, "failed"), (4, "cancelled"))}


@pytest.mark.parametrize("reason,kind,message", [
    ("budget_exhausted", "budget_exceeded", "Budget limit reached — upgrade or reduce scope"),
    ("user_cancelled", "execution_failed", None),
    ("authorization_revoked", "unauthorized", None),
])
def test_a_cancelled_run_is_an_error_that_lists_what_already_completed(reason, kind, message):
    from engine.stages.s15_final_state.response import build_envelope
    env = build_envelope(_summary("cancelled", [("completed", None), ("cancelled", reason), ("cancelled", reason)],
                                  terminal_reason=reason))
    assert (env.status, env.error.type) == ("error", kind) and env.data is None
    assert env.error.details == {"completed_steps": _listed((1, "completed"))}
    if message is not None:
        assert env.message == env.error.message == message


def test_no_eligible_worker_uses_the_matrix_wording():
    from engine.stages.s15_final_state.response import build_envelope
    env = build_envelope(_summary("failed", [("cancelled", "no_worker"), ("cancelled", "no_worker")]))
    assert env.status == "error" and env.message == "No worker is available for this task right now"


def test_a_dead_lettered_run_is_an_unrecoverable_error():
    from engine.stages.s15_final_state.response import build_envelope
    env = build_envelope(_summary("dead_letter", [("completed", None), ("dead_letter", None),
                                                  ("cancelled", "run_dead_lettered")]))
    assert env.status == "error" and env.error.recoverable is False
    assert env.error.details == {"completed_steps": _listed((1, "completed"))}


@pytest.mark.parametrize("status", ["pending", "running", "reconciling"])
def test_a_run_that_is_not_terminal_has_no_response(status):
    from engine.stages.s15_final_state.response import build_envelope
    with pytest.raises(ValueError):
        build_envelope(_summary(status, [("pending", None)]))


# --- end to end: summaries and redaction (§12, §21 S6, suite 12) -----------------------------------------------------

class SecretCredentials:
    async def credential(self, tenant_id, connection_id):
        return SECRET

    async def credential_valid(self, tenant_id, connection_id):
        return True


def _secret_mock(**programs):
    from adapters.runtime.mock_adapter import MockAdapter
    mock = MockAdapter(SecretCredentials())
    for op, program in programs.items():
        mock.program(op, **program)
    return mock


def _full(schema, mock):
    from tests_golden.s12.M17_dead_letter import _dl_deps
    return _dl_deps(schema, mock)


def _envelope(schema, run, tenant, execution):
    from adapters.postgres.run_summary import PostgresRunSummaries
    from engine.stages.s15_final_state.response import build_envelope
    summary = run(PostgresRunSummaries(schema.database()).load(tenant, execution))
    return summary, build_envelope(summary)


def test_the_summary_follows_the_plan_and_the_envelope_holds_no_internal_id(db_schema, run):
    state = _state("golden-resp-ids", "respids")
    tenant, execution = _admit(db_schema, run, state)
    first = _order(state)[1]
    _loop(db_schema, run, _full(db_schema, _secret_mock(**{_ops(state)[first]: {"call": "auth_401"}})),
          tenant, execution)
    summary, env = _envelope(db_schema, run, tenant, execution)
    assert [s.operation for s in summary.steps] == [s.kernel_op_id for s in state.plan.plan.steps]
    assert [s.position for s in summary.steps] == [1, 2, 3] and summary.run_status == "partial"
    assert env.status == "partial" and env.metadata == {"trace_id": state.execution_context.trace_id}
    ctx = state.execution_context
    step_ids = [r["step_id"] for r in run(db_schema.fetch("SELECT step_id FROM execution_steps WHERE"
                                                           " execution_id = $1", execution))]
    reservations = [r["reservation_id"] for r in run(db_schema.fetch(
        "SELECT reservation_id FROM budget_reservations WHERE execution_id = $1", execution))]
    text = repr(env)
    for internal in [execution, ctx.request_id, ctx.tenant_id, ctx.user_id, ctx.workspace_id, "runtime-A",
                     *step_ids, *reservations]:
        assert internal not in text, internal
    from adapters.postgres.run_summary import PostgresRunSummaries
    assert run(PostgresRunSummaries(db_schema.database()).load("golden-some-other-tenant", execution)) is None


_TABLES = ("execution_runs", "execution_steps", "execution_events", "idempotency_ledger", "dead_letters",
           "state_transitions", "step_reconciliations", "budget_reservations", "execution_plans")


def _persisted(schema, run, tenant):
    text = []
    for table in _TABLES:
        text += [r["row"] for r in run(schema.fetch(f"SELECT row_to_json(t)::text AS row FROM {table} t"
                                                    " WHERE t.tenant_id = $1", tenant))]
    return "\n".join(text)


@pytest.mark.parametrize("name,program", [
    ("defect", {"call": "raise_exception"}),
    ("body", {"call": "auth_401", "body": BODY}),
    ("exhausted", {"call": "fail_500_then_success", "n": 9, "body": BODY}),
])
def test_secrets_traces_and_provider_bodies_reach_no_envelope_log_or_row(db_schema, run, caplog, name, program):
    state = _state(f"golden-resp-redact-{name}", f"resp{name}")
    tenant, execution = _admit(db_schema, run, state, retry_safety="safe")
    first = _order(state)[0]
    caplog.set_level(logging.DEBUG)
    mock = _secret_mock(**{_ops(state)[first]: program})
    _loop(db_schema, run, _full(db_schema, mock), tenant, execution)
    assert mock.calls                                                          # the leak really was offered
    _, env = _envelope(db_schema, run, tenant, execution)
    stored = _persisted(db_schema, run, tenant)
    logs = caplog.text + "\n".join(json.dumps(getattr(r, "__dict__", {}), default=repr) for r in caplog.records)
    for leak in (SECRET, TRACE, "invalid token", "api.py"):
        assert leak not in repr(env), leak
        assert leak not in stored, leak
        assert leak not in logs, leak
    if name == "exhausted":
        assert run(db_schema.fetchval("SELECT count(*) FROM dead_letters WHERE execution_id = $1", execution)) == 1
    run(assert_system_invariants(db_schema))
