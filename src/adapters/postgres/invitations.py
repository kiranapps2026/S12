"""Invitations: an administrator invites someone into a workspace with a role; the invitee redeems a one-time token and
receives their own user, membership, connection and API key. The token is shown once and stored only as its SHA-256.

Rules: the role ceiling of the admin API applies (nobody invites above their own role); a token works once, until it
expires, unless revoked; redeeming is atomic (two people racing for one token: exactly one wins); the tenant and the
workspace must still be active; the created user is a person (never a service user)."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime

from adapters.postgres.admin import RANK, Actor, AdminError, AdminService
from adapters.postgres.admin_access import ROLES, _name
from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from contracts.principal import Principal

TOKEN_PREFIX = "inv_supra_"
MAX_TTL_HOURS = 24 * 30


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Invitations:
    def __init__(self, admin: AdminService) -> None:
        self._a = admin
        self._db = admin._db

    async def create(self, actor: Actor, workspace_id: str, role: str, ttl_hours: int = 72,
                     label: str | None = None) -> tuple[str, str, datetime]:
        """(invitation_id, token, expires_at); the token cannot be shown again."""
        if role not in ROLES:
            raise AdminError(422, "role_invalid")
        if RANK[role] > RANK[actor.role]:
            raise AdminError(403, "role_exceeds_yours")
        if not 1 <= ttl_hours <= MAX_TTL_HOURS:
            raise AdminError(422, "ttl_invalid")
        label = _name(label, "label")
        tenant = actor.principal.tenant_id
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        invitation_id = f"invite_{uuid.uuid4().hex}"
        async with self._db.tenant_transaction(tenant) as c:
            if await c.fetchval("SELECT 1 FROM workspaces WHERE workspace_id = $1 AND tenant_id = $2", workspace_id, tenant) is None:
                raise AdminError(404, "workspace_not_found")
            expires_at = await c.fetchval(
                "INSERT INTO invitations (invitation_id, token_hash, tenant_id, workspace_id, role, label, created_by, expires_at)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7, now() + make_interval(hours => $8)) RETURNING expires_at",
                invitation_id, hash_token(token), tenant, workspace_id, role, label, actor.principal.user_id, ttl_hours)
            await self._a._audit(c, actor, "invitation.create", "invitation", invitation_id, workspace_id=workspace_id,
                                 role=role, label=label)
        return invitation_id, token, expires_at

    async def list(self, actor: Actor) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT invitation_id, workspace_id, role, label, created_by, created_at, expires_at, revoked_at, accepted_at,"
                " accepted_user_id, CASE WHEN accepted_at IS NOT NULL THEN 'accepted' WHEN revoked_at IS NOT NULL THEN 'revoked'"
                " WHEN expires_at <= now() THEN 'expired' ELSE 'pending' END AS status FROM invitations"
                " WHERE tenant_id = $1 ORDER BY created_at DESC, invitation_id", actor.principal.tenant_id)
        return [dict(r) for r in rows]

    async def revoke(self, actor: Actor, invitation_id: str) -> None:
        tenant = actor.principal.tenant_id
        async with self._db.tenant_transaction(tenant) as c:
            row = await c.fetchrow("SELECT role FROM invitations WHERE invitation_id = $1 AND tenant_id = $2 AND accepted_at IS NULL"
                                   " AND revoked_at IS NULL FOR UPDATE", invitation_id, tenant)
            if row is None:
                raise AdminError(404, "invitation_not_found")
            if RANK[row["role"]] > RANK[actor.role]:
                raise AdminError(403, "role_exceeds_yours")
            await c.execute("UPDATE invitations SET revoked_at = now() WHERE invitation_id = $1", invitation_id)
            await self._a._audit(c, actor, "invitation.revoke", "invitation", invitation_id)

    async def accept(self, token: str, display_name: str | None = None) -> dict:
        """Redeem a token (no authentication: the token is the credential). Returns the new identity and its API key.
        Every refusal is the same 404 `invitation_invalid`, so a caller cannot tell an unknown token from a used one."""
        display_name = _name(display_name, "display_name")
        if not token.startswith(TOKEN_PREFIX):
            raise AdminError(404, "invitation_invalid")
        digest = hash_token(token)
        async with self._db.transaction() as c:
            found = await c.fetchrow("SELECT invitation_id, tenant_id, workspace_id, role, created_by FROM invitations"
                                     " WHERE token_hash = $1 AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
                                     " FOR UPDATE", digest)
            if found is None:
                raise AdminError(404, "invitation_invalid")
            tenant = found["tenant_id"]
            await c.execute("SELECT set_config('app.current_tenant', $1, true)", tenant)
            active = await c.fetchval("SELECT 1 FROM tenants WHERE tenant_id = $1 AND status = 'active'", tenant)
            workspace = await c.fetchval("SELECT 1 FROM workspaces WHERE workspace_id = $1 AND tenant_id = $2",
                                         found["workspace_id"], tenant)
            if active is None or workspace is None:
                raise AdminError(404, "invitation_invalid")
            ids = {"user_id": f"usr_{uuid.uuid4().hex}", "membership_id": f"mem_{uuid.uuid4().hex}",
                   "connection_id": f"conn_{uuid.uuid4().hex}"}
            await c.execute("INSERT INTO users (user_id, tenant_id, display_name, created_by) VALUES ($1,$2,$3,$4)",
                            ids["user_id"], tenant, display_name, found["created_by"])
            await c.execute("INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role, created_by)"
                            " VALUES ($1,$2,$3,$4,$5,$6)", ids["membership_id"], tenant, ids["user_id"],
                            found["workspace_id"], found["role"], found["created_by"])
            await c.execute("INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id, created_by)"
                            " VALUES ($1,$2,$3,$4,$5)", ids["connection_id"], tenant, ids["user_id"], found["workspace_id"],
                            found["created_by"])
            key_id, key = await PostgresApiKeyAuthenticator(self._db).issue_with_id(
                Principal(tenant, found["workspace_id"], ids["user_id"], ids["membership_id"], ids["connection_id"], ""),
                label="invitation", created_by=found["created_by"], connection=c)
            await c.execute("UPDATE invitations SET accepted_at = now(), accepted_user_id = $2 WHERE invitation_id = $1",
                            found["invitation_id"], ids["user_id"])
            await c.execute("INSERT INTO admin_audit (tenant_id, actor_user_id, actor_membership_id, action, target_type,"
                            " target_id, details) VALUES ($1,$2,$3,'invitation.accept','invitation',$4,$5::jsonb)", tenant,
                            ids["user_id"], ids["membership_id"], found["invitation_id"], '{"role": "%s"}' % found["role"])
        return {**ids, "tenant_id": tenant, "workspace_id": found["workspace_id"], "role": found["role"],
                "api_key_id": key_id, "api_key": key}
