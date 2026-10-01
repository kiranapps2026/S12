"""
Canonical plan digest — deterministic SHA-256 hash for Plan objects.

This is the single source of truth for plan hashing. S9 computes the digest
here, S11 verifies it here, and every test calls this function — no test
reimplements the serialization.

Supported types in Plan serialization:
  - None, bool, int, float, str — passed through as-is
  - tuple — converted to list
  - list — elements recursively serialized
  - dict — keys converted to str, values recursively serialized
  - dataclass — converted via asdict(), then recursively serialized
  - StrEnum — converted to its .value
  - datetime — converted to ISO-8601 UTC string (with Z suffix)
  - Decimal — converted to str (to avoid precision loss from float)

Unsupported types (raises TypeError):
  - bytes, bytearray, set, frozenset, complex, etc.

Excluded fields from digest:
  - PLAN_HASH_EXCLUDED_FIELDS = ("plan_hash",) — plan_hash IS the digest,
    so including it would create a circular self-reference.

Source: DATA_CONTRACTS.md §4, PIPELINE_STAGES.md §11, §13
Owner: Plan / Hash
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import hashlib
import json
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Type conversion policy
# ---------------------------------------------------------------------------

def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-safe form for canonical serialization.

    Raises TypeError on unsupported types — never silently loses precision.
    """
    # Primitives — pass through unchanged
    if value is None or isinstance(value, (bool, int)):
        return value
    # float: pass through (JSON float is IEEE 754 double; plan fields use float)
    if isinstance(value, float):
        return value
    # str: pass through
    if isinstance(value, str):
        return value
    # Enum: convert to its value
    if isinstance(value, Enum):
        return value.value
    # datetime: convert to ISO-8601 UTC string (with Z suffix)
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            # Naive datetime — assume UTC, add Z suffix
            return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        # Timezone-aware — convert to UTC, format with Z
        utc_dt = value.astimezone(datetime.timezone.utc)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    # Decimal: convert to str to preserve exact precision
    if isinstance(value, decimal.Decimal):
        return str(value)
    # dict: keys to str, values recursively serialized
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    # tuple: convert to list, elements recursively serialized
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    # list: elements recursively serialized
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    # dataclass: convert via asdict, then recursively serialize
    if dataclasses.is_dataclass(value):
        return _serialize_value(dataclasses.asdict(value))

    # Unsupported type — raise, don't silently convert
    raise TypeError(
        f"Cannot serialize {type(value).__name__} for canonical plan digest. "
        f"Value: {value!r}. Add explicit handling in _serialize_value()."
    )


# ---------------------------------------------------------------------------
# Excluded fields constant
# ---------------------------------------------------------------------------

#: Fields excluded from the plan digest. Now empty — Plan has no plan_hash
#: (plan_hash lives in PlanCreationResult beside Plan, not inside it).
PLAN_HASH_EXCLUDED_FIELDS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Canonical digest function
# ---------------------------------------------------------------------------

def canonical_plan_digest(plan: Any, *, include_plan_hash: bool = False) -> str:
    """
    Compute the canonical SHA-256 digest of a Plan.

    The digest is computed from a deterministic JSON representation:
    - dataclasses converted via asdict()
    - dict keys sorted alphabetically
    - explicit type conversion for datetime, Enum, Decimal, tuple
    - unsupported types raise TypeError

    By default, plan_hash is EXCLUDED from the digest (it IS the digest).
    Set include_plan_hash=True only for testing purposes.

    This function is used by:
    - S9 (plan_creation): computes plan_hash at plan creation time
    - S11 (plan_validation): verifies plan_hash has not been tampered with
    - All tests: never reimplement serialization — call this function

    Args:
        plan: Plan dataclass instance (or dict, for testing)
        include_plan_hash: If True, include plan_hash in the digest.
                           Default False (plan_hash is excluded — it is the digest).

    Returns:
        SHA-256 hex digest string (64 characters)

    Raises:
        TypeError: if plan contains an unserializable type
    """
    # Convert to dict via asdict — handles nested dataclasses automatically
    if dataclasses.is_dataclass(plan):
        plan_dict = dataclasses.asdict(plan)
    elif isinstance(plan, dict):
        plan_dict = dict(plan)  # shallow copy for testing
    else:
        raise TypeError(f"plan must be a dataclass or dict, got {type(plan).__name__}")

    # Remove excluded fields (plan_hash is the digest itself)
    # Unless include_plan_hash=True (for testing circular reference behavior)
    if not include_plan_hash:
        for field_name in PLAN_HASH_EXCLUDED_FIELDS:
            plan_dict.pop(field_name, None)

    # Pre-process: recursively convert all values to JSON-safe types
    # This ensures json.dumps never encounters an unsupported type
    processed = _serialize_value(plan_dict)

    # Serialize to JSON deterministically (sorted keys, no extra whitespace)
    canonical_json = json.dumps(
        processed,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
