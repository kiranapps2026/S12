"""Canonical SHA-256 digest of a Plan (S9 computes it, S10 binds to it, S11 verifies it)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from typing import Any

from supragents.contracts.frozen_json import thaw
from supragents.contracts.outputs import Plan


def plan_digest(plan: Plan) -> str:
    """Stable across processes: sorted keys, no whitespace, every field included."""
    canonical = json.dumps(_plain(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return thaw(value)
