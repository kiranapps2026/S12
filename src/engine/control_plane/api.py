"""
Control Plane API — the HTTP entry to the S0–S11 runner.

Source: COMPONENTS_BLUEPRINT.md, FINAL_ARCHITECTURE.md §36, RUNBOOK R-C

- One execution path: the PipelineRunner built by build_pipeline() and placed on
  app.state.pipeline by the composition root. The API never builds handlers itself.
- Identity (tenant, workspace, user, membership, connection, resource scope) comes ONLY
  from the API key resolved by app.state.authenticator. The body cannot carry or override it.
- Fail closed: no authenticator or no pipeline configured -> 503; failed authentication
  -> 401. There is no default principal.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from contracts.errors import DependencyUnavailable, UnknownConfirmation
from contracts.principal import Principal
from contracts.stage_registry import PIPELINE_SEQUENCE, StageStatus
from engine.control_plane.pipeline_state_runner import PipelineRunner
from engine.gateway.run import run_received_event
from engine.gateway.webhook import EventGateway, WebhookRejected, MAX_BODY_BYTES
from engine.stages.s0_entry.handler import EntryRequest

logger = logging.getLogger(__name__)

router = APIRouter()


MAX_INPUT_CHARS = 65536


class ExecuteRequest(BaseModel):
    """Request to run the pipeline. Deliberately has no identity fields."""
    model_config = {"extra": "forbid"}

    @field_validator("input_data")
    @classmethod
    def _bounded(cls, value: dict) -> dict:
        try:
            size = len(json.dumps(value))
        except (RecursionError, TypeError, ValueError):
            raise ValueError("input_data is not plain JSON of sane depth")
        if size > MAX_INPUT_CHARS:
            raise ValueError(f"input_data is larger than {MAX_INPUT_CHARS} characters")
        return value

    input_data: dict[str, Any] = Field(..., description="Input data for execution")
    conversation_id: str | None = None
    idempotency_key: str = ""


class ExecuteResponse(BaseModel):
    """Outcome of an S0–S11 run."""
    trace_id: str | None = None
    execution_id: str | None = None
    status: str                       # NORMAL | CLARIFY | DENY | ERROR
    final_stage: str
    reason: str | None = None
    confirmation_id: str | None = None   # set when S10 is waiting for the user


class ReplyRequest(BaseModel):
    """The user's answer to a pending confirmation."""
    model_config = {"extra": "forbid"}

    approved: bool


class HealthResponse(BaseModel):
    status: str
    stages_loaded: int
    contracts_valid: bool


@dataclass(frozen=True)
class RateLimits:
    user_per_minute: int
    tenant_per_minute: int
    invite_per_minute: int
    window_seconds: int = 60


async def enforce_rate_limit(request: Request, principal: Principal) -> None:
    """429 when the caller's user or tenant window is used up. No limiter configured (tests): unlimited.
    A limiter that cannot be read answers 503: no limiter, no request (fail closed)."""
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    limits: RateLimits = request.app.state.rate_limits
    try:
        for bucket, limit in ((f"u:{principal.tenant_id}:{principal.user_id}", limits.user_per_minute),
                              (f"t:{principal.tenant_id}", limits.tenant_per_minute)):
            decision = await limiter.hit(bucket, limit, limits.window_seconds)
            if not decision.allowed:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited",
                                    headers={"Retry-After": str(decision.retry_after)})
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")


def usage_scope(request: Request, tenant_id: str, user_id: str, request_id: str):
    """Attribute the language-model calls made inside the block to this tenant, user and request."""
    meter = getattr(request.app.state, "usage_meter", None)
    return nullcontext() if meter is None else meter.scope(tenant_id, user_id, request_id)


async def get_principal(request: Request) -> Principal:
    authenticator = getattr(request.app.state, "authenticator", None)
    if authenticator is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication_unavailable")
    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    if scheme != "Bearer" or not credential:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated")
    try:
        principal = await authenticator.authenticate(credential)
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication_unavailable")
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated")
    await enforce_rate_limit(request, principal)
    return principal


def get_pipeline(request: Request) -> PipelineRunner:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "pipeline_unavailable")
    return pipeline


@router.post("/execute", response_model=ExecuteResponse)
async def execute_pipeline(
    body: ExecuteRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    pipeline: PipelineRunner = Depends(get_pipeline),
) -> ExecuteResponse:
    """Run S0–S11 for the authenticated principal."""
    request_id = str(uuid.uuid4())
    entry = EntryRequest(
        raw_payload=body.input_data,
        entry_channel="api",
        request_id=request_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        membership_id=principal.membership_id,
        conversation_id=body.conversation_id,
        connection_id=principal.connection_id,
        resource_scope=principal.resource_scope,
        idempotency_key=body.idempotency_key,
    )
    with usage_scope(request, principal.tenant_id, principal.user_id, request_id):
        return _response(await pipeline.run(entry))


class EventRequest(BaseModel):
    """An event posted by an API client. Deliberately has no identity fields."""
    model_config = {"extra": "forbid"}

    type: str = Field(..., max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=128)


def _event_gateway(request: Request) -> EventGateway:
    gateway: EventGateway | None = getattr(request.app.state, "webhooks", None)
    if gateway is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhooks_unavailable")
    return gateway


async def _signed_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload_too_large")
    return await request.body()


async def _run_event(request: Request, gateway: EventGateway, pipeline: PipelineRunner, receive, *,
                     limited: bool = False) -> ExecuteResponse:
    """Receive an event (any source) and run it through the one pipeline. A repeat delivery is
    acknowledged without running again."""
    try:
        received = await receive()
    except WebhookRejected as rejected:
        raise HTTPException(rejected.status, rejected.reason)
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")
    if not limited:                       # API events were counted when their key was authenticated
        await enforce_rate_limit(request, received.principal)
    if received.duplicate:
        return ExecuteResponse(status="NORMAL", final_stage="S0", reason="duplicate_event")
    with usage_scope(request, received.principal.tenant_id, received.principal.user_id, received.envelope.event_id):
        return _response(await run_received_event(pipeline, gateway, received))


@router.post("/webhooks/{source_system}/{endpoint_id}", response_model=ExecuteResponse)
async def receive_webhook(
    source_system: str,
    endpoint_id: str,
    request: Request,
    pipeline: PipelineRunner = Depends(get_pipeline),
) -> ExecuteResponse:
    """A provider event, authenticated by its signing secret (header `X-Signature`).

    The tenant, workspace and user come from the endpoint's credential, never from the body. The
    event type must be registered and the payload must fit its schema. The run is the same S0-S11
    path as a user request (EVENT_DRIVEN mode)."""
    gateway = _event_gateway(request)
    body = await _signed_body(request)
    return await _run_event(request, gateway, pipeline, lambda: gateway.receive(
        source_system, endpoint_id, body, request.headers.get("x-signature")))


@router.post("/mcp/{endpoint_id}", response_model=ExecuteResponse)
async def receive_mcp_event(
    endpoint_id: str,
    request: Request,
    pipeline: PipelineRunner = Depends(get_pipeline),
) -> ExecuteResponse:
    """A tool call reported by an internal MCP server, signed like a webhook (header `X-Signature`)."""
    gateway = _event_gateway(request)
    body = await _signed_body(request)
    return await _run_event(request, gateway, pipeline, lambda: gateway.receive_mcp(
        endpoint_id, body, request.headers.get("x-signature")))


@router.post("/events", response_model=ExecuteResponse)
async def receive_api_event(
    body: EventRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    pipeline: PipelineRunner = Depends(get_pipeline),
) -> ExecuteResponse:
    """An event posted by an authenticated API client. The identity is the API key's, never the body's."""
    gateway = _event_gateway(request)
    return await _run_event(request, gateway, pipeline, lambda: gateway.receive_api(
        principal, body.model_dump(), request_id=request.headers.get("x-request-id")), limited=True)


@router.post("/confirmations/{confirmation_id}", response_model=ExecuteResponse)
async def reply_to_confirmation(
    confirmation_id: str,
    body: ReplyRequest,
    principal: Principal = Depends(get_principal),
    pipeline: PipelineRunner = Depends(get_pipeline),
) -> ExecuteResponse:
    """Answer a pending confirmation. Only the user it was issued to can approve or reject
    it, and only within their own tenant; the run then continues (approve) or ends (reject)."""
    try:
        result = await pipeline.reply(principal.tenant_id, confirmation_id, principal.user_id,
                                      body.approved)
    except UnknownConfirmation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "confirmation_not_found")
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")
    return _response(result)


def _response(result) -> ExecuteResponse:
    state = result.final_state
    if result.status is StageStatus.ERROR:
        logger.error("Pipeline ERROR at %s: %s", result.final_stage, result.reason)
    conf = state.confirmation.confirmation if state.confirmation else None
    return ExecuteResponse(
        trace_id=state.execution_context.trace_id if state.execution_context else None,
        execution_id=state.plan.execution_id if state.plan else None,
        status=result.status.value,
        final_stage=result.final_stage,
        reason=result.reason,
        confirmation_id=(conf.confirmation_id
                         if conf and conf.consumed_at is None and result.status is StageStatus.CLARIFY
                         else None),
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    from contracts.stage_registry import validate_stage_order

    try:
        validate_stage_order()
        contracts_valid = True
    except AssertionError:
        contracts_valid = False
    return HealthResponse(status="healthy", stages_loaded=len(PIPELINE_SEQUENCE),
                          contracts_valid=contracts_valid)
