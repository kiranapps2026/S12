"""JSON encoding of frozen contracts, driven by their type annotations.

Used to store a run suspended at S10. Decoding never executes code (unlike pickle): every
value is rebuilt only as the declared dataclass, enum or JSON type, and a value that does
not fit its annotation raises.
"""
from __future__ import annotations

import types
import typing
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any


def encode(value: Any) -> Any:
    """Plain JSON-compatible form of a contract value."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (frozenset, set)):
        return sorted(encode(v) for v in value)
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    return value


def decode(annotation: Any, data: Any) -> Any:
    """Rebuild a value of ``annotation`` from its encoded form. Raises on a mismatch."""
    origin = typing.get_origin(annotation)
    if annotation is Any:
        return data
    if origin in (typing.Union, types.UnionType):
        options = [o for o in typing.get_args(annotation) if o is not type(None)]
        if data is None:
            return None
        if len(options) != 1:
            raise TypeError(f"cannot decode ambiguous union {annotation}")
        return decode(options[0], data)
    if is_dataclass(annotation):
        hints = typing.get_type_hints(annotation)
        return annotation(**{f.name: decode(hints[f.name], data[f.name]) for f in fields(annotation)})
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(data)
    if origin is tuple:
        args = typing.get_args(annotation)
        item = args[0] if args else Any
        return tuple(decode(item, v) for v in _seq(data))
    if annotation is tuple:
        return tuple(_seq(data))
    if origin is list or annotation is list:
        args = typing.get_args(annotation)
        return [decode(args[0] if args else Any, v) for v in _seq(data)]
    if origin is frozenset or annotation is frozenset:
        return frozenset(_seq(data))
    if origin is dict or annotation is dict:
        if not isinstance(data, dict):
            raise TypeError(f"expected object, got {type(data).__name__}")
        args = typing.get_args(annotation)
        value_type = args[1] if len(args) == 2 else Any
        return {k: decode(value_type, v) for k, v in data.items()}
    return _scalar(annotation, data)


def _seq(data: Any) -> list:
    if not isinstance(data, list):
        raise TypeError(f"expected array, got {type(data).__name__}")
    return data


def _scalar(annotation: Any, data: Any) -> Any:
    if annotation is float and isinstance(data, int) and not isinstance(data, bool):
        return float(data)
    if annotation is int and isinstance(data, bool):
        raise TypeError("expected int, got bool")
    if annotation in (str, int, float, bool) and not isinstance(data, annotation):
        raise TypeError(f"expected {annotation.__name__}, got {type(data).__name__}")
    return data


def encode_state(state: Any) -> dict[str, Any]:
    return encode(state)


def decode_state(data: dict[str, Any]) -> Any:
    """Rebuild a PipelineState. Field types come from the ownership registry, so a stored
    value can only become the contract its stage owns."""
    from contracts.execution_context import ExecutionContext
    from contracts.pipeline_state import PipelineState, _resolve_field_type
    from contracts.stage_registry import StageStatus
    from contracts.entry import EntryRequest

    known = {f.name for f in fields(PipelineState)}
    extra = set(data) - known
    if extra:
        raise TypeError(f"unknown PipelineState fields: {sorted(extra)}")
    from contracts.frozen_binding import FrozenBindingIdentity
    from contracts.stage_outputs import CapabilityMatch
    types_by_field: dict[str, Any] = {
        "capability_matches": tuple[CapabilityMatch, ...],
        "frozen_bindings": tuple[FrozenBindingIdentity, ...],
        "execution_context": ExecutionContext, "entry_request": EntryRequest,
        "stage_status": StageStatus, "deny_reason": str,
    }
    values: dict[str, Any] = {}
    for name in known:
        raw = data.get(name)
        if raw is None:
            values[name] = None
            continue
        cls = types_by_field.get(name) or _resolve_field_type(name)
        if cls is None:
            raise TypeError(f"no contract type for PipelineState.{name}")
        values[name] = decode(cls, raw)
    return PipelineState(**values)
