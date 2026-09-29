"""Authenticator double: a fixed table of credential → Principal."""
from __future__ import annotations

from supragents.ports.authentication import Principal

PRINCIPAL_A = Principal("tenant-a", "workspace-1", "user-1", "member-1", "conn-1", "workspace-1/*")
PRINCIPAL_B = Principal("tenant-b", "workspace-9", "user-9", "member-9", "conn-9", "workspace-9/*")


class TableAuthenticator:
    def __init__(self) -> None:
        self.keys = {"key-a": PRINCIPAL_A, "key-b": PRINCIPAL_B}

    async def authenticate(self, credential: str) -> Principal | None:
        return self.keys.get(credential)
