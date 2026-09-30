"""
S0 Entry/Parse — parse incoming request, create ExecutionContext.

THIS IS THE ONLY PLACE ExecutionContext IS CREATED.

Source: FINAL_ARCHITECTURE.md §11, DATA_CONTRACTS.md §2
Owner: S0 / Entry/Parse

After S0, ExecutionContext is frozen. No in-place mutation allowed.
Only whitelisted fields may be added after S0:
    tenant_policy_version_id, workspace_policy_version_id, policy_version_id
No binding, capability, or provider fields are on ExecutionContext —
those live on FrozenBindingIdentity.
"""

from __future__ import annotations

import logging
import uuid

from contracts.pipeline_state import PipelineState
from contracts.entry import EntryRequest
from contracts.execution_context import ExecutionContext
from contracts.stage_registry import StageStatus

logger = logging.getLogger(__name__)


#: Identity values S0 must find on the entry request; absent -> DENY missing_<field>.
_REQUIRED_IDENTITY = ("tenant_id", "workspace_id", "user_id")


async def handle(entry: EntryRequest) -> PipelineState:
    """
    S0 handler: parse entry request, create ExecutionContext.

    This is the ONLY place ExecutionContext is created. Nothing is defaulted: a missing
    tenant, workspace or user is a DENY (`missing_<field>`) and no context is created.
    """
    for name in _REQUIRED_IDENTITY:
        if not getattr(entry, name, None):
            logger.warning("S0: DENY missing_%s", name)
            return PipelineState(entry_request=entry).with_status(
                StageStatus.DENY, f"missing_{name}")

    request_id = entry.request_id or str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    context = ExecutionContext(
        trace_id=trace_id,
        request_id=request_id,
        tenant_id=entry.tenant_id,
        workspace_id=entry.workspace_id,
        user_id=entry.user_id,
        membership_id=entry.membership_id,
        conversation_id=entry.conversation_id or str(uuid.uuid4()),   # R-BA: never empty (S12 entry needs one)
        connection_id=entry.connection_id,
        idempotency_key=entry.idempotency_key,
        task_id=entry.event_id,          # EVENT_DRIVEN: the gateway's event id; else assigned at S2
        resource_scope=entry.resource_scope,
        tags=frozenset(entry.tags),
    )

    logger.info(
        "S0 parsed request: trace=%s, request=%s, channel=%s",
        trace_id, request_id, entry.entry_channel,
    )

    return PipelineState(
        execution_context=context,
        entry_request=entry,
        stage_status=StageStatus.NORMAL,
    )
