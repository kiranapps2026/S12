"""The user's answer to a pending confirmation, supplied when a run is resumed."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfirmationReply:
    confirmation_id: str
    user_id: str
    approved: bool
