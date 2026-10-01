"""Per-event-type payload schemas (EVENT_GATEWAY §4: validate_schema). A payload is accepted only if its
(source system, event type) is REGISTERED for the tenant and the payload satisfies the latest active schema."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RegisteredSchema:
    version: str
    schema: dict


class EventSchemaStore(Protocol):
    async def latest(self, tenant_id: str, source_system: str, event_type: str) -> RegisteredSchema | None:
        """The newest active schema, or None if the event type is not registered for the tenant.
        Raise DependencyUnavailable if the registry cannot be read."""
