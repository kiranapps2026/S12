"""Runtime settings from the environment, optionally loaded from a ``.env`` file.

Only secrets and connection strings live in ``.env``; every other setting is built in.
Variables already set in the environment win over ``.env``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class SettingsError(Exception):
    """A required setting is missing."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    deepseek_api_key: str

    @classmethod
    def load(cls, env_file: Path = Path(".env")) -> Settings:
        load_env_file(env_file)
        return cls(
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
        )

    def require(self, *names: str) -> Settings:
        missing = [name.upper() for name in names if not getattr(self, name)]
        if missing:
            raise SettingsError(f"{', '.join(missing)} not set (put it in .env; see .env.example)")
        return self


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines; ignore blanks and comments; never override the environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
