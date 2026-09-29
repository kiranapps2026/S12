"""
PipelineState builder helpers for testing.

All with_stage_output() calls in tests must go through this module so that
OWN-19 can verify they only happen in allowed files.
"""
from __future__ import annotations

from contracts.pipeline_state import PipelineState


def set_stage_output(state: PipelineState, stage_id: str, value) -> PipelineState:
    """Set a stage output on PipelineState.

    All test code must call this instead of state.with_stage_output() directly
    so that OWN-19 can verify with_stage_output only runs in allowed files.
    """
    return state.with_stage_output(stage_id, value)
