"""S0 Entry: build the ExecutionContext, then the S0.1 activation check.

S0 is the only place trace_id and request_id are created. Identity comes from the
authenticated EntryRequest, never from the request body or an LLM.
"""
from __future__ import annotations

import uuid
from dataclasses import fields

from supragents.contracts.context import ExecutionContext
from supragents.contracts.entry import EntryRequest
from supragents.contracts.state import PipelineState
from supragents.contracts.vocabulary import StageStatus
from supragents.pipeline.deps import PipelineDeps
from supragents.ports.activation import ActivationState

STAGE = "S0"
_REQUIRED_IDENTITY = (
    "tenant_id", "workspace_id", "user_id", "membership_id",
    "connection_id", "conversation_id", "resource_scope",
)


async def run(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    entry = state.entry_request
    missing = [name for name in _REQUIRED_IDENTITY if not getattr(entry, name)]
    if missing:
        return state.halted(STAGE, StageStatus.DENY, f"identity_missing:{','.join(missing)}")
    state = state.with_output(STAGE, execution_context=_new_context(entry))
    return await _check_activation(state, deps)


def _new_context(entry: EntryRequest) -> ExecutionContext:
    identity = {f.name: getattr(entry, f.name) for f in fields(entry) if f.name != "text"}
    return ExecutionContext(trace_id=str(uuid.uuid4()), request_id=str(uuid.uuid4()), **identity)


async def _check_activation(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """S0.1: a paused or not-yet-active tenant or workspace runs no S1–S11 work."""
    context = state.execution_context
    try:
        activation = await deps.activation.read(context.tenant_id, context.workspace_id)
    except Exception:
        return state.halted(STAGE, StageStatus.DENY, "activation_state_unavailable")
    reason = _inactive_reason(activation)
    return state if reason is None else state.halted(STAGE, StageStatus.DENY, reason)


def _inactive_reason(activation: ActivationState) -> str | None:
    now = activation.database_now

    def after_now(moment: float | None) -> bool:
        return moment is not None and moment > now

    if after_now(activation.tenant_paused_until):
        return "tenant_paused"
    if after_now(activation.workspace_paused_until):
        return "workspace_paused"
    if after_now(activation.tenant_activation_at) or after_now(activation.workspace_activation_at):
        return "not_yet_active"
    return None
