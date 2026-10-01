"""The response envelope (DATA_CONTRACTS Envelope, EnvelopeError; gate §12)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EnvelopeError:
    type: str
    message: str
    details: dict | None = None
    recoverable: bool = True
    suggested_action: str | None = None


@dataclass(frozen=True)
class Envelope:
    status: str                       # ok | partial | error | clarify | confirm
    data: Any = None
    message: str | None = None
    error: EnvelopeError | None = None
    metadata: dict | None = None
