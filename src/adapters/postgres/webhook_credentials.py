"""Webhook signing secrets: encrypted at rest (envelope encryption), never hashed.

AES-256-GCM under a per-record data key (DEK); the DEK is stored only wrapped by one
system-wide key-encryption key (KEK) that comes from the environment / secret manager and
never enters the database. Decryption happens only when a request is being verified; the
plaintext is a bytearray the gateway overwrites afterwards (best effort). Secrets are never
logged or returned. The endpoint lookup happens BEFORE the tenant is known (like api_keys), so
`webhook_credentials` has no row-level security; it holds only ciphertext and the fixed
identity an endpoint acts as.
"""
from __future__ import annotations

import base64
import binascii
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from adapters.postgres.database import Database
from contracts.errors import DependencyUnavailable
from contracts.principal import Principal
from contracts.webhook_credentials import SigningSecret, WebhookEndpoint

DEFAULT_GRACE = "24 hours"


@dataclass(frozen=True)
class Kek:
    """The key-encryption key: 32 random bytes and a version number."""
    key: bytes
    version: int = 1

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise ValueError("the key-encryption key must be exactly 32 bytes")

    @classmethod
    def from_base64(cls, value: str, version: int = 1) -> Kek:
        try:
            return cls(base64.b64decode(value, validate=True), version)
        except (binascii.Error, ValueError):
            raise ValueError("WEBHOOK_KEK must be 32 bytes, base64-encoded") from None

    def __repr__(self) -> str:   # never print the key
        return f"Kek(version={self.version})"


def _seal(kek: Kek, secret: bytes, credential_id: str) -> tuple[bytes, bytes, bytes]:
    dek, nonce, dek_nonce = AESGCM.generate_key(256), os.urandom(12), os.urandom(12)
    aad = credential_id.encode()
    ciphertext = AESGCM(dek).encrypt(nonce, secret, aad)
    wrapped = dek_nonce + AESGCM(kek.key).encrypt(dek_nonce, dek, aad)
    return ciphertext, nonce, wrapped


def _open(kek: Kek, credential_id: str, ciphertext: bytes, nonce: bytes, wrapped: bytes) -> bytearray:
    aad = credential_id.encode()
    try:
        dek = AESGCM(kek.key).decrypt(wrapped[:12], wrapped[12:], aad)
        return bytearray(AESGCM(dek).decrypt(nonce, ciphertext, aad))
    except InvalidTag:
        raise DependencyUnavailable("webhook secret cannot be decrypted") from None


class PostgresWebhookCredentials:
    def __init__(self, database: Database, kek: Kek) -> None:
        self._db, self._kek = database, kek

    async def endpoint(self, endpoint_id: str, source_system: str) -> WebhookEndpoint | None:
        async with self._db.transaction() as connection:
            rows = await connection.fetch(
                "SELECT credential_id, status, tenant_id, workspace_id, user_id, membership_id,"
                "       connection_id, resource_scope, secret_ciphertext, secret_nonce, wrapped_dek"
                "  FROM webhook_credentials"
                " WHERE endpoint_id = $1 AND source_system = $2"
                "   AND (expires_at IS NULL OR expires_at > now())"
                "   AND (status = 'active' OR (status = 'retiring' AND retiring_until > now()))"
                " ORDER BY (status = 'active') DESC", endpoint_id, source_system)
        if not rows:
            return None
        first = rows[0]
        principal = Principal(first["tenant_id"], first["workspace_id"], first["user_id"],
                              first["membership_id"], first["connection_id"], first["resource_scope"])
        secrets_ = tuple(
            SigningSecret(r["credential_id"], r["status"],
                          _open(self._kek, r["credential_id"], r["secret_ciphertext"],
                                r["secret_nonce"], r["wrapped_dek"]))
            for r in rows)
        return WebhookEndpoint(principal, secrets_)

    async def mark_verified(self, credential_id: str) -> None:
        async with self._db.transaction() as connection:
            await connection.execute(
                "UPDATE webhook_credentials SET last_verified_at = now() WHERE credential_id = $1",
                credential_id)

    async def issue(self, principal: Principal, source_system: str, *, label: str | None = None,
                    created_by: str | None = None, connection=None) -> tuple[str, str]:
        """Create an endpoint for ``principal``. Returns (endpoint_id, secret); the secret cannot
        be shown again. With ``connection`` the insert joins the caller's transaction."""
        endpoint_id = uuid.uuid4().hex
        return endpoint_id, await self._insert(endpoint_id, principal, source_system, connection,
                                               label=label, created_by=created_by)

    async def rotate(self, endpoint_id: str, source_system: str, grace: str = DEFAULT_GRACE, *,
                     created_by: str | None = None, connection=None) -> str:
        """The current secret keeps working for ``grace``; the new secret is returned once."""
        if connection is None:
            async with self._db.transaction() as own:
                return await self._rotate(own, endpoint_id, source_system, grace, created_by)
        return await self._rotate(connection, endpoint_id, source_system, grace, created_by)

    async def _rotate(self, connection, endpoint_id, source_system, grace, created_by) -> str:
        current = await connection.fetchrow(
            "SELECT tenant_id, workspace_id, user_id, membership_id, connection_id, resource_scope, label"
            "  FROM webhook_credentials WHERE endpoint_id = $1 AND source_system = $2"
            "   AND status = 'active' FOR UPDATE", endpoint_id, source_system)
        if current is None:
            raise KeyError("unknown endpoint")
        row = dict(current)
        label = row.pop("label")
        await connection.execute(
            "UPDATE webhook_credentials SET status = 'retired', retiring_until = NULL"
            " WHERE endpoint_id = $1 AND source_system = $2 AND status = 'retiring'",
            endpoint_id, source_system)
        await connection.execute(
            "UPDATE webhook_credentials SET status = 'retiring',"
            "       retiring_until = now() + $3::interval"
            " WHERE endpoint_id = $1 AND source_system = $2 AND status = 'active'",
            endpoint_id, source_system, _interval(grace))
        return await self._insert(endpoint_id, Principal(**row), source_system, connection,
                                  label=label, created_by=created_by)

    async def _insert(self, endpoint_id: str, principal: Principal, source_system: str,
                      connection=None, *, label: str | None = None, created_by: str | None = None) -> str:
        secret = "whsec_" + secrets.token_urlsafe(32)
        credential_id = str(uuid.uuid4())
        ciphertext, nonce, wrapped = _seal(self._kek, secret.encode(), credential_id)
        sql = ("INSERT INTO webhook_credentials (credential_id, endpoint_id, tenant_id, workspace_id,"
               " user_id, membership_id, connection_id, resource_scope, source_system,"
               " secret_ciphertext, secret_nonce, wrapped_dek, kek_version, label, created_by)"
               " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)")
        args = (credential_id, endpoint_id, principal.tenant_id, principal.workspace_id, principal.user_id,
                principal.membership_id, principal.connection_id, principal.resource_scope, source_system,
                ciphertext, nonce, wrapped, self._kek.version, label, created_by)
        if connection is not None:
            await connection.execute(sql, *args)
        else:
            async with self._db.transaction() as own:
                await own.execute(sql, *args)
        return secret


def _interval(grace: str) -> timedelta:
    amount, _, unit = grace.partition(" ")
    if not amount.isdigit() or unit not in ("minutes", "hours", "days"):
        raise ValueError("grace must look like '24 hours'")
    return timedelta(**{unit: int(amount)})
