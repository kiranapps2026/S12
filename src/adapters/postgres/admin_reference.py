"""Writers for what S1 reference resolution reads: previous results ($ref), file metadata ($file) and template variables.

  * results are written by the system after a run (S15 will call `record_result`); nobody can post one through the API;
  * files: only METADATA is registered (name, type, size); this schema has no content store, so the bytes live elsewhere;
  * template variables are set by administrators only (they are substituted into requests, so they are configuration).
Nothing is ever deleted (the application role has no DELETE); a name is overwritten instead."""
from __future__ import annotations

import re
import uuid

from adapters.postgres.admin import Actor, AdminError, AdminService
from adapters.postgres.database import Database

MAX_FILE_BYTES = 100 * 1024 * 1024
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
MIME = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,60}/[a-z0-9][a-z0-9.+-]{0,60}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class PostgresResultWriter:
    """The writer S15 uses after a run: the text form of a result, kept for `$ref` in later requests of the conversation."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def record_result(self, *, tenant_id: str, user_id: str, conversation_id: str, summary: str) -> None:
        if not summary or len(summary) > 4000:
            raise ValueError("a result summary is 1-4000 characters")
        async with self._db.tenant_transaction(tenant_id) as c:
            await c.execute("INSERT INTO conversation_results (tenant_id, user_id, conversation_id, summary) VALUES ($1,$2,$3,$4)",
                            tenant_id, user_id, conversation_id, summary)


class ReferenceAdmin:
    def __init__(self, admin: AdminService) -> None:
        self._a = admin
        self._db = admin._db

    async def _workspace(self, c, actor: Actor, workspace_id: str) -> None:
        if await c.fetchval("SELECT 1 FROM workspaces WHERE workspace_id = $1 AND tenant_id = $2",
                            workspace_id, actor.principal.tenant_id) is None:
            raise AdminError(404, "workspace_not_found")

    async def register_file(self, actor: Actor, workspace_id: str, name: str, mime: str, size_bytes: int) -> str:
        """Register (or update) a file's metadata under a name; the file id stays the same when the name is reused."""
        if not name.strip() or len(name) > 100 or CONTROL.search(name) or "/" in name or "\\" in name:
            raise AdminError(422, "name_invalid")
        if not MIME.match(mime):
            raise AdminError(422, "mime_invalid")
        if not 0 <= size_bytes <= MAX_FILE_BYTES:
            raise AdminError(422, "size_invalid")
        tenant = actor.principal.tenant_id
        async with self._db.tenant_transaction(tenant) as c:
            await self._workspace(c, actor, workspace_id)
            file_id = await c.fetchval(
                "INSERT INTO files AS f (file_id, tenant_id, workspace_id, name, mime, size_bytes) VALUES ($1,$2,$3,$4,$5,$6)"
                " ON CONFLICT (tenant_id, workspace_id, name) DO UPDATE SET mime = EXCLUDED.mime, size_bytes = EXCLUDED.size_bytes"
                " RETURNING file_id", f"file_{uuid.uuid4().hex}", tenant, workspace_id, name, mime, size_bytes)
            await self._a._audit(c, actor, "file.register", "file", file_id, name=name, mime=mime, size_bytes=size_bytes)
        return file_id

    async def list_files(self, actor: Actor, workspace_id: str | None = None) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch("SELECT file_id, workspace_id, name, mime, size_bytes, created_at FROM files WHERE tenant_id = $1"
                                 " AND ($2::text IS NULL OR workspace_id = $2) ORDER BY workspace_id, name",
                                 actor.principal.tenant_id, workspace_id)
        return [dict(r) for r in rows]

    async def set_template(self, actor: Actor, name: str, value: str, workspace_id: str | None = None) -> None:
        """A template variable for one workspace, or tenant-wide (workspace_id None); a workspace value wins over the tenant's."""
        if not NAME.match(name):
            raise AdminError(422, "name_invalid")
        if not value or len(value) > 500 or CONTROL.search(value):
            raise AdminError(422, "value_invalid")
        tenant = actor.principal.tenant_id
        async with self._db.tenant_transaction(tenant) as c:
            if workspace_id is not None:
                await self._workspace(c, actor, workspace_id)
            await c.execute("INSERT INTO template_variables (tenant_id, workspace_id, name, value) VALUES ($1,$2,$3,$4)"
                            " ON CONFLICT (tenant_id, COALESCE(workspace_id, ''), name) DO UPDATE SET value = EXCLUDED.value",
                            tenant, workspace_id, name, value)
            await self._a._audit(c, actor, "template.set", "template", name, workspace_id=workspace_id)

    async def list_templates(self, actor: Actor) -> list[dict]:
        async with self._db.tenant_transaction(actor.principal.tenant_id) as c:
            rows = await c.fetch("SELECT workspace_id, name, value FROM template_variables WHERE tenant_id = $1"
                                 " ORDER BY name, workspace_id NULLS FIRST", actor.principal.tenant_id)
        return [dict(r) for r in rows]
