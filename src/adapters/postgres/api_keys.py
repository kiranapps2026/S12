"""API-key authentication: keys are random, shown once, and stored only as SHA-256 hashes."""
from __future__ import annotations

import hashlib
import secrets
import uuid

from adapters.postgres.database import Database
from contracts.principal import Principal

KEY_PREFIX = "sk_supra_"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class PostgresApiKeyAuthenticator:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def authenticate(self, credential: str) -> Principal | None:
        if not credential.startswith(KEY_PREFIX):
            return None
        async with self._db.transaction() as connection:
            row = await connection.fetchrow(
                "SELECT tenant_id, workspace_id, user_id, membership_id, connection_id, resource_scope"
                "  FROM api_keys WHERE key_hash = $1 AND is_active", hash_key(credential))
        return None if row is None else Principal(**dict(row))

    async def issue(self, principal: Principal) -> str:
        """Create a key for ``principal`` and return it. It cannot be shown again."""
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        async with self._db.transaction() as connection:
            await connection.execute(
                "INSERT INTO api_keys (key_id, key_hash, tenant_id, workspace_id, user_id, membership_id,"
                " connection_id, resource_scope) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                str(uuid.uuid4()), hash_key(key), principal.tenant_id, principal.workspace_id,
                principal.user_id, principal.membership_id, principal.connection_id,
                principal.resource_scope)
        return key
