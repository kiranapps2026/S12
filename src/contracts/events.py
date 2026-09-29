"""
Event correlation and correlation IDs.

Source: FINAL_ARCHITECTURE.md §41
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventIdentity:
    """
    Identity for a single event in the event log.

    Source: DATA_CONTRACTS.md §34
    """
    event_id: str                        # UUID v4
    trace_id: str                         # UUID v4 — chains all events
    correlation_id: str | None            # Groups related events
    causation_id: str | None              # Event that caused this one
    parent_event_id: str | None           # Hierarchical parent
    span_id: str | None                   # OpenTelemetry span


@dataclass(frozen=True)
class OutboxEvent:
    """
    Event in the outbox pattern for reliable event delivery.

    Source: DATA_CONTRACTS.md §35
    """
    outbox_id: str                        # UUID v4
    event_type: str                       # LEDGER_*, CONFIRMATION_*, etc.
    aggregate_id: str                     # execution_id, step_id, etc.
    aggregate_type: str                   # execution, step, worker, etc.
    payload: dict                         # Event payload (JSON-serializable)
    headers: dict[str, str] = field(default_factory=dict)
    destination: str | None = None        # Event destination (queue, webhook)
    status: str = "PENDING"               # PENDING, DELIVERED, FAILED
    retry_count: int = 0
    created_at: float = field(default_factory=lambda: 0.0)
    delivered_at: float | None = None
