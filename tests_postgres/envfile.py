"""Load KEY=VALUE pairs from the repo-root `.env` into os.environ for the live/database tests.

Real environment variables always win; `.env` only fills what is missing. `.env` is git-ignored.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise RuntimeError(f"{path.name} is UTF-16 (PowerShell '>' does that): re-save it as UTF-8")
    for line in raw.decode("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
