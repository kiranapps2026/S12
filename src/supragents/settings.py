"""Runtime settings, read from the environment only (no secrets in the repository)."""
from __future__ import annotations

import os
from dataclasses import dataclass


class SettingsError(Exception):
    """A required setting is missing."""


@dataclass(frozen=True)
class Settings:
    database_url: str

    @classmethod
    def from_environment(cls) -> Settings:
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            raise SettingsError("DATABASE_URL is not set (see .env.example)")
        return cls(database_url=url)
