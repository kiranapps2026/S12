"""A deliberately small JSON-Schema subset for event payloads (no external dependency, no regular
expressions, so a schema can never cause catastrophic backtracking, bounded depth and size).

Supported keywords: type, required, properties, additionalProperties (boolean), enum, minLength,
maxLength, minimum, maximum, items, minItems, maxItems. Anything else in a schema is refused
(`check_schema`) rather than silently ignored: an unenforced constraint is a hole. `bool` is not a number.
"""
from __future__ import annotations

_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
_KEYWORDS = frozenset({"type", "required", "properties", "additionalProperties", "enum", "minLength",
                       "maxLength", "minimum", "maximum", "items", "minItems", "maxItems", "description"})
MAX_DEPTH = 8
MAX_ENUM = 100
MAX_PROPERTIES = 200


class SchemaError(ValueError):
    """The schema itself uses something this validator does not enforce."""


def check_schema(schema, depth: int = 0) -> None:
    if depth > MAX_DEPTH or not isinstance(schema, dict):
        raise SchemaError("schema must be an object of bounded depth")
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise SchemaError(f"unsupported keywords: {sorted(unknown)}")
    kind = schema.get("type")
    kinds = [kind] if isinstance(kind, str) else kind
    if kind is not None and (not isinstance(kinds, list) or not kinds or not set(kinds) <= _TYPES):
        raise SchemaError("type must be one of " + ", ".join(sorted(_TYPES)))
    props = schema.get("properties", {})
    if not isinstance(props, dict) or len(props) > MAX_PROPERTIES:
        raise SchemaError("properties must be an object")
    for sub in props.values():
        check_schema(sub, depth + 1)
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        raise SchemaError("required must be a list of names")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        raise SchemaError("additionalProperties must be a boolean")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not 0 < len(schema["enum"]) <= MAX_ENUM):
        raise SchemaError("enum must be a non-empty list")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], int) or schema[key] < 0):
            raise SchemaError(f"{key} must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            raise SchemaError(f"{key} must be a number")
    if "items" in schema:
        check_schema(schema["items"], depth + 1)


def _is(kind: str, value) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool)          # number


def validate(schema: dict, value, path: str = "$", depth: int = 0) -> str | None:
    """None if `value` satisfies `schema`, else a short description of the first violation."""
    if depth > MAX_DEPTH + 2:
        return f"{path}: too deeply nested"
    kind = schema.get("type")
    if kind is not None:
        kinds = [kind] if isinstance(kind, str) else kind
        if not any(_is(k, value) for k in kinds):
            return f"{path}: expected {'/'.join(kinds)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: not one of the allowed values"
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return f"{path}: shorter than {schema['minLength']}"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{path}: longer than {schema['maxLength']}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path}: below {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path}: above {schema['maximum']}"
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path}: fewer than {schema['minItems']} items"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: more than {schema['maxItems']} items"
        if "items" in schema:
            for i, item in enumerate(value):
                problem = validate(schema["items"], item, f"{path}[{i}]", depth + 1)
                if problem:
                    return problem
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                return f"{path}.{name}: required"
        props = schema.get("properties", {})
        if schema.get("additionalProperties", True) is False:
            extra = sorted(set(value) - set(props))
            if extra:
                return f"{path}.{extra[0]}: not allowed"
        for name, sub in props.items():
            if name in value:
                problem = validate(sub, value[name], f"{path}.{name}", depth + 1)
                if problem:
                    return problem
    return None
