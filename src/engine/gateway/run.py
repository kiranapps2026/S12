"""Run a received event through the ONE pipeline (EVENT_DRIVEN mode) and record how it ended."""
from __future__ import annotations

import logging

from contracts.errors import DependencyUnavailable
from contracts.stage_registry import StageStatus
from engine.gateway.webhook import EventGateway, Received, event_message
from engine.stages.s0_entry.handler import EntryRequest

logger = logging.getLogger(__name__)


def entry_for(received: Received) -> EntryRequest:
    """The S0 entry request for an event: identity from authentication, event id as task id, the
    gateway's correlation id as the conversation id (never anything from the payload)."""
    principal, envelope = received.principal, received.envelope
    return EntryRequest(
        raw_payload={"message": event_message(received)},
        entry_channel="event",
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        membership_id=principal.membership_id,
        conversation_id=envelope.correlation_id,
        connection_id=principal.connection_id,
        resource_scope=principal.resource_scope,
        idempotency_key=envelope.event_id,
        event_id=envelope.event_id,
    )


async def run_received_event(pipeline, gateway: EventGateway, received: Received):
    """Run S0-S11 for `received` and mark the event `processed` or `failed`."""
    envelope = received.envelope
    try:
        result = await pipeline.run(entry_for(received))
    except Exception:
        await _finish(gateway, envelope, "failed")
        raise
    await _finish(gateway, envelope, "failed" if result.status is StageStatus.ERROR else "processed")
    return result


async def _finish(gateway: EventGateway, envelope, status_: str) -> None:
    try:
        await gateway.finish(envelope.tenant_id, envelope.event_id, status_)
    except DependencyUnavailable:
        logger.warning("could not record processing status of event %s", envelope.event_id)
