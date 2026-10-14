"""Redaction for logs and outbound model payloads. Never log source or secrets."""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^\s/'\"<>:]+:[^\s/'\"<>@]+@[^\s'\"<>]+"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bxox(?:b|p|a|r|s)-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-+=/]+"),
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)x-api-key\s*[:=]\s*\S+"),
)

SOURCE_KEYS = frozenset(
    {
        "source",
        "source_text",
        "quote",
        "snippet",
        "content",
        "code",
        "body",
        "text",
        "prompt",
        "messages",
        "input_bundle",
        "raw",
        "document",
    }
)

REDACTED = "[REDACTED]"


def scrub_text(value: str) -> str:
    out = value
    for pat in SECRET_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def strip_source_and_secrets(obj: Any, *, include_source: bool = False) -> Any:
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for key, val in obj.items():
            if not include_source and str(key).lower() in SOURCE_KEYS:
                cleaned[key] = "[SOURCE_OMITTED]"
            else:
                cleaned[key] = strip_source_and_secrets(val, include_source=include_source)
        return cleaned
    if isinstance(obj, list):
        return [strip_source_and_secrets(v, include_source=include_source) for v in obj]
    return obj
