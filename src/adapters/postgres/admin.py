"""Administration of one tenant: API keys, webhook/MCP endpoints and secrets, event schemas and schedules.

Rules (every one is tested):
- Only an ACTIVE owner or admin of the tenant may administer it, checked LIVE on every request (a role
  removed a minute ago is refused now).
- An administrator can create credentials only for memberships whose role is NOT higher than their own
  (an admin cannot mint an owner's key), and only inside their own tenant (other tenants' ids are 404).
- Secrets and API keys are returned ONCE, at creation. Listings never contain a secret, a key or a hash.
- Every mutation and its audit row are written in ONE transaction: if the audit row cannot be written,
  the change is not made. Audit details hold ids, versions and labels, never a secret.
- Tables without row-level security (api_keys, webhook_credentials, event_schedules) are always filtered by
  the caller's tenant here.
"""
from __future__ import annotations

import json
import types
import uuid
from dataclasses import dataclass

from adapters.postgres.api_keys import PostgresApiKeyAuthenticator
from adapters.postgres.database import Database
from adapters.postgres.event_schemas import PostgresEventSchemas
from adapters.postgres.schedules import PostgresScheduleStore
from adapters.postgres.webhook_credentials import PostgresWebhookCredentials
from contracts.principal import Principal
from contracts.schedule import Schedule
from engine.gateway import schema as schema_check
from engine.gateway.schedule import check_schedule

RANK = types.MappingProxyType({"viewer": 0, "member": 1, "admin": 2, "owner": 3})
ADMIN_ROLES = frozenset({"admin", "owner"})
EVENT_SYSTEMS = frozenset({"ghl", "stripe", "custom", "mcp", "api", "cron"})
ENDPOINT_SYSTEMS = frozenset({"ghl", "stripe", "custom", "mcp"})
MAX_SCHEMA_CHARS = 32768
MAX_PAYLOAD_CHARS = 16384
MAX_LABEL = 100


class AdminError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass(frozen=True)
class Actor:
    principal: Principal
    role: str


class AdminService:
    def __init__(self, database: Database, credentials: PostgresWebhookCredentials | None) -> None:
        self._db = database
        self._credentials = credentials
        self._keys = PostgresApiKeyAuthenticator(database)
        self._schemas = PostgresEventSchemas(database)
        self._schedules = PostgresScheduleStore(database)

    # ---- who may administer ----------------------------------------------------------------------

    async def authorize(self, principal: Principal) -> Actor:
        """The caller's live role, or 403. The tenant, the user and the membership must all be active."""
        async with self._db.tenant_transaction(principal.tenant_id) as c:
            row = await c.fetchrow(
                "SELECT m.role, m.is_active, m.revoked_at, m.user_id, u.status AS user_status, t.status AS tenant_status"
                "  FROM memberships m JOIN users u ON u.user_id = m.user_id JOIN tenants t ON t.tenant_id = m.tenant_id"
                " WHERE m.membership_id = $1 AND m.tenant_id = $2", principal.membership_id, principal.tenant_id)
        if (row is None or not row["is_active"] or row["revoked_at"] is not None or row["user_id"] != principal.user_id
                or row["user_status"] != "active" or row["tenant_status"] != "active"
                or row["role"] not in ADMIN_ROLES):
            raise AdminError(403, "admin_required")
        return Actor(principal, row["role"])

    # ---- helpers ---------------------------------------------------------------------------------

    async def _audit(self, c, actor: Actor, action: str, target_type: str, target_id: str, **details) -> None:
        await c.execute(
            "INSERT INTO admin_audit (tenant_id, actor_user_id, actor_membership_id, action, target_type, target_id,"
            " details) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)", actor.principal.tenant_id, actor.principal.user_id,
            actor.principal.membership_id, action, target_type, target_id, json.dumps(details))

    async def _identity(self, c, actor: Actor, membership_id: str, connection_id: str, scope: str) -> Principal:
        """The identity a new credential will act as. Both rows must be in the actor's tenant (RLS), agree with each
        other, be active, and the membership's role must not exceed the actor's."""
        tenant = actor.principal.tenant_id
        m = await c.fetchrow("SELECT user_id, workspace_id, role, is_active, revoked_at FROM memberships"
                             " WHERE membership_id = $1 AND tenant_id = $2", membership_id, tenant)
        if m is None:
            raise AdminError(404, "membership_not_found")
        if not m["is_active"] or m["revoked_at"] is not None:
            raise AdminError(409, "membership_inactive")
        if RANK[m["role"]] > RANK[actor.role]:
            raise AdminError(403, "role_exceeds_yours")
        user = await c.fetchval("SELECT status FROM users WHERE user_id = $1 AND tenant_id = $2", m["user_id"], tenant)
        if user != "active":
            raise AdminError(409, "user_inactive")
        conn = await c.fetchrow("SELECT user_id, workspace_id, status, (expires_at IS NOT NULL AND expires_at <= now())"
                                " AS expired FROM connections WHERE connection_id = $1 AND tenant_id = $2",
                                connection_id, tenant)
        if conn is None:
            raise AdminError(404, "connection_not_found")
        if conn["user_id"] != m["user_id"] or conn["workspace_id"] != m["workspace_id"]:
            raise AdminError(409, "connection_mismatch")
        if conn["status"] != "active" or conn["expired"]:
            raise AdminError(409, "connection_inactive")
        return Principal(tenant, m["workspace_id"], m["user_id"], membership_id, connection_id, scope or "")

    @staticmethod
    def _label(label: str | None) -> str | None:
        if label is not None and (not label.strip() or len(label) > MAX_LABEL):
            raise AdminError(422, "label_invalid")
        return label

    # ---- API keys --------------------------------------------------------------------------------

    async def issue_api_key(self, actor: Actor, membership_id: str, connection_id: str, resource_scope: str = "",
                            label: str | None = None) -> tuple[str, str]:
        """(key_id, key). The key is shown once; only its hash is stored."""
        label = self._label(label)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            identity = await self._identity(c, actor, membership_id, connection_id, resource_scope)
            key_id, key = await self._keys.issue_with_id(identity, label=label,
                                                         created_by=actor.principal.user_id, connection=c)
            await self._audit(c, actor, "api_key.issue", "api_key", key_id, user_id=identity.user_id,
                              membership_id=membership_id, label=label)
        return key_id, key

    async def list_api_keys(self, actor: Actor) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT key_id, user_id, workspace_id, membership_id, connection_id, resource_scope, is_active, label,"
                " created_by, created_at, revoked_at FROM api_keys WHERE tenant_id = $1 ORDER BY created_at, key_id",
                actor.principal.tenant_id)
        return [dict(r) for r in rows]

    async def revoke_api_key(self, actor: Actor, key_id: str) -> None:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            done = await c.fetchval("UPDATE api_keys SET is_active = false, revoked_at = now()"
                                    " WHERE key_id = $1 AND tenant_id = $2 AND is_active RETURNING key_id",
                                    key_id, actor.principal.tenant_id)
            if done is None:
                raise AdminError(404, "api_key_not_found")
            await self._audit(c, actor, "api_key.revoke", "api_key", key_id)

    # ---- webhook / MCP endpoints and their signing secrets ---------------------------------------------

    def _need_credentials(self) -> PostgresWebhookCredentials:
        if self._credentials is None:
            raise AdminError(503, "webhooks_unavailable")
        return self._credentials

    async def issue_endpoint(self, actor: Actor, source_system: str, membership_id: str, connection_id: str,
                             resource_scope: str = "", label: str | None = None) -> tuple[str, str]:
        """(endpoint_id, secret). The secret is shown once. The identity should be a dedicated service user
        (ruling R-AT); the API enforces the tenant, the role ceiling and the consistency of the identity."""
        credentials = self._need_credentials()
        if source_system not in ENDPOINT_SYSTEMS:
            raise AdminError(422, "source_system_invalid")
        label = self._label(label)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            identity = await self._identity(c, actor, membership_id, connection_id, resource_scope)
            endpoint_id, secret = await credentials.issue(identity, source_system, label=label,
                                                          created_by=actor.principal.user_id, connection=c)
            await self._audit(c, actor, "endpoint.issue", "endpoint", endpoint_id, source_system=source_system,
                              user_id=identity.user_id, label=label)
        return endpoint_id, secret

    async def _endpoint_source(self, c, actor: Actor, endpoint_id: str) -> str:
        source = await c.fetchval(
            "SELECT source_system FROM webhook_credentials WHERE endpoint_id = $1 AND tenant_id = $2"
            " AND status = 'active'", endpoint_id, actor.principal.tenant_id)
        if source is None:
            raise AdminError(404, "endpoint_not_found")
        return source

    async def rotate_endpoint(self, actor: Actor, endpoint_id: str, grace: str = "24 hours") -> str:
        """A new secret (shown once); the current one keeps working for `grace` (default 24 hours)."""
        credentials = self._need_credentials()
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            source = await self._endpoint_source(c, actor, endpoint_id)
            try:
                secret = await credentials.rotate(endpoint_id, source, grace, created_by=actor.principal.user_id,
                                                  connection=c)
            except ValueError:
                raise AdminError(422, "grace_invalid") from None
            await self._audit(c, actor, "endpoint.rotate", "endpoint", endpoint_id, source_system=source, grace=grace)
        return secret

    async def list_endpoints(self, actor: Actor) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT endpoint_id, source_system, status, workspace_id, user_id, membership_id, connection_id, label,"
                " created_by, created_at, retiring_until, last_verified_at, expires_at FROM webhook_credentials"
                " WHERE tenant_id = $1 AND status IN ('active','retiring') ORDER BY created_at, credential_id",
                actor.principal.tenant_id)
        return [dict(r) for r in rows]

    async def revoke_endpoint(self, actor: Actor, endpoint_id: str) -> None:
        """Every secret of the endpoint stops working immediately (no grace period)."""
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            source = await self._endpoint_source(c, actor, endpoint_id)
            await c.execute("UPDATE webhook_credentials SET status = 'retired', retiring_until = NULL"
                            " WHERE endpoint_id = $1 AND tenant_id = $2 AND status IN ('active','retiring')",
                            endpoint_id, actor.principal.tenant_id)
            await self._audit(c, actor, "endpoint.revoke", "endpoint", endpoint_id, source_system=source)

    # ---- event schemas ---------------------------------------------------------------------------------

    @staticmethod
    def _schema_key(source_system: str, event_type: str) -> None:
        import re
        if source_system not in EVENT_SYSTEMS:
            raise AdminError(422, "source_system_invalid")
        if not re.match(r"^[A-Za-z0-9_.:\-]{1,64}$", event_type):
            raise AdminError(422, "event_type_invalid")

    async def put_schema(self, actor: Actor, source_system: str, event_type: str, schema: dict) -> int:
        """Register the next version of a payload schema. Refused if it uses anything the validator does not enforce."""
        self._schema_key(source_system, event_type)
        if len(json.dumps(schema)) > MAX_SCHEMA_CHARS:
            raise AdminError(413, "schema_too_large")
        try:
            schema_check.check_schema(schema)
        except schema_check.SchemaError as exc:
            raise AdminError(422, f"schema_unsupported: {exc}") from None
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            version = await self._schemas.register(actor.principal.tenant_id, source_system, event_type, schema,
                                                   created_by=actor.principal.user_id, connection=c)
            await self._audit(c, actor, "event_schema.put", "event_schema", f"{source_system}/{event_type}",
                              version=version)
        return version

    async def list_schemas(self, actor: Actor) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT DISTINCT ON (source_system, event_type) source_system, event_type, schema_version, is_active,"
                " created_by, created_at FROM event_schemas WHERE tenant_id = $1"
                " ORDER BY source_system, event_type, schema_version DESC", actor.principal.tenant_id)
        return [dict(r) for r in rows]

    async def get_schema(self, actor: Actor, source_system: str, event_type: str) -> dict:
        self._schema_key(source_system, event_type)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT schema_version, schema, is_active, created_by, created_at FROM event_schemas"
                " WHERE tenant_id = $1 AND source_system = $2 AND event_type = $3 ORDER BY schema_version DESC",
                actor.principal.tenant_id, source_system, event_type)
        if not rows:
            raise AdminError(404, "event_schema_not_found")
        return {"source_system": source_system, "event_type": event_type,
                "versions": [{**dict(r), "schema": json.loads(r["schema"])} for r in rows]}

    async def deactivate_schema(self, actor: Actor, source_system: str, event_type: str, version: int) -> None:
        """Stop using one version. If it was the newest active one, the previous active version applies; if none is
        active, the event type is no longer registered and its events are refused."""
        self._schema_key(source_system, event_type)
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            done = await c.fetchval(
                "UPDATE event_schemas SET is_active = false WHERE tenant_id = $1 AND source_system = $2"
                " AND event_type = $3 AND schema_version = $4 AND is_active RETURNING schema_version",
                actor.principal.tenant_id, source_system, event_type, version)
            if done is None:
                raise AdminError(404, "event_schema_not_found")
            await self._audit(c, actor, "event_schema.deactivate", "event_schema", f"{source_system}/{event_type}",
                              version=version)

    # ---- schedules -------------------------------------------------------------------------------------

    async def create_schedule(self, actor: Actor, *, event_type: str, payload: dict, kind: str, membership_id: str,
                              connection_id: str, resource_scope: str = "", interval_seconds: int | None = None,
                              anchor=None, at_seconds: int | None = None, weekday: int | None = None,
                              label: str | None = None) -> str:
        """Create a schedule (its id is generated). Its event type must be registered for the `cron` source and
        the payload must satisfy that schema, so a schedule that could never run is refused now."""
        label = self._label(label)
        if len(json.dumps(payload)) > MAX_PAYLOAD_CHARS:
            raise AdminError(413, "payload_too_large")
        self._schema_key("cron", event_type)
        tenant = actor.principal.tenant_id
        async with self._db.tenant_transaction(tenant) as c:
            identity = await self._identity(c, actor, membership_id, connection_id, resource_scope)
            schedule = Schedule(schedule_id=str(uuid.uuid4()), principal=identity, event_type=event_type,
                                payload=payload, kind=kind, anchor=anchor, interval_seconds=interval_seconds,
                                at_seconds=at_seconds, weekday=weekday)
            try:
                check_schedule(schedule)
            except ValueError as exc:
                raise AdminError(422, f"schedule_invalid: {exc}") from None
            registered = await c.fetchrow(
                "SELECT schema FROM event_schemas WHERE tenant_id = $1 AND source_system = 'cron' AND event_type = $2"
                " AND is_active ORDER BY schema_version DESC LIMIT 1", tenant, event_type)
            if registered is None:
                raise AdminError(422, "event_type_not_registered")
            problem = schema_check.validate(json.loads(registered["schema"]), payload)
            if problem is not None:
                raise AdminError(422, "payload_invalid")
            await self._schedules.create(schedule, label=label, created_by=actor.principal.user_id, connection=c)
            await self._audit(c, actor, "schedule.create", "schedule", schedule.schedule_id, kind=kind,
                              event_type=event_type, user_id=identity.user_id, label=label)
        return schedule.schedule_id

    async def list_schedules(self, actor: Actor) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch(
                "SELECT schedule_id, event_type, kind, anchor, interval_seconds, at_seconds, weekday, is_active,"
                " last_planned, workspace_id, user_id, membership_id, connection_id, label, created_by, created_at"
                " FROM event_schedules WHERE tenant_id = $1 ORDER BY created_at, schedule_id", actor.principal.tenant_id)
        return [dict(r) for r in rows]

    async def deactivate_schedule(self, actor: Actor, schedule_id: str) -> None:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            done = await c.fetchval("UPDATE event_schedules SET is_active = false WHERE schedule_id = $1"
                                    " AND tenant_id = $2 AND is_active RETURNING schedule_id",
                                    schedule_id, actor.principal.tenant_id)
            if done is None:
                raise AdminError(404, "schedule_not_found")
            await self._audit(c, actor, "schedule.deactivate", "schedule", schedule_id)

    # ---- audit -----------------------------------------------------------------------------------------

    async def audit_trail(self, actor: Actor, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch("SELECT audit_id, actor_user_id, action, target_type, target_id, details, occurred_at"
                                 " FROM admin_audit ORDER BY audit_id DESC LIMIT $1", limit)
        return [{**dict(r), "details": json.loads(r["details"])} for r in rows]
