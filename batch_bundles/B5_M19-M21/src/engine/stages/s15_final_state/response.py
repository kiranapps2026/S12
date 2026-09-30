"""S15 response (gate §12, §21 S6; FINAL_ARCHITECTURE I-018; SECURITY §7).

Pure: a terminal run's summary to the user's envelope. Only codes, positions, operation names and states go in, so
no exception text, stack trace, provider body, credential or internal id can come out; the only id is ``trace_id``
(in ``metadata``). Messages come from fixed text per reason, with the negative-path matrix wording where a row
applies (PIPELINE_STAGES §19).
"""
from __future__ import annotations

import types
from dataclasses import dataclass

from contracts.envelope import Envelope, EnvelopeError
from contracts.execution_states import ExecutionStatus as R
from contracts.execution_states import StepState as S
from contracts.execution_states import StepTerminalReason as T


@dataclass(frozen=True)
class StepSummary:
    position: int                    # 1-based plan position
    operation: str                   # kernel operation name
    status: str
    terminal_reason: str | None = None


@dataclass(frozen=True)
class RunSummary:
    run_status: str
    terminal_reason: str | None
    trace_id: str
    steps: tuple[StepSummary, ...]


_CANCELLED = types.MappingProxyType({
    T.BUDGET_EXHAUSTED: ("budget_exceeded", "Budget limit reached — upgrade or reduce scope",
                         "Increase budget or use a simpler request"),
    T.USER_CANCELLED: ("execution_failed", "The request was cancelled.", None),
    T.CREDENTIAL_INVALID: ("unauthorized", "Authentication failed — check credentials", "Reconnect the account"),
    T.AUTHORIZATION_REVOKED: ("unauthorized", "Access to this operation was withdrawn while it ran.",
                              "Request access from admin"),
    T.KILL_SWITCH_ENGAGED: ("execution_failed", "Execution is paused for this account.", "Contact support"),
    T.BINDING_INVALID: ("provider_unavailable", "The provider for this operation is no longer available.",
                        "Try again later"),
})
_STEP_MESSAGES = types.MappingProxyType({
    T.NO_WORKER: "No worker is available for this task right now",
    T.ADMISSION_EXHAUSTED: "Service is busy — please retry later",
})


def _public(step: StepSummary) -> dict:
    return {"position": step.position, "operation": step.operation, "status": step.status}


def _where(summary: RunSummary, *states) -> list[dict]:
    return [_public(s) for s in summary.steps if s.status in states]


def build_envelope(summary: RunSummary) -> Envelope:
    meta = {"trace_id": summary.trace_id}
    status = summary.run_status
    if status == R.COMPLETED:
        return Envelope("ok", data={"steps": _where(summary, S.COMPLETED)}, message="Done.", metadata=meta)
    if status == R.PARTIAL:
        return Envelope("partial", data={"steps": _where(summary, S.COMPLETED)},
                        message="Some steps did not complete.", metadata=meta,
                        error=EnvelopeError("partial_execution", "Some steps did not complete.",
                                            details={"failed_steps": _where(summary, S.FAILED, S.CANCELLED)},
                                            recoverable=True, suggested_action="Review failed steps"))
    if status == R.CANCELLED:
        kind, message, action = _CANCELLED.get(summary.terminal_reason,
                                               ("execution_failed", "The request was stopped.", None))
        return Envelope("error", message=message, metadata=meta,
                        error=EnvelopeError(kind, message, details={"completed_steps": _where(summary, S.COMPLETED)},
                                            recoverable=True, suggested_action=action))
    if status == R.DEAD_LETTER:
        message = "We could not confirm what happened; the request has been flagged for review."
        return Envelope("error", message=message, metadata=meta,
                        error=EnvelopeError("execution_failed", message,
                                            details={"completed_steps": _where(summary, S.COMPLETED)},
                                            recoverable=False, suggested_action="Wait for review"))
    if status == R.FAILED:
        reasons = {s.terminal_reason for s in summary.steps}
        message = next((_STEP_MESSAGES[r] for r in _STEP_MESSAGES if r in reasons), "The request could not be completed.")
        return Envelope("error", message=message, metadata=meta,
                        error=EnvelopeError("execution_failed", message,
                                            details={"failed_steps": _where(summary, S.FAILED, S.CANCELLED)},
                                            recoverable=True, suggested_action="Check error details"))
    raise ValueError(f"run status {status!r} is not terminal: no response yet")
