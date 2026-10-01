"""Canonical plan digest — deterministic SHA-256 hash for Plan objects."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any


def canonical_plan_digest(plan: Any) -> str:
    if dataclasses.is_dataclass(plan):
        plan_dict = dataclasses.asdict(plan)
    elif isinstance(plan, dict):
        plan_dict = dict(plan)
    else:
        raise TypeError(f"plan must be a dataclass or dict, got {type(plan).__name__}")
    canonical_json = json.dumps(plan_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
