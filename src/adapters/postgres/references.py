"""S1 reference sources from PostgreSQL: results, files and template variables, tenant-scoped (RLS)."""
from __future__ import annotations

from adapters.postgres.database import Database
from contracts.reference_source import FileInfo


class PostgresReferenceSource:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def previous_result(self, *, tenant_id: str, user_id: str, conversation_id: str,
                              index: int) -> str | None:
        if index < 1:
            return None
        async with self._db.tenant_transaction(tenant_id) as connection:
            return await connection.fetchval(
                "SELECT summary FROM conversation_results"
                " WHERE tenant_id = $1 AND user_id = $2 AND conversation_id = $3"
                " ORDER BY result_id DESC OFFSET $4 LIMIT 1",
                tenant_id, user_id, conversation_id, index - 1)

    async def file(self, *, tenant_id: str, workspace_id: str, name: str) -> FileInfo | None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT file_id, name, mime, size_bytes FROM files"
                " WHERE tenant_id = $1 AND workspace_id = $2 AND name = $3",
                tenant_id, workspace_id, name)
        return None if row is None else FileInfo(**dict(row))

    async def variable(self, *, tenant_id: str, workspace_id: str, name: str) -> str | None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            return await connection.fetchval(
                "SELECT value FROM template_variables"
                " WHERE tenant_id = $1 AND name = $2 AND (workspace_id = $3 OR workspace_id IS NULL)"
                " ORDER BY workspace_id NULLS LAST LIMIT 1",
                tenant_id, name, workspace_id)

    async def now(self) -> float:
        async with self._db.transaction() as connection:
            return await connection.fetchval("SELECT EXTRACT(EPOCH FROM clock_timestamp())::float8")
