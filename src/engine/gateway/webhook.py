"""Webhook ingress: authenticate -> validate -> store -> envelope.

- Identity comes ONLY from the endpoint's credential (signing-secret lookup). Nothing in the
  body can name or change the tenant, workspace or user.
- Fail closed. An unknown endpoint and a wrong signature are the same answer (no oracle).
- The gateway never runs business logic and never calls a model; it hands back the envelope
  and the principal, and the caller runs the ONE pipeline.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from contracts.event_envelope import EventEnvelope
from contracts.principal import Principal
from contracts.webhook_credentials import EventLog, WebhookCredentialStore
from engine.gateway import signature

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 65536
_SOURCES = frozenset({"ghl", "stripe", "custom", "mcp"})
_EVENT_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
_TYPE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")


class WebhookRejected(Exception):
    """The event is refused. `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class Received:
    envelope: EventEnvelope
    principal: Principal
    payload: dict
    duplicate: bool


class WebhookGateway:
    def __init__(self, credentials: WebhookCredentialStore, log: EventLog, clock=time.time) -> None:
        self._credentials = credentials
        self._log = log
        self._clock = clock

    async def finish(self, tenant_id: str, event_id: str, status: str) -> None:
        await self._log.finish(tenant_id, event_id, status)

    async def receive(self, source_system: str, endpoint_id: str, raw_body: bytes,
                      signature_header: str | None) -> Received:
        if source_system not in _SOURCES:
            raise WebhookRejected(401, "unauthenticated")
        if len(raw_body) > MAX_BODY_BYTES:
            raise WebhookRejected(413, "payload_too_large")

        endpoint = await self._credentials.endpoint(endpoint_id, source_system)
        try:
            try:
                timestamp, provided = signature.parse_header(signature_header)
                verified = None
                if endpoint is not None:
                    for secret in endpoint.secrets:
                        if signature.matches(secret.value, timestamp, raw_body, provided):
                            verified = secret
                            break
            finally:
                if endpoint is not None:
                    for secret in endpoint.secrets:
                        secret.value[:] = bytes(len(secret.value))   # best-effort wipe
        except signature.SignatureProblem:
            raise WebhookRejected(401, "unauthenticated") from None
        if endpoint is None or verified is None:
            logger.warning("webhook rejected: bad signature or unknown endpoint (%s)", source_system)
            raise WebhookRejected(401, "unauthenticated")
        try:
            signature.check_timestamp(timestamp, self._clock())
        except signature.SignatureProblem:
            raise WebhookRejected(400, "stale_timestamp") from None
        if verified.status == "retiring":
            logger.warning("webhook verified with a RETIRING secret (source=%s)", source_system)
        await self._credentials.mark_verified(verified.credential_id)

        payload = _parse(raw_body)
        event_type = payload.get("type")
        if not isinstance(event_type, str) or not _TYPE.match(event_type):
            raise WebhookRejected(400, "invalid_event_type")

        principal = endpoint.principal
        event_id = str(uuid.uuid4())
        checksum = hashlib.sha256(raw_body).hexdigest()
        envelope = EventEnvelope(
            event_id=event_id,
            correlation_id=str(uuid.uuid4()),
            source="webhook",
            source_system=source_system,
            type=event_type,
            payload_ref=f"pg:event_log.{event_id}",
            payload_checksum=checksum,
            tenant_id=principal.tenant_id,          # from the credential, never the payload
            workspace_id=principal.workspace_id,
            timestamp=datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        )
        stored = await self._log.record(
            envelope=envelope, principal=principal,
            idempotency_key=_idempotency_key(source_system, payload, timestamp, checksum),
            raw_body=raw_body)
        return Received(envelope, principal, payload, stored.duplicate)


def event_message(received: Received) -> str:
    """The text S1/S2 see for an event: type, source and the payload as compact JSON. It is
    untrusted data like any user text and goes through S1 sanitisation and the S1 size limits."""
    body = json.dumps(received.payload, separators=(",", ":"), ensure_ascii=False)
    return f"Event {received.envelope.type} from {received.envelope.source_system}: {body}"


def _idempotency_key(source_system: str, payload: dict, timestamp: int, checksum: str) -> str:
    """`{source}:{source_system}:{discriminator}` (EVENT_GATEWAY §3.1). The sender's own event id
    when it gives one (so provider retries deduplicate); otherwise the signed timestamp plus the
    body hash (so an exact replay deduplicates)."""
    source_id = payload.get("id")
    if isinstance(source_id, (str, int)) and _EVENT_ID.match(str(source_id)):
        return f"webhook:{source_system}:{source_id}"
    return f"webhook:{source_system}:{timestamp}.{checksum}"


def _parse(raw_body: bytes) -> dict:
    try:
        payload = json.loads(raw_body)
    except (ValueError, RecursionError):
        raise WebhookRejected(400, "invalid_json") from None
    if not isinstance(payload, dict):
        raise WebhookRejected(400, "invalid_json")
    return payload
