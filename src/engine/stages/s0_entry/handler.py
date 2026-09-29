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
from contracts.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class EntryRequest:
    """Incoming request at the entry point."""
    def __init__(
        self,
        raw_payload: dict,
        entry_channel: str,
        tenant_id: str,
        conversation_id: str | None = None,
        connection_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ):
        self.raw_payload = raw_payload
        self.entry_channel = entry_channel
        self.tenant_id = tenant_id
        self.conversation_id = conversation_id
        self.connection_id = connection_id
        self.user_id = user_id
        self.request_id = request_id


async def handle(entry: EntryRequest) -> ExecutionContext:
    """
    S0 handler: parse entry request, create ExecutionContext.

    This is the ONLY place ExecutionContext is created.
    After this, ExecutionContext is frozen — never mutated again.

    Returns a NEW ExecutionContext instance.
    """
    request_id = entry.request_id or str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    context = ExecutionContext(
        trace_id=trace_id,
        request_id=request_id,
        tenant_id=entry.tenant_id,
        workspace_id=entry.tenant_id,
        user_id=entry.user_id or "system",
        conversation_id=entry.conversation_id,
        connection_id=entry.connection_id,
    )

    logger.info(
        "S0 parsed request: trace=%s, request=%s, channel=%s",
        trace_id, request_id, entry.entry_channel,
    )

    state = PipelineState(
        execution_context=context,
        entry_request=entry,
    )

    return state
