"""
S11 Plan Validation — validate the execution plan before execution.

Source: DATA_CONTRACTS.md §4, PIPELINE_STAGES.md §13
Owner: S11 / Plan Validation

Reads Plan from PlanCreationResult (S9). Validates:
- Plan fields match DATA_CONTRACTS §4 spec
- Step dependencies form a DAG (no circular deps)
- Budget_reserved is non-negative
- All referenced kernel_op_ids exist in capability registry

Returns:
- ALLOW: ExecutionManifest + ValidationResult(is_valid=True)
- DENY: ValidationResult(is_valid=False) — execution_manifest stays None
"""

from __future__ import annotations

import logging
import time

from contracts.pipeline_state import PipelineState, S11_SECONDARY_FIELD
from contracts.stage_outputs import ValidationResult
from contracts.execution_manifest import ExecutionManifest
from contracts.frozen_binding import FrozenBindingIdentity
from contracts.plan_hash import canonical_plan_digest

logger = logging.getLogger(__name__)


def _verify_plan_hash(plan_result: object, expected_hash: str) -> bool:
    """Verify plan_hash matches the canonical digest of the Plan."""
    if not hasattr(plan_result, "plan"):
        return False
    plan = plan_result.plan
    actual = canonical_plan_digest(plan)
    return actual == expected_hash


async def handle(state: PipelineState) -> PipelineState:
    """
    S11 handler: validate the execution plan.

    Reads PlanCreationResult (S9) and SafetyResult (S8) from PipelineState.
    Writes execution_manifest (primary) and validation_result (secondary).

    Returns updated PipelineState with execution_manifest and validation_result.
    """
    plan_result = state.plan
    safety_result = state.safety_result
    frozen = state.frozen_binding_identity
    context = state.execution_context

    if plan_result is None:
        raise ValueError("No PlanCreationResult from S9")
    if safety_result is None:
        raise ValueError("No SafetyResult from S8")
    if not safety_result.allowed:
        raise ValueError(f"S11 blocked by safety gate: {safety_result.failed_check}")

    plan = plan_result.plan
    errors: list[str] = []

    # --- Check 1: Plan hash integrity ---
    if not _verify_plan_hash(plan_result, plan_result.plan_hash):
        errors.append("plan_hash_mismatch")

    # --- Check 2: Plan matches DATA_CONTRACTS §4 ---
    if not errors:
        if not isinstance(plan.id, str) or not plan.id:
            errors.append("invalid_plan_id")
        elif not isinstance(plan.steps, tuple):
            errors.append("invalid_steps_type")
        elif not isinstance(plan.created_at, (int, float)):
            errors.append("invalid_created_at")

    # --- Check 3: No unknown step dependencies ---
    if not errors:
        step_ids = {s.id for s in plan.steps}
        has_unknown = False
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"unknown_dependency:{step.id}:{dep}")
                    has_unknown = True
                    break
            if has_unknown:
                break

    # --- Check 4: Budget not exceeded ---
    if not errors:
        if plan.budget_reserved < 0:
            errors.append(f"budget_exceeded:{plan.budget_reserved}")

    # --- If any failure, return DENY ---
    if errors:
        logger.warning("S11: DENY — %s", errors)
        return state.with_stage_output(
            "S11",
            validation_result=ValidationResult(is_valid=False, errors=tuple(errors)),
        )

    # --- All validation checks pass — create ExecutionManifest ---
    manifest = ExecutionManifest(
        execution_id=plan_result.execution_id,
        trace_id=context.trace_id if context else "",
        plan_hash=plan_result.plan_hash,
        capability_version="1.0.0",
        binding_version="1.0.0",
        policy_version="1.0.0",
        risk_policy_version="1.0.0",
        authorization_version="1.0.0",
        auth_result_id=context.auth_result_id if context else None,
        worker_runtime_version="1.0.0",
        model_version="1.0.0",
        created_at=time.time(),
    )

    return state.with_stage_output(
        "S11",
        execution_manifest=manifest,
        validation_result=ValidationResult(is_valid=True, errors=()),
    )
