"""Ruling R-N: S9, S10 and S11 run only after S8 allowed and recorded auth_passed."""
from __future__ import annotations

from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus


def deny_unless_safety_passed(state: PipelineState, stage: str) -> PipelineState | None:
    """Return a halted state if S8 did not allow the run, else None."""
    safety = state.safety_result
    context = state.execution_context
    if safety is not None and safety.allowed and context is not None and context.auth_passed:
        return None
    return state.halted(stage, StageStatus.DENY, "safety_not_passed")
