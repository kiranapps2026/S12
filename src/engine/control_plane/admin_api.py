"""Administration API (`/api/v1/admin/...`): API keys, webhook/MCP endpoints and secrets, event schemas, schedules.

Authorization: the caller's Bearer API key must belong to an ACTIVE owner or admin of the tenant, checked live
on every request. Everything is scoped to that tenant. Secrets and keys appear only in the response that creates
them. See adapters/postgres/admin.py for the rules that keep an administrator inside their own tenant and role.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from adapters.postgres.admin import Actor, AdminError, AdminService
from contracts.errors import DependencyUnavailable
from contracts.principal import Principal
from engine.control_plane.api import get_principal

router = APIRouter(prefix="/admin", tags=["admin"])


def _service(request: Request) -> AdminService:
    service = getattr(request.app.state, "admin", None)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "admin_unavailable")
    return service


async def get_actor(request: Request, principal: Principal = Depends(get_principal)) -> Actor:
    try:
        return await _service(request).authorize(principal)
    except AdminError as error:
        raise HTTPException(error.status, error.reason)
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")


async def _call(coro):
    """Run an admin operation, mapping its refusals to HTTP errors."""
    try:
        return await coro
    except AdminError as error:
        raise HTTPException(error.status, error.reason)
    except DependencyUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable")


class _Body(BaseModel):
    model_config = {"extra": "forbid"}


class NewApiKey(_Body):
    membership_id: str = Field(..., max_length=128)
    connection_id: str = Field(..., max_length=128)
    resource_scope: str = Field(default="", max_length=128)
    label: str | None = Field(default=None, max_length=100)


class NewEndpoint(NewApiKey):
    source_system: str = Field(..., max_length=32)


class Rotation(_Body):
    grace: str = Field(default="24 hours", pattern=r"^\d{1,4} (minutes|hours|days)$")


class SchemaBody(_Body):
    schema_: dict[str, Any] = Field(..., alias="schema")


class NewSchedule(_Body):
    event_type: str = Field(..., max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    kind: str = Field(..., max_length=16)
    membership_id: str = Field(..., max_length=128)
    connection_id: str = Field(..., max_length=128)
    resource_scope: str = Field(default="", max_length=128)
    interval_seconds: int | None = None
    anchor: datetime | None = None
    at_seconds: int | None = None
    weekday: int | None = None
    label: str | None = Field(default=None, max_length=100)


# ---- API keys ------------------------------------------------------------------------------------------

@router.post("/api-keys", status_code=201)
async def issue_api_key(body: NewApiKey, actor: Actor = Depends(get_actor), request: Request = None):
    key_id, key = await _call(_service(request).issue_api_key(
        actor, body.membership_id, body.connection_id, body.resource_scope, body.label))
    return {"key_id": key_id, "api_key": key, "note": "shown once; store it now"}


@router.get("/api-keys")
async def list_api_keys(actor: Actor = Depends(get_actor), request: Request = None):
    return {"api_keys": await _call(_service(request).list_api_keys(actor))}


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_service(request).revoke_api_key(actor, key_id))


# ---- webhook / MCP endpoints ---------------------------------------------------------------------------

@router.post("/endpoints", status_code=201)
async def issue_endpoint(body: NewEndpoint, actor: Actor = Depends(get_actor), request: Request = None):
    endpoint_id, secret = await _call(_service(request).issue_endpoint(
        actor, body.source_system, body.membership_id, body.connection_id, body.resource_scope, body.label))
    path = "mcp" if body.source_system == "mcp" else f"webhooks/{body.source_system}"
    return {"endpoint_id": endpoint_id, "signing_secret": secret, "url_path": f"/api/v1/{path}/{endpoint_id}",
            "note": "the secret is shown once; store it now"}


@router.get("/endpoints")
async def list_endpoints(actor: Actor = Depends(get_actor), request: Request = None):
    return {"endpoints": await _call(_service(request).list_endpoints(actor))}


@router.post("/endpoints/{endpoint_id}/rotate")
async def rotate_endpoint(endpoint_id: str, body: Rotation | None = None, actor: Actor = Depends(get_actor),
                          request: Request = None):
    secret = await _call(_service(request).rotate_endpoint(actor, endpoint_id, (body or Rotation()).grace))
    return {"endpoint_id": endpoint_id, "signing_secret": secret,
            "note": "the previous secret keeps working for the grace period; the new one is shown once"}


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def revoke_endpoint(endpoint_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_service(request).revoke_endpoint(actor, endpoint_id))


# ---- event schemas -------------------------------------------------------------------------------------

@router.put("/event-schemas/{source_system}/{event_type}", status_code=201)
async def put_schema(source_system: str, event_type: str, body: SchemaBody, actor: Actor = Depends(get_actor),
                     request: Request = None):
    version = await _call(_service(request).put_schema(actor, source_system, event_type, body.schema_))
    return {"source_system": source_system, "event_type": event_type, "version": version}


@router.get("/event-schemas")
async def list_schemas(actor: Actor = Depends(get_actor), request: Request = None):
    return {"event_schemas": await _call(_service(request).list_schemas(actor))}


@router.get("/event-schemas/{source_system}/{event_type}")
async def get_schema(source_system: str, event_type: str, actor: Actor = Depends(get_actor), request: Request = None):
    return await _call(_service(request).get_schema(actor, source_system, event_type))


@router.delete("/event-schemas/{source_system}/{event_type}/{version}", status_code=204)
async def deactivate_schema(source_system: str, event_type: str, version: int, actor: Actor = Depends(get_actor),
                            request: Request = None):
    await _call(_service(request).deactivate_schema(actor, source_system, event_type, version))


# ---- schedules -----------------------------------------------------------------------------------------

@router.post("/schedules", status_code=201)
async def create_schedule(body: NewSchedule, actor: Actor = Depends(get_actor), request: Request = None):
    schedule_id = await _call(_service(request).create_schedule(
        actor, event_type=body.event_type, payload=body.payload, kind=body.kind, membership_id=body.membership_id,
        connection_id=body.connection_id, resource_scope=body.resource_scope, interval_seconds=body.interval_seconds,
        anchor=body.anchor, at_seconds=body.at_seconds, weekday=body.weekday, label=body.label))
    return {"schedule_id": schedule_id}


@router.get("/schedules")
async def list_schedules(actor: Actor = Depends(get_actor), request: Request = None):
    return {"schedules": await _call(_service(request).list_schedules(actor))}


@router.delete("/schedules/{schedule_id}", status_code=204)
async def deactivate_schedule(schedule_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_service(request).deactivate_schedule(actor, schedule_id))


# ---- audit ---------------------------------------------------------------------------------------------

@router.get("/audit")
async def audit_trail(limit: int = 100, actor: Actor = Depends(get_actor), request: Request = None):
    return {"audit": await _call(_service(request).audit_trail(actor, limit))}
