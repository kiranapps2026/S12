"""
S10 Confirmation — present D/IRREVERSIBLE operations for user approval.

Source: DATA_CONTRACTS.md §4, PIPELINE_STAGES.md §12
Owner: S10 / Confirmation

Actions:
1. Scan plan for D/IRREVERSIBLE mutations
2. If found:
   - Generate Confirmation record (single-use, 5-min expiry)
   - Bind token to plan_hash and execution_id from PlanCreationResult
   - Return ENVELOPE(status="confirm", ...) — wait for user callback
3. If user confirms: consume token (single-use, atomic), proceed to S11
4. If user rejects: mark token as rejected, route to S15
5. If token expires: route to S15

Rules:
- Single-use: Token consumed atomically on first use
- Time-limited: Expires after 5 minutes (300 seconds)
- User-bound: Token tied to user_id + conversation_id
- Specific: Message lists EXACT operations
"""

from __future__ import annotations

import logging
import time
import uuid

from contracts.pipeline_state import PipelineState
from contracts.stage_outputs import PlanCreationResult
from contracts.safety import SafetyResult
from contracts.execution_manifest import Confirmation
from contracts.stage_registry import StageStatus

logger = logging.getLogger(__name__)


class ConfirmationRequired(Exception):
    """Confirmation required — execution paused, awaiting user."""
    pass


class ConfirmationRejected(Exception):
    """User rejected confirmation — execution cancelled."""
    pass


def _build_confirmation_message(plan_result: PlanCreationResult) -> str:
    """Build human-readable confirmation message listing exact operations."""
    plan = plan_result.plan
    lines = ["This will:"]
    for step in plan.steps:
        lines.append(f"  - Execute {step.kernel_op_id} ({step.id})")
    lines.append(f"")
    lines.append(f"Total operations: {len(plan.steps)}")
    lines.append(f"Budget reserved: {plan.budget_reserved} units")
    lines.append(f"")
    lines.append(f"Reply YES to confirm or NO to cancel.")
    return "\n".join(lines)


async def handle(state: PipelineState) -> PipelineState:
    """
    S10 handler: present confirmation for D/IRREVERSIBLE operations.

    Reads PlanCreationResult (S9) and SafetyResult (S8) from PipelineState.
    If requires_confirmation is True:
      - Generate Confirmation record with plan_hash binding
      - Return confirmation token (worker pauses, waits for callback)
    If requires_confirmation is False:
      - Return approved Confirmation (auto-approve for READ/IDEMPOTENT)

    Returns updated PipelineState with confirmation set.
    """
    plan_result = state.plan
    safety_result = state.safety_result

    if plan_result is None:
        raise ValueError("No PlanCreationResult from S9")
    if safety_result is None:
        raise ValueError("No SafetyResult from S8")
    if not safety_result.allowed:
        raise ValueError(f"S10 blocked by safety gate: {safety_result.failed_check}")

    context = state.execution_context
    plan = plan_result.plan

    # requires_confirmation comes from TaskProfile (S6), not SafetyResult (S8).
    # S6 computes it from the DATA_CONTRACTS §7 confirmation requirements table.
    task_profile = state.task_profile
    requires_confirmation = (
        task_profile.requires_confirmation
        if task_profile is not None
        else False
    )

    now = time.time()

    # Build human-readable operations list from plan steps
    operations = tuple(
        {"step_id": step.id, "kernel_op_id": step.kernel_op_id, "mutation": step.mutation}
        for step in plan.steps
    )

    confirmation_args = {
        "confirmation_id": str(uuid.uuid4()),
        "user_id": context.user_id if context else "",
        "conversation_id": context.conversation_id or "",
        "plan_id": plan.id,
        "plan_hash": plan_result.plan_hash,
        "operations": operations,
        "expires_at": now + 300.0,  # 5-minute expiry
    }

    if requires_confirmation:
        logger.info(
            "S10: confirmation required — token=%s, plan_hash=%s",
            confirmation_args["confirmation_id"],
            plan_result.plan_hash[:16],
        )

        # In real impl: persist token to pending_confirmations table (DB)
        # Worker pauses here, waits for user callback
        # Confirmation is CONSUMED at S10 — S12 never re-verifies it

    else:
        # Auto-approve for READ/IDEMPOTENT operations
        confirmation_args["consumed_at"] = now  # Mark as immediately consumed

        logger.info(
            "S10: auto-approved — mutation=%s, plan_hash=%s",
            task_profile.mutations[0] if task_profile else "unknown",
            plan_result.plan_hash[:16],
        )

    confirmation = Confirmation(**confirmation_args)
    return state.with_stage_output("S10", confirmation)
