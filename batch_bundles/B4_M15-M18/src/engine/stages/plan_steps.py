"""Which binding each plan step runs (multi-capability plans, M2a, R-AB).

S4 numbers the plan's steps and records, for each, the index of the intent step (and so of the
S3 match and S5 binding) it belongs to. S6, S9 and S11 all read that one mapping, so a step can
never be built with, or validated against, another step's binding.
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts.frozen_binding import FrozenBindingIdentity
from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import CapabilityMatch


@dataclass(frozen=True)
class PlanStepBinding:
    step_data: dict                      # S4's execution step (step_id, params, depends_on, ...)
    binding: FrozenBindingIdentity
    match: CapabilityMatch


def plan_step_bindings(state: PipelineState) -> tuple[PlanStepBinding, ...] | None:
    """One entry per plan step, in plan order. None if the mapping is missing or inconsistent
    (a step index outside the bindings, or bindings and matches of different lengths): callers
    treat that as a refusal."""
    graph = state.graph_analysis
    bindings, matches = state.bindings, state.matches
    if graph is None or not graph.execution_steps or not bindings or len(bindings) != len(matches):
        return None
    out = []
    for step_data in graph.execution_steps:
        index = step_data.get("binding_index", 0)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(bindings):
            return None
        if bindings[index].capability_id != matches[index].capability_id:
            return None
        out.append(PlanStepBinding(step_data, bindings[index], matches[index]))
    return tuple(out)
