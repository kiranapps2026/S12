"""RunResult → Envelope (DATA_CONTRACTS §1). The interface never sees raw pipeline state."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from supragents.contracts.codec import encode
from supragents.contracts.outputs import Confirmation
from supragents.contracts.vocabulary import StageStatus
from supragents.pipeline.result import RunOutcome, RunResult

_STATUS = MappingProxyType({StageStatus.CLARIFY: "clarify", StageStatus.DENY: "deny", StageStatus.ERROR: "error"})
# reason → (envelope error type, recoverable, message shown to the user)
_REASONS = MappingProxyType({
    "injection_detected": ("injection_detected", False, "This request was blocked for safety reasons."),
    "no_capability": ("unknown_capability", True, "I don't know how to do that yet. Can you rephrase?"),
    "low_confidence": ("validation_error", True, "I'm not sure what you mean. Can you tell me more?"),
    "budget_exceeded": ("budget_exceeded", True, "Your budget is not sufficient for this request."),
    "circuit_open": ("circuit_open", True, "The provider is temporarily unavailable. Try again shortly."),
    "capability_denied": ("unauthorized", True, "You don't have permission for this. Ask an admin."),
    "confirmation_expired": ("confirmation_expired", True, "The confirmation expired. Please start again."),
    "confirmation_rejected": ("execution_failed", True, "Cancelled: nothing was changed."),
    "plan_invalid": ("plan_error", False, "The plan failed validation. Please report this."),
    "llm_unavailable": ("provider_unavailable", True, "The language model is unavailable. Try again later."),
})


@dataclass(frozen=True)
class EnvelopeError:
    type: str
    message: str
    recoverable: bool = True


@dataclass(frozen=True)
class Envelope:
    status: str
    message: str | None = None
    data: dict[str, Any] | None = None
    error: EnvelopeError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return encode(self)


def failure(error_type: str, message: str, recoverable: bool = True) -> Envelope:
    return Envelope(status="error", message=message, error=EnvelopeError(error_type, message, recoverable))


def from_result(result: RunResult) -> Envelope:
    context = result.state.execution_context
    metadata = {"trace_id": context.trace_id if context else None}
    if result.outcome is RunOutcome.COMPLETED:
        return Envelope(status="ok", message="Plan validated and ready for execution.",
                        data={"manifest": encode(result.manifest)}, metadata=metadata)
    if result.outcome is RunOutcome.AWAITING_CONFIRMATION:
        return _confirm(result.pending_confirmation, metadata)
    return _stopped(result, metadata)


def _confirm(confirmation: Confirmation, metadata: dict[str, Any]) -> Envelope:
    lines = [f"{i}. {op['kernel_op_id']} ({op['mutation']}, cost {op['cost']})"
             for i, op in enumerate(confirmation.operations, start=1)]
    message = "This will:\n" + "\n".join(lines) + "\n\nReply YES to confirm or NO to cancel."
    data = {"confirmation_id": confirmation.confirmation_id, "expires_at": confirmation.expires_at,
            "operations": encode(confirmation.operations)}
    return Envelope(status="confirm", message=message, data=data, metadata=metadata)


def _stopped(result: RunResult, metadata: dict[str, Any]) -> Envelope:
    halt = result.halt
    error_type, recoverable, message = _REASONS.get(
        halt.reason, ("execution_failed", True, f"The request stopped at {halt.stage}: {halt.reason}."))
    status = _STATUS[halt.status]
    error = EnvelopeError(error_type, message, recoverable) if status == "error" else None
    return Envelope(status=status, message=message, error=error,
                    metadata={**metadata, "stage": halt.stage, "reason": halt.reason})
