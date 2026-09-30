"""Where S1 gets the values behind `$ref`, `$file` and `{{template}}` references.

Every method is scoped to the caller: tenant (row-level security), workspace and, for results,
the user and conversation. S1 never reads any other tenant's or user's data, and only calls a
method when the text actually contains the matching reference.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FileInfo:
    """Metadata of a stored file. S1 refers to files by this; it never reads their content."""
    file_id: str
    name: str
    mime: str
    size_bytes: int


class ReferenceSource(Protocol):
    async def previous_result(self, *, tenant_id: str, user_id: str, conversation_id: str,
                              index: int) -> str | None:
        """The `index`-th most recent result (1 = latest) of this user's conversation, as text,
        or None if there is no such result."""

    async def file(self, *, tenant_id: str, workspace_id: str, name: str) -> FileInfo | None:
        """The file called `name` in the workspace, or None."""

    async def variable(self, *, tenant_id: str, workspace_id: str, name: str) -> str | None:
        """A tenant/workspace template variable (workspace overrides tenant), or None."""

    async def now(self) -> float:
        """Authoritative Unix time (the database clock) for relative dates and {{today}}."""
