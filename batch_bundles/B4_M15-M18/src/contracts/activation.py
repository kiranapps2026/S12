"""S0.1 activation check input: tenant/workspace pause and scheduled-activation times."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ActivationState:
    """Times are Unix seconds; ``database_now`` is the authoritative (database) clock."""
    database_now: float
    tenant_paused_until: float | None
    tenant_activation_at: float | None
    workspace_paused_until: float | None
    workspace_activation_at: float | None


class ActivationStateReader(Protocol):
    async def read(self, tenant_id: str, workspace_id: str) -> ActivationState:
        """Raise DependencyUnavailable if the rows cannot be read."""
