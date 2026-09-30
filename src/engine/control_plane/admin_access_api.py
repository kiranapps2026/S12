"""User, membership, connection and grant management (`/api/v1/admin/...`).

Same authorization as the rest of the admin API (live owner/admin check). The rules (role ceiling, no self change,
last-owner protection, grant restrictions) are enforced in adapters/postgres/admin_access.py.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from adapters.postgres.admin import Actor
from adapters.postgres.admin_access import AccessAdmin
from engine.control_plane.admin_api import _Body, _call, _service, get_actor

router = APIRouter(prefix="/admin", tags=["admin-access"])


def _access(request: Request) -> AccessAdmin:
    return AccessAdmin(_service(request))


class NewWorkspace(_Body):
    name: str = Field(..., max_length=100)


class NewUser(_Body):
    display_name: str | None = Field(default=None, max_length=100)
    is_service: bool = False


class UserStatus(_Body):
    status: str = Field(..., max_length=16)


class NewMembership(_Body):
    user_id: str = Field(..., max_length=128)
    workspace_id: str = Field(..., max_length=128)
    role: str = Field(..., max_length=16)


class RoleBody(_Body):
    role: str = Field(..., max_length=16)


class NewConnection(_Body):
    user_id: str = Field(..., max_length=128)
    workspace_id: str = Field(..., max_length=128)
    expires_at: datetime | None = None


class NewGrant(NewConnection):
    capability_id: str = Field(..., max_length=128)


@router.post("/workspaces", status_code=201)
async def create_workspace(body: NewWorkspace, actor: Actor = Depends(get_actor), request: Request = None):
    return {"workspace_id": await _call(_access(request).create_workspace(actor, body.name))}


@router.get("/workspaces")
async def list_workspaces(actor: Actor = Depends(get_actor), request: Request = None):
    return {"workspaces": await _call(_access(request).list_workspaces(actor))}


@router.post("/users", status_code=201)
async def create_user(body: NewUser, actor: Actor = Depends(get_actor), request: Request = None):
    return {"user_id": await _call(_access(request).create_user(actor, body.display_name, body.is_service))}


@router.get("/users")
async def list_users(actor: Actor = Depends(get_actor), request: Request = None):
    return {"users": await _call(_access(request).list_users(actor))}


@router.post("/users/{user_id}/status", status_code=204)
async def change_user_status(user_id: str, body: UserStatus, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_access(request).set_user_status(actor, user_id, body.status))


@router.post("/memberships", status_code=201)
async def add_membership(body: NewMembership, actor: Actor = Depends(get_actor), request: Request = None):
    return {"membership_id": await _call(_access(request).add_membership(
        actor, body.user_id, body.workspace_id, body.role))}


@router.get("/memberships")
async def list_memberships(user_id: str | None = None, actor: Actor = Depends(get_actor), request: Request = None):
    return {"memberships": await _call(_access(request).list_memberships(actor, user_id))}


@router.post("/memberships/{membership_id}/role", status_code=204)
async def change_role(membership_id: str, body: RoleBody, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_access(request).set_role(actor, membership_id, body.role))


@router.delete("/memberships/{membership_id}", status_code=204)
async def remove_membership(membership_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_access(request).remove_membership(actor, membership_id))


@router.post("/connections", status_code=201)
async def create_connection(body: NewConnection, actor: Actor = Depends(get_actor), request: Request = None):
    return {"connection_id": await _call(_access(request).create_connection(
        actor, body.user_id, body.workspace_id, body.expires_at))}


@router.get("/connections")
async def list_connections(user_id: str | None = None, actor: Actor = Depends(get_actor), request: Request = None):
    return {"connections": await _call(_access(request).list_connections(actor, user_id))}


@router.post("/connections/{connection_id}/revoke", status_code=204)
async def revoke_connection(connection_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_access(request).revoke_connection(actor, connection_id))


@router.get("/capabilities")
async def list_capabilities(actor: Actor = Depends(get_actor), request: Request = None):
    return {"capabilities": await _call(_access(request).list_capabilities(actor))}


@router.post("/grants", status_code=201)
async def grant(body: NewGrant, actor: Actor = Depends(get_actor), request: Request = None):
    return {"grant_id": await _call(_access(request).grant(
        actor, body.user_id, body.workspace_id, body.capability_id, body.expires_at))}


@router.get("/grants")
async def list_grants(user_id: str | None = None, actor: Actor = Depends(get_actor), request: Request = None):
    return {"grants": await _call(_access(request).list_grants(actor, user_id))}


@router.delete("/grants/{grant_id}", status_code=204)
async def revoke_grant(grant_id: str, actor: Actor = Depends(get_actor), request: Request = None):
    await _call(_access(request).revoke_grant(actor, grant_id))
