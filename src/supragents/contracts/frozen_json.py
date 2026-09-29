"""Deep-immutable JSON values, so frozen contracts cannot be mutated through a dict."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, TypeAlias

FrozenJson: TypeAlias = (
    "None | bool | int | float | str | tuple[FrozenJson, ...] | Mapping[str, FrozenJson]"
)

_SCALARS = (type(None), bool, int, float, str)


def freeze(value: Any) -> FrozenJson:
    """Return an immutable copy of a JSON-like value. Raises TypeError for anything else."""
    if isinstance(value, _SCALARS):
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def thaw(value: FrozenJson) -> Any:
    """Plain dict/list form of a frozen value, for hashing and serialization."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value
