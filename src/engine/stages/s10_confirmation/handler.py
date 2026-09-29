"""
S10 Confirmation — present D/IRREVERSIBLE (and other high-impact) plans for approval.

Source: DATA_CONTRACTS.md §13, PIPELINE_STAGES.md §12, RUNBOOK R-N/R-R/R-Z
Owner: S10 / Confirmation

S10 always writes exactly one output, ConfirmationOutcome(required, confirmation):
- requires_confirmation False -> required=False, confirmation=None, status NORMAL.
- requires_confirmation True  -> a pending Confirmation (plan_id, plan_hash from S9;
  user_id, conversation_id from ExecutionContext; expires in 300 s) is saved in the
  confirmation store together with tenant_id and execution_id, and the stage status is
  CLARIFY ("confirmation_required"): the run stops and waits for the user.

The confirmed re-entry calls resume_confirmation(): the store's conditional consume must
succeed before S11 runs. Expired -> DENY confirmation_expired; wrong user or hash ->
DENY confirmation_mismatch. Status lives only in the store.
"""
from __future__ import annotations

import dataclasses
import logging
import time
import uuid

from contracts.pipeline_state import PipelineState
from contracts.execution_manifest import Confirmation, ConfirmationOutcome
from contracts.stage_registry import StageStatus
from engine.stages.preconditions import deny_unless_safety_passed
from engine.stages.s10_confirmation.store import (
    ConfirmationStore, CONSUMED, EXPIRED, MISMATCH,
)

logger = logging.getLogger(__name__)

CONFIRMATION_TTL_SECONDS = 300.0
CONFIRMATION_REQUIRED = "confirmation_required"


def _operations(steps) -> tuple[dict, ...]:
    """What the user is shown. A multi-capability plan (R-AB) lists EVERY step with the exact
    parameters it will run with (R-AE): the values plan_hash covers."""
    if len(steps) == 1:
        s = steps[0]
        return ({"step_id": s.id, "kernel_op_id": s.kernel_op_id, "mutation": s.mutation},)
    return tuple(
        {"step_id": s.id, "kernel_op_id": s.kernel_op_id, "mutation": s.mutation,
         "params": dict(s.params)}
        for s in steps
    )


async def handle(state: PipelineState, store: ConfirmationStore | None) -> PipelineState:
    """S10 handler. Returns the state with `confirmation` written and a status."""
    refused = deny_unless_safety_passed(state)
    if refused is not None:
        return refused
    if state.plan is None or state.task_profile is None:
        return state.with_status(StageStatus.DENY, "missing_plan")

    if not state.task_profile.requires_confirmation:
        return state.with_stage_output("S10", ConfirmationOutcome(required=False, confirmation=None))

    if store is None:
        return state.with_status(StageStatus.DENY, "confirmation_store_unavailable")

    ctx = state.execution_context
    plan_result = state.plan
    confirmation = Confirmation(
        confirmation_id=str(uuid.uuid4()),
        user_id=ctx.user_id,
        conversation_id=ctx.conversation_id or "",
        plan_id=plan_result.plan.id,
        plan_hash=plan_result.plan_hash,
        operations=_operations(plan_result.plan.steps),
        expires_at=time.time() + CONFIRMATION_TTL_SECONDS,
    )
    try:
        await store.save(confirmation, ctx.tenant_id, plan_result.execution_id)
    except Exception:
        logger.exception("S10: confirmation store save failed")
        return state.with_status(StageStatus.DENY, "confirmation_store_unavailable")

    logger.info("S10: confirmation required, plan_hash=%s", plan_result.plan_hash[:16])
    state = state.with_stage_output("S10", ConfirmationOutcome(required=True, confirmation=confirmation))
    return state.with_status(StageStatus.CLARIFY, CONFIRMATION_REQUIRED)


async def resume_confirmation(state: PipelineState, store: ConfirmationStore, *,
                              user_id: str, now: float | None = None) -> PipelineState:
    """Confirmed re-entry: consume the pending confirmation, then allow S11 to run.

    `user_id` is the AUTHENTICATED replier, never the user stored in the suspended state:
    only the user the confirmation was issued to can consume it.

    The only permitted rewrite of the S10 output: the same confirmation, now carrying
    consumed_at. On any refusal the state keeps the pending confirmation.
    """
    outcome = state.confirmation
    if outcome is None or not outcome.required or outcome.confirmation is None:
        return state.with_status(StageStatus.DENY, "confirmation_mismatch")
    conf = outcome.confirmation
    when = time.time() if now is None else now
    result = await store.consume(
        conf.confirmation_id,
        tenant_id=state.execution_context.tenant_id,
        user_id=user_id,
        plan_hash=state.plan.plan_hash,
        now=now,
    )
    if result == CONSUMED:
        consumed = dataclasses.replace(conf, consumed_at=when)
        state = dataclasses.replace(state, confirmation=ConfirmationOutcome(True, consumed))
        return state.with_status(StageStatus.NORMAL)
    reason = EXPIRED if result == EXPIRED else MISMATCH
    return state.with_status(StageStatus.DENY, reason)
