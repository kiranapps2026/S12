"""
S9 Plan Creation — create the execution plan with all steps.

Source: DATA_CONTRACTS.md §4, PIPELINE_STAGES.md §11
Owner: S9 / Plan Creation

S9 produces a PlanCreationResult containing:
- plan: Plan matching DATA_CONTRACTS §4 field-for-field (no execution_id,
  no plan_hash inside the Plan)
- plan_hash: SHA-256 of the canonical Plan digest
- execution_id: distinct from request_id

S9 does NOT reserve budget — reservation happens at S12.
S9 does NOT acquire locks — lock acquisition is an S12 concern.
"""

from __future__ import annotations

import logging
import time
import uuid

from contracts.pipeline_state import PipelineState
from contracts.safety import TaskProfile, PathDecision
from contracts.stage_outputs import Plan, Step, PlanCreationResult
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_registry import StageStatus
from engine.stages.plan_steps import plan_step_bindings
from engine.stages.preconditions import deny_unless_safety_passed

logger = logging.getLogger(__name__)


async def handle(state: PipelineState) -> PipelineState:
    """
    S9 handler: create the execution Plan.

    Reads TaskProfile (S6) and PathDecision (S7) from PipelineState.
    Produces PlanCreationResult containing Plan, plan_hash, and execution_id.

    Returns updated PipelineState with plan set.
    """
    refused = deny_unless_safety_passed(state)  # R-N
    if refused is not None:
        return refused

    task_profile = state.task_profile
    path_decision = state.path_decision
    frozen = state.frozen_binding_identity

    if task_profile is None:
        raise ValueError("No TaskProfile from S6")
    if path_decision is None:
        raise ValueError("No PathDecision from S7")
    chain = None
    if frozen is None:
        chain = plan_step_bindings(state)       # multi-capability plan (M2a): one binding per step
        if chain is None:
            return state.with_status(StageStatus.DENY, "binding_mismatch")

    now = time.time()
    # S9 generates NEW UUIDs — distinct from request_id (which is from S0)
    execution_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())

    # Build steps from graph analysis if available, otherwise single step. Each step carries
    # the per-step cost (task cost / steps) so the step costs add up to the reserved budget.
    graph_analysis = state.graph_analysis
    steps: list[Step] = []
    n_steps = max(1, task_profile.steps_estimated)
    per_step_cost = task_profile.cost // n_steps
    if chain is not None and sum(i.match.estimated_cost_units for i in chain) != task_profile.cost:
        return state.with_status(StageStatus.DENY, "binding_mismatch")   # S6 and S9 must agree

    if chain is not None:
        # Every step carries ITS OWN binding's operation, mutation, risk and inverse and its own
        # registry cost (R-AB, R-AF); the parameters are S4's, bound here and covered by plan_hash (R-AE).
        for item in chain:
            steps.append(Step(
                id=item.step_data["step_id"],
                kernel_op_id=item.binding.kernel_op_id,
                params=dict(item.step_data.get("params", {})),
                depends_on=tuple(item.step_data.get("depends_on", [])),
                mutation=item.binding.effective_mutation,
                risk=item.binding.effective_risk,
                cost=item.match.estimated_cost_units,
                retry_policy=item.step_data.get("retry_policy", {}),
                inverse=item.binding.inverse_kernel_op_id,
            ))
    elif graph_analysis and graph_analysis.execution_steps:
        for step_data in graph_analysis.execution_steps:
            step = Step(
                id=step_data.get("step_id", f"step-{len(steps) + 1}"),
                kernel_op_id=frozen.kernel_op_id,
                params=step_data.get("params", {}),
                depends_on=tuple(step_data.get("depends_on", [])),
                mutation=frozen.effective_mutation,
                risk=frozen.effective_risk,
                cost=per_step_cost,
                retry_policy=step_data.get("retry_policy", {}),
                inverse=frozen.inverse_kernel_op_id,
            )
            steps.append(step)

    if not steps:
        # Single-step plan
        steps.append(Step(
            id="step-1",
            kernel_op_id=frozen.kernel_op_id,
            params={},
            depends_on=(),
            mutation=frozen.effective_mutation,
            risk=frozen.effective_risk,
            cost=per_step_cost,
            retry_policy={},
            inverse=frozen.inverse_kernel_op_id,
        ))

    # Branch ID: only for AGENTIC path; None for FAST/WORKFLOW
    branch_id = None
    if path_decision == PathDecision.AGENTIC:
        branch_id = str(uuid.uuid4())

    # Build the spec-conformant Plan (DATA_CONTRACTS §4)
    plan = Plan(
        id=plan_id,
        steps=tuple(steps),
        join_mode="all",
        budget_reserved=task_profile.cost if task_profile else 1,
        created_at=now,
        confirmations=(),
    )

    # Compute plan_hash over the spec-conformant Plan
    plan_hash = canonical_plan_digest(plan)

    # Package into PlanCreationResult (execution_id and plan_hash beside Plan)
    result = PlanCreationResult(
        plan=plan,
        plan_hash=plan_hash,
        execution_id=execution_id,
    )

    logger.info(
        "S9: created plan %s for execution %s (hash=%s, steps=%d)",
        plan.id,
        execution_id,
        plan_hash[:16],
        len(plan.steps),
    )

    return state.with_stage_output("S9", result)
