"""
Shared stage preconditions (R-N).

S9, S10 and S11 each check, as their first action, that S8 allowed the request and
recorded the authorization on the ExecutionContext. A runner bug must not be able to
plan, confirm or manifest an unauthorized request.
"""
from __future__ import annotations

from contracts.pipeline_state import PipelineState
from contracts.stage_registry import StageStatus

SAFETY_NOT_PASSED = "safety_not_passed"


def safety_passed(state: PipelineState) -> bool:
    sr = state.safety_result
    ctx = state.execution_context
    return (
        sr is not None
        and sr.allowed is True
        and ctx is not None
        and ctx.auth_passed is True
    )


def deny_unless_safety_passed(state: PipelineState) -> PipelineState | None:
    """Return a DENY state (no output written, never raises) or None when safe."""
    if safety_passed(state):
        return None
    return state.with_status(StageStatus.DENY, SAFETY_NOT_PASSED)
