"""Durable event log (``event_log``): raw payload stored once per (tenant, idempotency key)."""
from __future__ import annotations

from adapters.postgres.database import Database
from contracts.event_envelope import EventEnvelope
from contracts.principal import Principal
from contracts.webhook_credentials import StoredEvent


class PostgresEventLog:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def record(self, *, envelope: EventEnvelope, principal: Principal, idempotency_key: str,
                     raw_body: bytes) -> StoredEvent:
        async with self._db.tenant_transaction(envelope.tenant_id) as connection:
            inserted = await connection.fetchval(
                "INSERT INTO event_log (event_id, tenant_id, workspace_id, event_type, source, source_system,"
                " payload, payload_ref, payload_checksum, correlation_id, idempotency_key, auth_method,"
                " auth_principal) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'hmac_sha256',$12)"
                " ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING event_id",
                envelope.event_id, envelope.tenant_id, envelope.workspace_id, envelope.type,
                envelope.source, envelope.source_system, raw_body, envelope.payload_ref,
                envelope.payload_checksum, envelope.correlation_id, idempotency_key, principal.connection_id)
        return StoredEvent(duplicate=inserted is None)

    async def finish(self, tenant_id: str, event_id: str, status: str) -> None:
        """status: 'processed' (the pipeline ran to an outcome) or 'failed'."""
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "UPDATE event_log SET processing_status = $2 WHERE event_id = $1", event_id, status)
