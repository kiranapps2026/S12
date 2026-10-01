"""Live authorization port (M11, C23, C24).

The ``LiveAuthorization`` port is called at the start of every attempt to
determine whether the caller is still authorized.  A non-None return means
the authorization has been revoked and the step must stop immediately.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Revoked:
    """Non-None return from ``LiveAuthorization.check`` means revoked."""
    reason: str


@dataclass(frozen=True)
class LiveCheck:
    """Result of a live authorization check."""
    revoked: Revoked | None = None


class LiveAuthorization:
    """Port: call ``check`` before every adapter call.

    Returns ``None`` when the caller is authorized, or a ``Revoked`` instance
    when the authorization has been withdrawn.
    """

    async def check(
        self,
        *,
        tenant_id: str,
        workspace_id: str | None,
        user_id: str | None,
        connection_id: str | None,
        binding: object,
    ) -> Revoked | None:
        raise NotImplementedError
