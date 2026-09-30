"""Event gateway: authenticate -> validate -> store -> envelope, for every event source.

Sources (EVENT_GATEWAY_AND_ROUTER §4):
  webhook   signed HTTP POST from a provider (ghl, stripe, custom); HMAC signing secret
  mcp       signed HTTP POST from an internal MCP server; the same signing-secret mechanism
  api       an authenticated API client (Bearer API key) posting an event
  schedule  the internal scheduler firing a stored schedule at a planned time

Rules common to all sources:
- Identity (tenant, workspace, user) comes ONLY from authentication: the endpoint's credential, the API
  key, or the schedule's stored identity. Nothing in the payload can name or change it (I-022).
- An event type must be REGISTERED for the tenant and the payload must satisfy its schema, otherwise the
  event is refused before anything is stored (fail closed).
- Fail closed and no oracle: an unknown endpoint and a wrong signature are the same answer.
- Deduplication is the unique (tenant, idempotency key) insert (EVENT_GATEWAY §3.1).
- The gateway never runs business logic and never calls a model; it hands back the envelope and the
  principal, and the caller runs the ONE pipeline.
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

from contracts.errors import DependencyUnavailable
from contracts.event_envelope import EventEnvelope
from contracts.event_schema import EventSchemaStore
from contracts.principal import Principal
from contracts.schedule import Schedule
from contracts.webhook_credentials import EventLog, WebhookCredentialStore
from engine.gateway import schema as schema_check
from engine.gateway import signature

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 65536
_WEBHOOK_SOURCES = frozenset({"ghl", "stripe", "custom"})
_EVENT_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
_TYPE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
MCP_TOOL_CALL = "mcp.tool_call"
MAX_KEY_LENGTH = 256


class WebhookRejected(Exception):
    """The event is refused. `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


EventRejected = WebhookRejected


@dataclass(frozen=True)
class Received:
    envelope: EventEnvelope
    principal: Principal
    payload: dict
    duplicate: bool


class EventGateway:
    def __init__(self, credentials: WebhookCredentialStore | None, log: EventLog,
                 schemas: EventSchemaStore | None, clock=time.time) -> None:
        self._credentials = credentials      # None: signed sources answer 503 (no key-encryption key)
        self._log = log
        self._schemas = schemas
        self._clock = clock

    async def finish(self, tenant_id: str, event_id: str, status: str) -> None:
        await self._log.finish(tenant_id, event_id, status)

    # ---- signed sources: webhook and mcp ---------------------------------------------------------

    async def receive(self, source_system: str, endpoint_id: str, raw_body: bytes,
                      signature_header: str | None) -> Received:
        """A provider webhook (ghl, stripe, custom)."""
        if source_system not in _WEBHOOK_SOURCES:
            raise WebhookRejected(401, "unauthenticated")
        principal, timestamp = await self._authenticate(source_system, endpoint_id, raw_body, signature_header)
        payload = _parse(raw_body)
        event_type = payload.get("type")
        if not isinstance(event_type, str) or not _TYPE.match(event_type):
            raise WebhookRejected(400, "invalid_event_type")
        checksum = hashlib.sha256(raw_body).hexdigest()
        # §3.1: the sender's own event id, else the hash of the body (identical bodies are one event)
        discriminator = _client_id(payload.get("id")) or f"sha256:{checksum}"
        return await self._accept(principal=principal, source="webhook", source_system=source_system,
                                  event_type=event_type, payload=payload, raw_body=raw_body,
                                  key=f"webhook:{source_system}:{discriminator}",
                                  occurred=datetime.fromtimestamp(timestamp, timezone.utc),
                                  auth_method="hmac_sha256", auth_principal=principal.connection_id)

    async def receive_mcp(self, endpoint_id: str, raw_body: bytes, signature_header: str | None) -> Received:
        """A tool call reported by an internal MCP server: `{"tool_name": ..., "arguments": {...}, "id": optional}`."""
        principal, timestamp = await self._authenticate("mcp", endpoint_id, raw_body, signature_header)
        body = _parse(raw_body)
        tool = body.get("tool_name")
        arguments = body.get("arguments", {})
        if not isinstance(tool, str) or not _TYPE.match(tool) or not isinstance(arguments, dict):
            raise WebhookRejected(400, "invalid_tool_call")
        payload = {"tool_name": tool, "arguments": arguments}
        # A signed request that repeats within the replay window must not run twice: without a client
        # key the discriminator is the signed timestamp plus the body hash (a deviation from the spec's
        # "each request is new", chosen because a captured signed request is an attack).
        discriminator = _client_id(body.get("id")) or \
            f"sha256:{hashlib.sha256(f'{timestamp}.'.encode() + raw_body).hexdigest()}"
        return await self._accept(principal=principal, source="mcp", source_system="mcp",
                                  event_type=MCP_TOOL_CALL, payload=payload, raw_body=raw_body,
                                  key=f"mcp:mcp:{discriminator}",
                                  occurred=datetime.fromtimestamp(timestamp, timezone.utc),
                                  auth_method="hmac_sha256", auth_principal=principal.connection_id)

    async def _authenticate(self, source_system: str, endpoint_id: str, raw_body: bytes,
                            signature_header: str | None) -> tuple[Principal, int]:
        if self._credentials is None:
            raise WebhookRejected(503, "webhooks_unavailable")
        if len(raw_body) > MAX_BODY_BYTES:
            raise WebhookRejected(413, "payload_too_large")
        endpoint = await self._credentials.endpoint(endpoint_id, source_system)
        verified = None
        try:
            try:
                timestamp, provided = signature.parse_header(signature_header)
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
            logger.warning("signed event rejected: bad signature or unknown endpoint (%s)", source_system)
            raise WebhookRejected(401, "unauthenticated")
        try:
            signature.check_timestamp(timestamp, self._clock())
        except signature.SignatureProblem:
            raise WebhookRejected(400, "stale_timestamp") from None
        if verified.status == "retiring":
            logger.warning("signed event verified with a RETIRING secret (source=%s)", source_system)
        await self._credentials.mark_verified(verified.credential_id)
        return endpoint.principal, timestamp

    # ---- api source ------------------------------------------------------------------------------

    async def receive_api(self, principal: Principal, body: dict, request_id: str | None = None) -> Received:
        """An event posted by an authenticated API client: `{"type": ..., "payload": {...}, "idempotency_key": optional}`.
        The identity is the caller's API key, never the body."""
        event_type, payload = body.get("type"), body.get("payload", {})
        if not isinstance(event_type, str) or not _TYPE.match(event_type):
            raise WebhookRejected(400, "invalid_event_type")
        if not isinstance(payload, dict):
            raise WebhookRejected(400, "invalid_json")
        raw_body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if len(raw_body) > MAX_BODY_BYTES:
            raise WebhookRejected(413, "payload_too_large")
        # §3.1: the client's idempotency key when supplied; otherwise each request is a new event
        discriminator = _client_id(body.get("idempotency_key")) or request_id or str(uuid.uuid4())
        return await self._accept(principal=principal, source="api", source_system="api",
                                  event_type=event_type, payload=payload, raw_body=raw_body,
                                  key=f"api:api:{discriminator}",
                                  occurred=datetime.fromtimestamp(self._clock(), timezone.utc),
                                  auth_method="api_key", auth_principal=principal.connection_id)

    # ---- schedule source -------------------------------------------------------------------------

    async def receive_schedule(self, schedule: Schedule, planned: datetime) -> Received:
        """A stored schedule reaching a planned fire time. The key uses the PLANNED time, so two
        schedulers (or a retry) firing the same planned time create one event (§3.1)."""
        raw_body = json.dumps(schedule.payload, sort_keys=True, separators=(",", ":")).encode()
        planned_utc = planned.astimezone(timezone.utc)
        return await self._accept(principal=schedule.principal, source="schedule", source_system="cron",
                                  event_type=schedule.event_type, payload=schedule.payload, raw_body=raw_body,
                                  key=f"schedule:cron:{schedule.schedule_id}:{planned_utc.isoformat()}",
                                  occurred=planned_utc, auth_method="schedule_internal",
                                  auth_principal=schedule.schedule_id)

    # ---- common ----------------------------------------------------------------------------------

    async def _accept(self, *, principal: Principal, source: str, source_system: str, event_type: str,
                      payload: dict, raw_body: bytes, key: str, occurred: datetime, auth_method: str,
                      auth_principal: str) -> Received:
        schema_version = await self._validated(principal.tenant_id, source_system, event_type, payload)
        if len(key) > MAX_KEY_LENGTH:
            key = "sha256:" + hashlib.sha256(key.encode()).hexdigest()
        event_id = str(uuid.uuid4())
        envelope = EventEnvelope(
            event_id=event_id,
            correlation_id=str(uuid.uuid4()),
            source=source,
            source_system=source_system,
            type=event_type,
            payload_ref=f"pg:event_log.{event_id}",
            payload_checksum=hashlib.sha256(raw_body).hexdigest(),
            tenant_id=principal.tenant_id,          # from authentication, never the payload
            workspace_id=principal.workspace_id,
            timestamp=occurred.isoformat(),
            schema_version=schema_version,
        )
        stored = await self._log.record(envelope=envelope, principal=principal, idempotency_key=key,
                                        raw_body=raw_body, auth_method=auth_method, auth_principal=auth_principal)
        return Received(envelope, principal, payload, stored.duplicate)

    async def _validated(self, tenant_id: str, source_system: str, event_type: str, payload: dict) -> str:
        """The version of the registered schema the payload satisfies (C2). An unregistered event type,
        an unusable schema and a payload that does not fit are all refused; a registry that cannot be
        read is 503. Nothing is stored for a refused event."""
        if self._schemas is None:
            raise WebhookRejected(503, "event_schemas_unavailable")
        try:
            registered = await self._schemas.latest(tenant_id, source_system, event_type)
        except DependencyUnavailable:
            raise WebhookRejected(503, "event_schemas_unavailable") from None
        if registered is None:
            raise WebhookRejected(422, "event_type_not_registered")
        try:
            schema_check.check_schema(registered.schema)
        except schema_check.SchemaError:
            logger.error("registered schema for %s/%s is unusable", source_system, event_type)
            raise WebhookRejected(422, "event_schema_invalid") from None
        problem = schema_check.validate(registered.schema, payload)
        if problem is not None:
            logger.info("event payload rejected (%s): %s", event_type, problem)
            raise WebhookRejected(422, "payload_invalid")
        return registered.version


WebhookGateway = EventGateway


def event_message(received: Received) -> str:
    """The text S1/S2 see for an event: type, source and the payload as compact JSON. It is
    untrusted data like any user text and goes through S1 sanitisation and the S1 size limits."""
    body = json.dumps(received.payload, separators=(",", ":"), ensure_ascii=False)
    return f"Event {received.envelope.type} from {received.envelope.source_system}: {body}"


def _client_id(value) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool) and _EVENT_ID.match(str(value)):
        return str(value)
    return None


def _parse(raw_body: bytes) -> dict:
    try:
        payload = json.loads(raw_body)
    except (ValueError, RecursionError):
        raise WebhookRejected(400, "invalid_json") from None
    if not isinstance(payload, dict):
        raise WebhookRejected(400, "invalid_json")
    return payload
