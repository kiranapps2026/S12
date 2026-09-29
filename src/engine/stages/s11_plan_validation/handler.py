"""
S11 Plan Validation — validate the execution plan and issue the ExecutionManifest.

Source: DATA_CONTRACTS.md §4, PIPELINE_STAGES.md §13, RUNBOOK R-N/R-S
Owner: S11 / Plan Validation

Checks, in order, after the R-N safety precondition (first failure decides):
  1. every Step.kernel_op_id / risk / mutation equals the frozen binding -> binding_mismatch
  2. plan digest equals the S9 plan_hash                                 -> plan_hash_mismatch
  3. required confirmation was consumed and its plan_hash matches        -> confirmation_mismatch
  4. budget_reserved >= 0                                                -> budget_invalid
  5. step dependencies form an acyclic graph over known steps            -> dag_invalid
  6. at least one step                                                   -> plan_empty
Denial: ValidationResult(False, (code,)), execution_manifest None, status DENY (code).
"""
from __future__ import annotations

import logging
import time

from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import ValidationResult
from contracts.execution_manifest import ExecutionManifest
from contracts.plan_hash import canonical_plan_digest
from contracts.stage_registry import StageStatus
from engine.stages.preconditions import deny_unless_safety_passed

logger = logging.getLogger(__name__)


def _dag_ok(steps) -> bool:
    ids = {s.id for s in steps}
    if len(ids) != len(steps):
        return False
    deps = {s.id: tuple(s.depends_on) for s in steps}
    if any(d not in ids for ds in deps.values() for d in ds):
        return False
    state: dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(node: str) -> bool:
        if state.get(node) == 2:
            return True
        if state.get(node) == 1:
            return False
        state[node] = 1
        if not all(visit(d) for d in deps[node]):
            return False
        state[node] = 2
        return True

    return all(visit(n) for n in ids)


def _first_error(state: PipelineState) -> str | None:
    plan_result, frozen = state.plan, state.frozen_binding_identity
    if plan_result is None or frozen is None:
        return "binding_mismatch"
    plan = plan_result.plan

    for step in plan.steps:
        if (step.kernel_op_id != frozen.kernel_op_id
                or step.risk != frozen.effective_risk
                or step.mutation != frozen.effective_mutation):
            return "binding_mismatch"

    if canonical_plan_digest(plan) != plan_result.plan_hash:
        return "plan_hash_mismatch"

    outcome = state.confirmation
    if outcome is None:
        return "confirmation_mismatch"
    if outcome.required:
        c = outcome.confirmation
        if c is None or c.consumed_at is None or c.plan_hash != plan_result.plan_hash:
            return "confirmation_mismatch"

    if plan.budget_reserved < 0:
        return "budget_invalid"
    if not _dag_ok(plan.steps):
        return "dag_invalid"
    if not plan.steps:
        return "plan_empty"
    return None


async def handle(state: PipelineState) -> PipelineState:
    """S11 handler. Never raises for a refused plan."""
    refused = deny_unless_safety_passed(state)
    if refused is not None:
        return refused

    error = _first_error(state)
    if error is not None:
        logger.warning("S11: DENY %s", error)
        state = state.with_stage_output(
            "S11",
            execution_manifest=None,
            validation_result=ValidationResult(is_valid=False, errors=(error,)),
        )
        return state.with_status(StageStatus.DENY, error)

    ctx, frozen, plan_result = state.execution_context, state.frozen_binding_identity, state.plan
    manifest = ExecutionManifest(
        execution_id=plan_result.execution_id,
        trace_id=ctx.trace_id,
        plan_hash=plan_result.plan_hash,
        capability_version=frozen.capability_version,
        binding_version=frozen.binding_version,
        policy_version=ctx.policy_version_id or "",
        risk_policy_version=frozen.risk_policy_version,
        authorization_version=frozen.authorization_version,
        auth_result_id=ctx.auth_result_id,
        created_at=time.time(),
    )
    return state.with_stage_output(
        "S11",
        execution_manifest=manifest,
        validation_result=ValidationResult(is_valid=True, errors=()),
    )
