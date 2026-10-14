"""JSON-Schema subset validator and JSON extraction for structured model output."""

from __future__ import annotations

import json
import re
from typing import Any

from reposentry.gateway.errors import OutputTooLargeError, SchemaValidationError

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def extract_json_object(text: str, *, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) > max_bytes:
        raise OutputTooLargeError(f"output exceeds {max_bytes} bytes")
    stripped = _FENCE.sub("", text).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise SchemaValidationError("no JSON object found")
    candidate = stripped[start : end + 1]
    if len(candidate.encode("utf-8")) > max_bytes:
        raise OutputTooLargeError(f"JSON object exceeds {max_bytes} bytes")
    return candidate


def parse_and_validate(text: str, schema: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    blob = extract_json_object(text, max_bytes=max_bytes)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaValidationError("top-level value must be an object")
    _validate(data, schema, path="$")
    return data


def _validate(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{path}: expected object")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra = set(value) - set(props)
            if extra:
                raise SchemaValidationError(f"{path}: extra fields {sorted(extra)}")
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaValidationError(f"{path}: missing required field {key}")
        for key, child in value.items():
            if key in props:
                _validate(child, props[key], f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise SchemaValidationError(f"{path}: expected array")
        item_schema = schema.get("items", {})
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise SchemaValidationError(f"{path}: too many items")
        for i, item in enumerate(value):
            _validate(item, item_schema, f"{path}[{i}]")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"{path}: expected string")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise SchemaValidationError(f"{path}: string too long")
        if "enum" in schema and value not in schema["enum"]:
            raise SchemaValidationError(f"{path}: value not in enum")
        return
    if expected == "integer":
        if type(value) is not int:
            raise SchemaValidationError(f"{path}: expected integer")
        return
    if expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SchemaValidationError(f"{path}: expected number")
        return
    if expected == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"{path}: expected boolean")
        return
    if expected == "null":
        if value is not None:
            raise SchemaValidationError(f"{path}: expected null")
        return
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: value not in enum")
