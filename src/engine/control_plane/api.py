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

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from contracts.errors import DependencyUnavailable, UnknownConfirmation
from contracts.principal import Principal
from contracts.stage_registry import PIPELINE_SEQUENCE, StageStatus
from engine.control_plane.pipeline_state_runner import PipelineRunner
from engine.stages.s0_entry.handler import EntryRequest

logger = logging.getLogger(__name__)

router = APIRouter()


class ExecuteRequest(BaseModel):
    """Request to run the pipeline. Deliberately has no identity fields."""
    model_config = {"extra": "forbid"}

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
    return principal


def get_pipeline(request: Request) -> PipelineRunner:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "pipeline_unavailable")
    return pipeline


@router.post("/execute", response_model=ExecuteResponse)
async def execute_pipeline(
    body: ExecuteRequest,
    principal: Principal = Depends(get_principal),
    pipeline: PipelineRunner = Depends(get_pipeline),
) -> ExecuteResponse:
    """Run S0–S11 for the authenticated principal."""
    entry = EntryRequest(
        raw_payload=body.input_data,
        entry_channel="api",
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        membership_id=principal.membership_id,
        conversation_id=body.conversation_id,
        connection_id=principal.connection_id,
        resource_scope=principal.resource_scope,
        idempotency_key=body.idempotency_key,
    )
    return _response(await pipeline.run(entry))


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
