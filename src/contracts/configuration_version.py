"""
Configuration versioning — prevents mid-execution config drift.

Source: DATA_CONTRACTS.md §36, IDENTITY_AND_TENANCY.md §22
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ConfigVersion:
    """
    Immutable configuration snapshot.

    Guarantees that mid-execution config drift is impossible.
    Configuration is captured at S0 (and re-validated at S11).
    """
    config_id: str                        # UUID v4
    version: str                           # Semantic version
    config_hash: str                       # SHA-256 of config content
    tenant_id: str | None = None           # None for global config
    config_data: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: 0.0)
    created_by: str = "system"
    description: str = ""

    @staticmethod
    def compute_hash(config_data: dict[str, Any]) -> str:
        """Compute a deterministic hash of configuration data."""
        import json
        from datetime import datetime as _dt
        def _default(obj: Any) -> Any:
            if isinstance(obj, _dt):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
        canonical = json.dumps(config_data, sort_keys=True, default=_default)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]
