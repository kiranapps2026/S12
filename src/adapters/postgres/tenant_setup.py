"""Create a tenant with its first workspace, owner and API key (an operator action: it runs with the owner connection,
never through the API, because the API needs an owner to exist first)."""
from __future__ import annotations

import re
import uuid

import asyncpg

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.database import Database
from contracts.principal import Principal

SLUG = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
MUTATIONS = ("R", "W", "D", "IRREVERSIBLE")


class TenantSetupError(Exception):
    pass


async def create_tenant(database: Database, *, slug: str, name: str, owner_name: str, budget_pool: int = 10000,
                        max_mutation: str = "W", policy_version_id: str = "policy-1") -> dict:
    """One transaction: tenant, workspace `main`, an owner user with membership and connection, and the owner's API key.
    Returns the ids and the key (shown once; only its SHA-256 is stored). Refuses an existing tenant id."""
    if not SLUG.match(slug):
        raise TenantSetupError("slug must be 3-40 characters: lowercase letters, digits, hyphens, starting with a letter")
    if max_mutation not in MUTATIONS:
        raise TenantSetupError(f"max_mutation must be one of {MUTATIONS}")
    if budget_pool < 0:
        raise TenantSetupError("budget_pool must not be negative")
    for field, value in (("name", name), ("owner_name", owner_name)):
        if not value.strip() or len(value) > 100 or re.search(r"[\x00-\x1f\x7f]", value):
            raise TenantSetupError(f"{field} is empty, too long or has control characters")
    ids = {"tenant_id": slug, "workspace_id": f"ws_{uuid.uuid4().hex}", "user_id": f"usr_{uuid.uuid4().hex}",
           "membership_id": f"mem_{uuid.uuid4().hex}", "connection_id": f"conn_{uuid.uuid4().hex}"}
    try:
        return await _create(database, ids, slug, name, owner_name, budget_pool, max_mutation, policy_version_id)
    except asyncpg.UniqueViolationError:                       # also the loser of a concurrent creation of one slug
        raise TenantSetupError(f"tenant '{slug}' already exists") from None


async def _create(database, ids, slug, name, owner_name, budget_pool, max_mutation, policy_version_id) -> dict:
    async with database.transaction() as c:
        await c.execute("SELECT set_config('app.current_tenant', $1, true)", slug)
        await c.execute("INSERT INTO tenants (tenant_id, name, budget_pool, max_mutation, policy_version_id)"
                        " VALUES ($1,$2,$3,$4,$5)", slug, name, budget_pool, max_mutation, policy_version_id)
        await c.execute("INSERT INTO workspaces (workspace_id, tenant_id, name, created_by) VALUES ($1,$2,'main','bootstrap')",
                        ids["workspace_id"], slug)
        await c.execute("INSERT INTO users (user_id, tenant_id, display_name, created_by) VALUES ($1,$2,$3,'bootstrap')",
                        ids["user_id"], slug, owner_name)
        await c.execute("INSERT INTO memberships (membership_id, tenant_id, user_id, workspace_id, role, created_by)"
                        " VALUES ($1,$2,$3,$4,'owner','bootstrap')", ids["membership_id"], slug, ids["user_id"], ids["workspace_id"])
        await c.execute("INSERT INTO connections (connection_id, tenant_id, user_id, workspace_id, created_by)"
                        " VALUES ($1,$2,$3,$4,'bootstrap')", ids["connection_id"], slug, ids["user_id"], ids["workspace_id"])
        key_id, key = await PostgresApiKeyAuthenticator(database).issue_with_id(
            Principal(slug, ids["workspace_id"], ids["user_id"], ids["membership_id"], ids["connection_id"], ""),
            label="owner (bootstrap)", created_by="bootstrap", connection=c)
        await c.execute("INSERT INTO admin_audit (tenant_id, actor_user_id, actor_membership_id, action, target_type, target_id,"
                        " details) VALUES ($1,'bootstrap',$2,'tenant.create','tenant',$1,$3::jsonb)", slug,
                        ids["membership_id"], '{"owner_user_id": "%s"}' % ids["user_id"])
    return {**ids, "api_key_id": key_id, "api_key": key}
