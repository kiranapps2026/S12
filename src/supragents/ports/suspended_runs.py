"""Durable storage of runs suspended at S10 (PIPELINE_STAGES §12 "on worker restart")."""
from __future__ import annotations

from typing import Protocol

from supragents.contracts.state import PipelineState


class SuspendedRunStore(Protocol):
    async def save(self, state: PipelineState, *, tenant_id: str, execution_id: str,
                   confirmation_id: str) -> None:
        """Store the state the run had before S10. Raise DependencyUnavailable on failure."""

    async def load(self, *, tenant_id: str, confirmation_id: str) -> PipelineState | None:
        """The stored state, or None if this tenant has no run waiting on that confirmation."""
