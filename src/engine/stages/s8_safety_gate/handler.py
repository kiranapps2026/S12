"""
S8 Safety Gate — enforce safety constraints, run 8 checks, kill switch as first check.

Source: FINAL_ARCHITECTURE.md §11, §17, PIPELINE_STAGES.md §10, RUNBOOK R-A/R-B/R-C/R-D/R-M
Owner: S8 / Safety Gate

Check functions live in checks.py (shared module). S8 imports and calls them.
Dependencies are injected explicitly via S8Dependencies from the composition root.
No module-level globals. No test fallbacks in production code.

R-M: On ALLOW, S8 replaces execution_context.auth_passed=True and
execution_context.auth_result_id via validate_replace, then writes safety_result.
"""

from __future__ import annotations

import logging
import dataclasses
import uuid

from contracts.pipeline_state import PipelineState
from contracts.safety import SafetyResult
from contracts.stage_registry import StageStatus
from engine.stages.s8_safety_gate.dependencies import S8Dependencies

from .checks import (
    CheckResult,
    SAFETY_CHECKS,
)

logger = logging.getLogger(__name__)


async def handle(state: PipelineState, deps: S8Dependencies | None = None) -> PipelineState:
    """
    S8 handler: enforce safety policy with 8 checks.

    Check order:
    1. Kill switch (from deps.policy.kill_switch_engaged — system/tenant config)
    2. Required upstream outputs (TaskProfile, FrozenBindingIdentity, identity)
    3. 8 deterministic checks (imported from checks.py)
    4. All pass → SafetyResult(allowed=True)

    FAIL-CLOSED: If any check can't make a decision, DENY.
    No exception escapes the stage — all failures return DENY.
    One write per call.

    Args:
        state: PipelineState with S0–S7 outputs.
        deps: S8Dependencies injected from composition root. None → DENY
              kill_switch_state_unavailable.

    Returns updated PipelineState with safety_result set.
    """
    def deny(reason: str, failed_check: str) -> PipelineState:
        logger.warning("S8: DENY %s (%s)", reason, failed_check)
        denied = state.with_stage_output(
            "S8", SafetyResult(allowed=False, reason=reason, failed_check=failed_check)
        )
        return denied.with_status(StageStatus.DENY, reason)

    # 1. Kill switch — always first. deps or policy missing -> DENY.
    try:
        engaged = deps.policy.kill_switch_engaged
    except Exception:
        return deny("kill_switch_state_unavailable", "kill_switch")
    if engaged is True:
        return deny("kill_switch", "kill_switch")
    if engaged is not False:
        return deny("kill_switch_state_unavailable", "kill_switch")

    # 2. Required upstream outputs.
    if state.task_profile is None:
        return deny("missing_task_profile", "missing_task_profile")
    if state.frozen_binding_identity is None:
        return deny("missing_frozen_binding", "missing_frozen_binding")
    if state.execution_context is None:
        return deny("missing_identity", "missing_identity")

    # 3. The 8 checks in R-B table order. First non-pass denies.
    for check_name, check_fn in SAFETY_CHECKS:
        try:
            r = check_fn(
                state.execution_context,
                state.task_profile,
                state.frozen_binding_identity,
                deps,
            )
        except Exception:
            return deny(f"{check_name}_unavailable", check_name)
        if not isinstance(r, CheckResult) or r.name != check_name:
            return deny(f"{check_name}_invalid", check_name)
        if r.passed is not True:
            return deny(r.reason or f"{check_name}_failed", check_name)

    # 4. All checks pass.
    # R-M: set auth_passed/auth_result_id via replace_context, then write safety_result.
    state = state.replace_context(
        "S8",
        auth_passed=True,
        auth_result_id=str(uuid.uuid4()),
    )
    return state.with_stage_output(
        "S8",
        SafetyResult(allowed=True, reason=None, failed_check=None),
    )
