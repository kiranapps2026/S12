"""S10 Confirmation: D/IRREVERSIBLE or costly plans wait for the user's explicit approval.

First pass: store a pending confirmation (tenant and execution id, ruling R-Z) and
suspend the run. Resumed pass (with the user's reply): consume it atomically in the
store, or stop. S10 never trusts in-memory state: it re-reads the store.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from types import MappingProxyType

from supragents.contracts.outputs import Confirmation, ConfirmationCheck, PlanCreationResult
from supragents.contracts.reply import ConfirmationReply
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import ConfirmationStatus, StageStatus
from supragents.pipeline.deps import PipelineDeps
from supragents.stages.guards import deny_unless_safety_passed

STAGE = "S10"
CONFIRMATION_TTL_SECONDS = 300.0


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    denied = deny_unless_safety_passed(state, STAGE)
    if denied is not None:
        return denied
    if not state.task_profile.requires_confirmation:
        return _checked(state, ConfirmationStatus.NOT_REQUIRED, None)
    if state.confirmation_reply is None:
        return await _request(state, deps)
    return await _apply_reply(state, deps, state.confirmation_reply)


async def _request(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    context = state.execution_context
    plan_result = state.plan_result
    confirmation = Confirmation(
        confirmation_id=str(uuid.uuid4()),
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        plan_id=plan_result.plan.id,
        plan_hash=plan_result.plan_hash,
        operations=_operations(plan_result),
        expires_at=await deps.clock.now() + CONFIRMATION_TTL_SECONDS,
    )
    await deps.confirmations.save(
        confirmation, tenant_id=context.tenant_id, execution_id=plan_result.plan.execution_id
    )
    return _checked(state, ConfirmationStatus.PENDING, confirmation)


async def _apply_reply(state: PipelineState, deps: PipelineDeps, reply: ConfirmationReply) -> PipelineState:
    context = state.execution_context
    stored = await deps.confirmations.find(
        tenant_id=context.tenant_id, execution_id=state.plan_result.plan.execution_id
    )
    if stored is None or stored.confirmation.confirmation_id != reply.confirmation_id:
        return state.halted(STAGE, StageStatus.ERROR, "confirmation_not_found")
    if reply.user_id != context.user_id:
        return state.halted(STAGE, StageStatus.ERROR, "confirmation_wrong_user")
    ids = {"tenant_id": context.tenant_id, "user_id": context.user_id}
    if not reply.approved:
        await deps.confirmations.reject(reply.confirmation_id, **ids)
        return _stopped(state, ConfirmationStatus.REJECTED, stored.confirmation, "confirmation_rejected")
    if stored.confirmation.expires_at <= await deps.clock.now():
        return _stopped(state, ConfirmationStatus.EXPIRED, stored.confirmation, "confirmation_expired")
    consumed = await deps.confirmations.consume(
        reply.confirmation_id, plan_hash=state.plan_result.plan_hash, **ids
    )
    if not consumed:
        return _stopped(state, stored.status, stored.confirmation, "confirmation_not_consumable")
    confirmation = replace(stored.confirmation, consumed_at=await deps.clock.now())
    return _checked(state, ConfirmationStatus.CONSUMED, confirmation)


def _operations(plan_result: PlanCreationResult) -> tuple[MappingProxyType, ...]:
    """The exact operations shown to the user (PIPELINE_STAGES §12 "Specific")."""
    return tuple(
        MappingProxyType({"step_id": step.id, "kernel_op_id": step.kernel_op_id,
                          "mutation": step.mutation.value, "cost": step.cost})
        for step in plan_result.plan.steps
    )


def _checked(state: PipelineState, status: ConfirmationStatus, confirmation: Confirmation | None) -> PipelineState:
    return state.with_output(STAGE, confirmation_check=ConfirmationCheck(status=status, confirmation=confirmation))


def _stopped(state: PipelineState, status: ConfirmationStatus, confirmation: Confirmation, reason: str) -> PipelineState:
    return _checked(state, status, confirmation).halted(STAGE, StageStatus.ERROR, reason)
