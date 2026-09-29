"""
Event ledger — immutable event log for all pipeline stages.

Source: FINAL_ARCHITECTURE.md §40, DATA_CONTRACTS.md §34
"""

from __future__ import annotations

import logging
import time
import uuid
from contracts.events import LedgerEvent

logger = logging.getLogger(__name__)


class EventLedger:
    """
    Immutable event ledger for the execution kernel.

    Every stage (S0-S15) emits events to this ledger.
    Events are immutable after creation.
    trace_id chains all events for a given execution.
    """

    def __init__(self) -> None:
        self._buffer: list[LedgerEvent] = []

    def _generate_event_id(self) -> str:
        """Generate a new event ID (UUID v4)."""
        return str(uuid.uuid4())

    def _now(self) -> float:
        """Get server-authoritative timestamp."""
        return time.time()

    async def emit(
        self,
        event_type: str,
        execution_id: str,
        trace_id: str,
        stage: str,
        actor_type: str,
        actor_id: str,
        payload: dict | None = None,
    ) -> LedgerEvent:
        """
        Emit an event to the ledger.

        Args:
            event_type: LEDGER_* event type
            execution_id: Parent execution ID
            trace_id: Trace chain ID
            stage: Pipeline stage (S0-S15)
            actor_type: user, worker, system
            actor_id: user_id, worker_id, or "system"
            payload: Event payload

        Returns:
            The created LedgerEvent
        """
        event = LedgerEvent(
            event_id=self._generate_event_id(),
            event_type=event_type,
            execution_id=execution_id,
            trace_id=trace_id,
            stage=stage,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload or {},
            timestamp=self._now(),
        )

        # Buffer for batch insert (or insert immediately)
        self._buffer.append(event)

        logger.debug("Ledger event: %s [%s] %s", event_type, stage, event.event_id)

        # TODO: Persist to database
        # await self._persist(event)

        return event

    async def flush(self) -> None:
        """Flush buffered events to the database."""
        if not self._buffer:
            return

        # TODO: Batch insert events
        events = list(self._buffer)
        self._buffer.clear()

        logger.debug("Flushed %d ledger events", len(events))

    async def get_events(self, trace_id: str) -> list[LedgerEvent]:
        """
        Get all events for a trace.

        Source: FINAL_ARCHITECTURE.md §40
        """
        # TODO: Query from database
        return [e for e in self._buffer if e.trace_id == trace_id]

    async def get_execution_events(self, execution_id: str) -> list[LedgerEvent]:
        """Get all events for an execution."""
        return [e for e in self._buffer if e.execution_id == execution_id]
