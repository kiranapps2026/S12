"""Onboarding and content routes: invitations (admin creates, invitee redeems), usage report, file metadata and template
variables. Administrative routes use the same live owner/admin check as the rest of `/admin`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from adapters.postgres.admin import Actor, AdminError
from adapters.postgres.admin_reference import ReferenceAdmin
from adapters.postgres.invitations import Invitations
from adapters.postgres.usage import usage_summary
from contracts.errors import DependencyUnavailable
from engine.control_plane.admin_api import _Body, _call, _service, get_actor

router = APIRouter(tags=["onboarding"])


def _invitations(request: Request) -> Invitations:
    return Invitations(_service(request))


def _references(request: Request) -> ReferenceAdmin:
    return ReferenceAdmin(_service(request))


class NewInvitation(_Body):
    workspace_id: str = Field(..., max_length=128)
    role: str = Field(..., max_length=16)
    ttl_hours: int = Field(default=72, ge=1, le=720)
    label: str | None = Field(default=None, max_length=100)


class Acceptance(_Body):
    token: str = Field(..., min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=100)


class NewFile(_Body):
    workspace_id: str = Field(..., max_length=128)
    name: str = Field(..., max_length=100)
    mime: str = Field(..., max_length=128)
    size_bytes: int = Field(..., ge=0)


class TemplateValue(_Body):
    value: str = Field(..., max_length=500)
    workspace_id: str | None = Field(default=None, max_length=128)


# ---- invitations ---------------------------------------------------------------------------------------

@router.post("/admin/invitations", status_code=201)
async def create_invitation(body: NewInvitation, actor: Actor = Depends(get_actor), request: Request = None):
    invitation_id, token, expires_at = await _call(_invitations(request).create(
        actor, body.workspace_id, body.role, body.ttl_hours, body.label))
    return {"invitation_id": invitation_id, "token": token, "expires_at": expires_at,
            "note": "the token is shown once; give it to the invitee, who redeems it at POST /api/v1/invitations/accept"}


@router.get("/admin/invitations")
async def list_invitations(actor: Actor = Depends(get_actor), request: Request = None):
    return {"invitations": await _call(_invitations(request).list(actor))}


@router.delete("/admin/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(invitation_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_invitations(request).revoke(actor, invitation_id))


@router.post("/invitations/accept", status_code=201)
async def accept_invitation(body: Acceptance, request: Request):
    """Public: the token is the credential. Rate limited per client address; every refusal is the same 404."""
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        limits = request.app.state.rate_limits
        client = request.client.host if request.client else "unknown"
        try:
            decision = await limiter.hit(f"invite:{client}", limits.invite_per_minute, limits.window_seconds)
        except DependencyUnavailable:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")
        if not decision.allowed:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", headers={"Retry-After": str(decision.retry_after)})
    result = await _call(_invitations(request).accept(body.token, body.display_name))
    return {**result, "note": "the API key is shown once; store it now"}


# ---- usage ---------------------------------------------------------------------------------------------

@router.get("/admin/usage")
async def usage(days: int = 30, actor: Actor = Depends(get_actor), request: Request = None):
    if not 1 <= days <= 366:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "days_invalid")
    service = _service(request)
    try:
        report: dict[str, Any] = await usage_summary(service._db, actor.principal.tenant_id, days)
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")
    price = getattr(request.app.state, "llm_price_per_million_tokens", 0.0) or 0.0
    if price:
        report["estimated_cost"] = round(report["total_tokens"] * price / 1_000_000, 6)
    return report


# ---- files (metadata) and template variables -----------------------------------------------------------

@router.post("/admin/files", status_code=201)
async def register_file(body: NewFile, actor: Actor = Depends(get_actor), request: Request = None):
    file_id = await _call(_references(request).register_file(actor, body.workspace_id, body.name, body.mime, body.size_bytes))
    return {"file_id": file_id, "note": "metadata only: the file's content is not stored by this service"}


@router.get("/admin/files")
async def list_files(workspace_id: str | None = None, actor: Actor = Depends(get_actor), request: Request = None):
    return {"files": await _call(_references(request).list_files(actor, workspace_id))}


@router.put("/admin/templates/{name}", status_code=204)
async def put_template(name: str, body: TemplateValue, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_references(request).set_template(actor, name, body.value, body.workspace_id))


@router.get("/admin/templates")
async def list_templates(actor: Actor = Depends(get_actor), request: Request = None):
    return {"templates": await _call(_references(request).list_templates(actor))}
