"""S6 Task Profile: assemble cost and the confirmation requirement from frozen S5 values."""
from __future__ import annotations

from supragents.contracts.outputs import TaskProfile
from supragents.contracts.state import PipelineState
from supragents.pipeline.deps import PipelineDeps
from supragents.policy.confirmation_rules import requires_confirmation

STAGE = "S6"


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    binding = state.frozen_binding
    graph = state.graph_analysis
    total_cost = binding.cost_per_step * graph.step_count
    providers = (binding.provider,)
    return state.with_output(STAGE, task_profile=TaskProfile(
        intent=state.intent_result.intent,
        capability_ids=(binding.capability_id,),
        graph_type=graph.graph_type,
        steps_estimated=graph.step_count,
        mutations=(binding.effective_mutation,) * graph.step_count,
        risk=binding.effective_risk,
        cost=total_cost,
        requires_confirmation=requires_confirmation(
            binding.effective_mutation, binding.effective_risk, total_cost, len(providers)
        ),
        resource_scope=state.execution_context.resource_scope,
        providers=providers,
    ))
