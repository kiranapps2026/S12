"""JSON encoding of frozen contracts, driven by their type annotations.

Used to store a suspended PipelineState. It never executes code while decoding (unlike
pickle): every value is rebuilt only as the declared dataclass, enum or JSON type.
"""
from __future__ import annotations

import types
import typing
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from supragents.contracts.frozen_json import freeze, thaw


def encode(value: Any) -> Any:
    """Plain JSON-compatible form of a contract value."""
    if is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    return thaw(value)


def decode(annotation: Any, data: Any) -> Any:
    """Rebuild a value of ``annotation`` from its encoded form. Raises on a mismatch."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return _decode_optional(annotation, data)
    if is_dataclass(annotation):
        hints = typing.get_type_hints(annotation)
        return annotation(**{f.name: decode(hints[f.name], data[f.name]) for f in fields(annotation)})
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(data)
    if origin is tuple:
        item_type = typing.get_args(annotation)[0]
        return tuple(decode(item_type, item) for item in data)
    if origin is frozenset:
        return frozenset(data)
    if origin is Mapping:
        return freeze(data)
    return _decode_scalar(annotation, data)


def _decode_optional(annotation: Any, data: Any) -> Any:
    options = [option for option in typing.get_args(annotation) if option is not type(None)]
    if data is None:
        return None
    if len(options) != 1:
        raise TypeError(f"cannot decode ambiguous union {annotation}")
    return decode(options[0], data)


def _decode_scalar(annotation: Any, data: Any) -> Any:
    if annotation is float and isinstance(data, int) and not isinstance(data, bool):
        return float(data)
    if annotation in (str, int, float, bool) and not isinstance(data, annotation):
        raise TypeError(f"expected {annotation.__name__}, got {type(data).__name__}")
    return data
