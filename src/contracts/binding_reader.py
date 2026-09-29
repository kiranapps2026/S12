"""S12 entry reads the frozen binding's row ONCE, by binding_id, to compare its version (gate C32)."""
from __future__ import annotations

from typing import Protocol


class BindingVersionReader(Protocol):
    async def binding_version(self, binding_id: str) -> str | None:
        """The current version of the ACTIVE binding row, or None if the row is missing or no
        longer active. Raise DependencyUnavailable if the registry cannot be read."""
