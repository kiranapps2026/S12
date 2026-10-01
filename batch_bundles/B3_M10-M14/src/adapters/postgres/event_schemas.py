"""Registered event payload schemas (tenant-scoped by row-level security)."""
from __future__ import annotations

import json

from adapters.postgres.database import Database
from contracts.event_schema import RegisteredSchema
from engine.gateway.schema import check_schema


class PostgresEventSchemas:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def latest(self, tenant_id: str, source_system: str, event_type: str) -> RegisteredSchema | None:
        async with self._db.tenant_transaction(tenant_id) as c:
            row = await c.fetchrow(
                "SELECT schema_version, schema FROM event_schemas WHERE tenant_id = $1 AND source_system = $2"
                " AND event_type = $3 AND is_active ORDER BY schema_version DESC LIMIT 1",
                tenant_id, source_system, event_type)
        return None if row is None else RegisteredSchema(str(row["schema_version"]), json.loads(row["schema"]))

    async def register(self, tenant_id: str, source_system: str, event_type: str, schema: dict, *,
                       created_by: str | None = None, connection=None) -> int:
        """Add the next version of a schema (older versions stay, inactive on request). Raises
        SchemaError if the schema uses anything the validator does not enforce. With ``connection``
        (a tenant transaction) the insert joins the caller's transaction."""
        check_schema(schema)
        if connection is None:
            async with self._db.tenant_transaction(tenant_id) as own:
                return await self._register(own, tenant_id, source_system, event_type, schema, created_by)
        return await self._register(connection, tenant_id, source_system, event_type, schema, created_by)

    async def _register(self, c, tenant_id, source_system, event_type, schema, created_by) -> int:
        version = await c.fetchval(
            "SELECT COALESCE(MAX(schema_version), 0) + 1 FROM event_schemas"
            " WHERE tenant_id = $1 AND source_system = $2 AND event_type = $3",
            tenant_id, source_system, event_type)
        await c.execute(
            "INSERT INTO event_schemas (tenant_id, source_system, event_type, schema_version, schema, created_by)"
            " VALUES ($1,$2,$3,$4,$5::jsonb,$6)", tenant_id, source_system, event_type, version,
            json.dumps(schema), created_by)
        return version
