"""
S0.1 — activation check: a paused or not-yet-active tenant or workspace runs no S1–S11 work.

Ruling: R-AA (proposed id, owner ratifies; text in docs/proposals/S0_1_PAUSE_CHECK.md).
R-P is the vocabulary ruling; R-A..R-Z are all taken, so the next free id is R-AA.

Decided by the database clock, never the caller's. Fail closed: if the state cannot be read
the request is denied. Reasons (exact): tenant_paused, workspace_paused, not_yet_active,
activation_state_unavailable. Applies to a new run and to a reply to a waiting confirmation.
"""
from __future__ import annotations

import logging

from contracts.activation import ActivationState, ActivationStateReader
from contracts.pipeline_state import PipelineState

logger = logging.getLogger(__name__)

TENANT_PAUSED = "tenant_paused"
WORKSPACE_PAUSED = "workspace_paused"
NOT_YET_ACTIVE = "not_yet_active"
UNAVAILABLE = "activation_state_unavailable"


def inactive_reason(activation: ActivationState) -> str | None:
    """The reason the tenant/workspace may not run now, or None if it may."""
    now = activation.database_now

    def after_now(moment: float | None) -> bool:
        return moment is not None and moment > now

    if after_now(activation.tenant_paused_until):
        return TENANT_PAUSED
    if after_now(activation.workspace_paused_until):
        return WORKSPACE_PAUSED
    if after_now(activation.tenant_activation_at) or after_now(activation.workspace_activation_at):
        return NOT_YET_ACTIVE
    return None


async def activation_denial(state: PipelineState, reader: ActivationStateReader | None) -> str | None:
    """The DENY reason if this request may not run now, or None if it may."""
    ctx = state.execution_context
    if ctx is None or reader is None:
        return UNAVAILABLE
    try:
        activation = await reader.read(ctx.tenant_id, ctx.workspace_id)
    except Exception:  # noqa: BLE001 — fail closed
        logger.exception("S0.1: activation state unavailable")
        return UNAVAILABLE
    return inactive_reason(activation)
