"""S9 Plan Creation: build the step chain and freeze it with its SHA-256 digest.

S9 generates execution_id and plan_id. It does not reserve budget (S12 does).
"""
from __future__ import annotations

import uuid

from supragents.contracts.outputs import FrozenBindingIdentity, GraphAnalysis, Plan, PlanCreationResult, Step
from supragents.contracts.plan_hash import plan_digest
from supragents.contracts.state import PipelineState
from supragents.pipeline.deps import PipelineDeps
from supragents.stages.guards import deny_unless_safety_passed

STAGE = "S9"
JOIN_MODE = "all"


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    denied = deny_unless_safety_passed(state, STAGE)
    if denied is not None:
        return denied
    steps = _steps(state.graph_analysis, state.frozen_binding)
    plan = Plan(
        id=str(uuid.uuid4()),
        execution_id=str(uuid.uuid4()),
        steps=steps,
        join_mode=JOIN_MODE,
        budget_required=sum(step.cost for step in steps),
        created_at=deps.clock.now(),
    )
    return state.with_output(STAGE, plan_result=PlanCreationResult(plan=plan, plan_hash=plan_digest(plan)))


def _steps(graph: GraphAnalysis, binding: FrozenBindingIdentity) -> tuple[Step, ...]:
    """One step per entry of step_params; step n depends on step n-1."""
    return tuple(
        Step(
            id=f"step-{index}",
            kernel_op_id=binding.kernel_op_id,
            params=params,
            depends_on=() if index == 1 else (f"step-{index - 1}",),
            mutation=binding.effective_mutation,
            risk=binding.effective_risk,
            cost=binding.cost_per_step,
            timeout_seconds=binding.timeout_seconds,
            retry_safety=binding.retry_safety,
            inverse=binding.inverse,
        )
        for index, params in enumerate(graph.step_params, start=1)
    )
