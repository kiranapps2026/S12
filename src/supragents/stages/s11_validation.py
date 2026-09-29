"""S11 Plan Validation: verify the frozen plan, then issue the ExecutionManifest.

S11 re-resolves nothing: it checks the plan against the S9 digest and the frozen S5
binding, and requires a consumed confirmation when S6 asked for one.
"""
from __future__ import annotations

from supragents.contracts.outputs import ConfirmationCheck, ExecutionManifest, FrozenBindingIdentity, Plan, ValidationResult
from supragents.contracts.plan_hash import plan_digest
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import ConfirmationStatus, StageStatus
from supragents.pipeline.deps import PipelineDeps
from supragents.stages.guards import deny_unless_safety_passed

STAGE = "S11"
_CONFIRMED = frozenset({ConfirmationStatus.CONSUMED, ConfirmationStatus.NOT_REQUIRED})


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    denied = deny_unless_safety_passed(state, STAGE)
    if denied is not None:
        return denied
    errors = plan_errors(state.plan_result.plan, state.plan_result.plan_hash, state.frozen_binding)
    errors += _confirmation_errors(state.confirmation_check)
    if errors:
        state = state.with_output(STAGE, validation_result=ValidationResult(is_valid=False, errors=tuple(errors)))
        return state.halted(STAGE, StageStatus.ERROR, "plan_invalid")
    return state.with_output(
        STAGE,
        validation_result=ValidationResult(is_valid=True, errors=()),
        execution_manifest=await _manifest(state, deps),
    )


def plan_errors(plan: Plan, plan_hash: str, binding: FrozenBindingIdentity) -> list[str]:
    errors = [] if plan_digest(plan) == plan_hash else ["plan_hash_mismatch"]
    step_ids = [step.id for step in plan.steps]
    if not plan.steps:
        errors.append("no_steps")
    if len(set(step_ids)) != len(step_ids):
        errors.append("duplicate_step_id")
    for step in plan.steps:
        errors += [f"unknown_dependency:{step.id}:{dep}" for dep in step.depends_on if dep not in step_ids]
        if step.kernel_op_id != binding.kernel_op_id:
            errors.append(f"unbound_kernel_op:{step.id}")
        if step.cost <= 0 or step.timeout_seconds <= 0:
            errors.append(f"invalid_limits:{step.id}")
    if _has_cycle(plan):
        errors.append("circular_dependency")
    if plan.budget_required != sum(step.cost for step in plan.steps):
        errors.append("budget_mismatch")
    return errors


def _has_cycle(plan: Plan) -> bool:
    """Depth-first search; dependencies outside the plan are reported separately."""
    graph = {step.id: step.depends_on for step in plan.steps}
    visiting: set[str] = set()
    finished: set[str] = set()

    def visit(step_id: str) -> bool:
        if step_id in finished or step_id not in graph:
            return False
        if step_id in visiting:
            return True
        visiting.add(step_id)
        cyclic = any(visit(dependency) for dependency in graph[step_id])
        visiting.discard(step_id)
        finished.add(step_id)
        return cyclic

    return any(visit(step_id) for step_id in graph)


def _confirmation_errors(check: ConfirmationCheck) -> list[str]:
    return [] if check.status in _CONFIRMED else ["confirmation_missing"]


async def _manifest(state: PipelineState, deps: PipelineDeps) -> ExecutionManifest:
    context = state.execution_context
    versions = await deps.registry.versions()
    return ExecutionManifest(
        execution_id=state.plan_result.plan.execution_id,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
        plan_hash=state.plan_result.plan_hash,
        binding_id=state.frozen_binding.binding_id,
        auth_result_id=context.auth_result_id,
        capability_version=versions.capability_version,
        binding_version=versions.binding_version,
        policy_version=context.policy_version_id,
        risk_policy_version=versions.risk_policy_version,
        authorization_version=versions.authorization_version,
        worker_runtime_version=versions.worker_runtime_version,
        model_version=versions.model_version,
        created_at=await deps.clock.now(),
    )
