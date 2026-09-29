"""S1 Normalize: sanitize the text; a high-severity injection stops the run."""
from __future__ import annotations

from supragents.contracts.outputs import NormalizedInput
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus
from supragents.pipeline.deps import PipelineDeps
from supragents.policy.sanitizer import MAX_TEXT_LENGTH, sanitize

STAGE = "S1"


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    sanitized = sanitize(state.entry_request.text)
    state = state.with_output(STAGE, normalized_input=NormalizedInput(
        text=sanitized.text,
        injection_detected=bool(sanitized.patterns),
        injection_patterns=sanitized.patterns,
        high_severity=sanitized.high_severity,
    ))
    if sanitized.high_severity:
        return state.halted(STAGE, StageStatus.DENY, "injection_detected")
    if not sanitized.text:
        return state.halted(STAGE, StageStatus.CLARIFY, "empty_request")
    if len(sanitized.text) > MAX_TEXT_LENGTH:
        return state.halted(STAGE, StageStatus.CLARIFY, "request_too_long")
    return state
