"""
S8 Safety Enforcement — enforce safety policy, set kill switch if needed.

Source: FINAL_ARCHITECTURE.md §11, §17
Owner: S8 / Safety Enforcement
"""

from __future__ import annotations

import logging

from contracts.pipeline_state import PipelineState
from contracts.safety import SafetyResult, TaskProfile
from contracts.stage_registry import StageOutcome

logger = logging.getLogger(__name__)


class SafetyEnforcementError(Exception):
    """Safety policy enforcement failed."""
    pass


async def handle(state: PipelineState) -> PipelineState:
    """
    S8 handler: enforce safety policy on the current task.

    Reads task_profile (S6) and path_decision (S7) from PipelineState.
    Enforces risk thresholds and sets kill switch if needed.
    Returns updated PipelineState with safety_result set.
    """
    task_profile = state.task_profile
    path_decision = state.path_decision

    if task_profile is None:
        raise SafetyEnforcementError("No TaskProfile from S6")
    if path_decision is None:
        raise SafetyEnforcementError("No PathDecision from S7")

    # Enforce safety policy
    kill_switch_active = False
    check_results: dict[str, bool] = {}

    if task_profile.effective_risk >= 0.9:
        kill_switch_active = True
        check_results["risk_threshold"] = False
    else:
        check_results["risk_threshold"] = True

    check_results["requires_confirmation"] = task_profile.requires_confirmation
    check_results["is_idempotent"] = task_profile.mutation_type in ("READ", "IDEMPOTENT_WRITE")

    is_safe = not kill_switch_active
    if not is_safe:
        logger.warning("S8: kill switch activated for task %s", task_profile.execution_id)

    # Build SafetyResult — this is the S8-authoritative safety assessment
    safety_result = SafetyResult(
        is_safe=is_safe,
        mutation_classification=task_profile.mutation_type,
        is_idempotent=task_profile.mutation_type in ("READ", "IDEMPOTENT_WRITE"),
        is_irreversible=task_profile.mutation_type == "IRREVERSIBLE",
        requires_confirmation=task_profile.requires_confirmation,
        kill_switch_active=kill_switch_active,
        check_results=check_results,
        reasons=[],
    )

    logger.info(
        "S8 enforced safety: safe=%s, kill_switch=%s",
        is_safe, kill_switch_active,
    )

    return state.with_stage_output("S8", safety_result)
