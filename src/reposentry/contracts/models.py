"""RepoSentry C0 Contracts — typed, versioned data definitions."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: str = "0.1.0"

# Windows reserved DOS device names (case-insensitive, with or without extension)
WINDOWS_RESERVED_DEVICE_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def _round_floats(obj: Any) -> Any:
    """Recursively quantize floats to 4 decimal places for deterministic cross-platform hashing."""
    if isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            raise ValueError("NaN and Infinity are not permitted in canonical serialization.")
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v) for v in obj]
    return obj


def canonical_json(data: Any) -> str:
    """Produce deterministic, canonical JSON representation with sorted keys, quantized floats, and no whitespace."""
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    quantized = _round_floats(data)
    return json.dumps(quantized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def compute_content_hash(data: Any) -> str:
    """Compute sha256 hash of canonical JSON representation."""
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_and_validate_path(path_str: str) -> str:
    """Validate and normalize workspace-relative paths.

    Rejects:
    - Absolute paths (Unix '/' or Windows drive letters)
    - Drive-relative paths ('/foo', '\\foo')
    - UNC paths ('//server/share', '\\\\server\\share')
    - Alternate Data Streams (paths containing ':')
    - Parent-directory navigation ('..')
    - Windows reserved DOS device names ('CON', 'PRN', 'AUX', 'NUL', 'COM1-9', 'LPT1-9')
    - Trailing spaces and dots that Windows silently strips
    """
    if not path_str or not path_str.strip():
        raise ValueError("Path cannot be empty.")

    raw = path_str.strip()

    # Reject Alternate Data Streams and drive letters
    if ":" in raw:
        raise ValueError(f"Path contains illegal colon (ADS or drive letter): '{path_str}'")

    # Reject leading slashes (Unix absolute, Windows drive-relative, or UNC)
    if raw.startswith(("/", "\\")):
        raise ValueError(f"Path must be relative, not absolute or drive-relative: '{path_str}'")

    cleaned = raw.replace("\\", "/")

    # Reject UNC paths
    if cleaned.startswith("//"):
        raise ValueError(f"UNC network paths are strictly forbidden: '{path_str}'")

    parts = [p for p in cleaned.split("/") if p and p != "."]
    if not parts:
        raise ValueError("Path resolves to empty directory root.")

    for part in parts:
        # Check for traversal
        if part == "..":
            raise ValueError(f"Path traversal ('..') is strictly forbidden: '{path_str}'")

        # Reject trailing dots and spaces (Windows normalization vulnerability)
        if part.endswith(".") or part.endswith(" "):
            raise ValueError(f"Path component has forbidden trailing dot or space: '{part}'")

        # Check Windows reserved DOS device names (e.g. CON, NUL, AUX, NUL.py)
        base_name = part.split(".")[0].upper()
        if base_name in WINDOWS_RESERVED_DEVICE_NAMES:
            raise ValueError(f"Windows reserved DOS device name is forbidden: '{part}'")

    # Double check with pathlib
    if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
        raise ValueError(f"Absolute paths are forbidden: '{path_str}'")

    return "/".join(parts)


def sanitize_text(text: str, max_length: int = 10000) -> str:
    """Sanitize strings: normalize Unicode (NFKC), strip hostile Bidi/format chars, check bounds."""
    if len(text) > max_length:
        raise ValueError(f"Text length ({len(text)}) exceeds maximum allowed ({max_length})")

    # Normalize homoglyphs and compatibility characters
    normalized = unicodedata.normalize("NFKC", text)

    # Filter out illegal control characters and Unicode Format/Surrogate characters (Cf, Cs)
    # This strips Bidi override characters (e.g. \u202E), zero-width spaces (\u200B), and BOM (\uFEFF)
    sanitized_chars: list[str] = []
    for c in normalized:
        code = ord(c)
        cat = unicodedata.category(c)

        # Allow standard printable whitespace: tab (\t), newline (\n), carriage return (\r)
        if code in (9, 10, 13):
            sanitized_chars.append(c)
            continue

        # Reject ASCII control characters (0-31 and 127)
        if code < 32 or code == 127:
            raise ValueError("String contains illegal control characters")

        # Reject Unicode Format characters (Cf: bidi overrides, zero-width chars) and Surrogates (Cs)
        if cat in ("Cf", "Cs"):
            raise ValueError(f"String contains illegal Unicode format/control character (U+{code:04X})")

        sanitized_chars.append(c)

    return "".join(sanitized_chars)


class BaseContract(BaseModel):
    """Base model for all RepoSentry contracts: immutable, strict, versioned."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Version of the contract definition.",
    )

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"Schema version mismatch: expected '{SCHEMA_VERSION}', got '{v}'"
            )
        return v

    def to_canonical_json(self) -> str:
        return canonical_json(self)

    def content_hash(self) -> str:
        return compute_content_hash(self)


class LineRange(BaseContract):
    """Exact source code location range."""

    start_line: int = Field(ge=1, description="1-indexed starting line number")
    end_line: int = Field(ge=1, description="1-indexed ending line number")
    start_col: int = Field(ge=0, default=0, description="0-indexed start column")
    end_col: int = Field(ge=0, default=0, description="0-indexed end column")

    @model_validator(mode="after")
    def validate_range(self) -> LineRange:
        if self.start_line > self.end_line:
            raise ValueError(
                f"start_line ({self.start_line}) cannot be greater than end_line ({self.end_line})"
            )
        if self.start_line == self.end_line and self.start_col > self.end_col:
            raise ValueError(
                f"start_col ({self.start_col}) cannot be greater than end_col ({self.end_col}) on same line"
            )
        return self


class SymbolKind(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    MODULE = "module"


class Symbol(BaseContract):
    """Symbol extracted via AST analysis."""

    name: str = Field(min_length=1, max_length=256)
    kind: SymbolKind
    file_path: str = Field(description="Normalized workspace-relative path")
    line_range: LineRange
    docstring: str | None = Field(default=None, max_length=5000)
    parameters: list[str] = Field(default_factory=list, max_length=256)
    return_type: str | None = Field(default=None, max_length=256)
    decorators: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)

    @field_validator("name", "return_type", "docstring", mode="before")
    @classmethod
    def sanitize_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=5000)
        return v


class FrameworkType(str, Enum):
    FLASK = "flask"
    FASTAPI = "fastapi"
    UNKNOWN = "unknown"


class Route(BaseContract):
    """Extracted web endpoint definition."""

    path: str = Field(min_length=1, max_length=1024, description="URL route pattern")
    http_methods: list[str] = Field(min_length=1, max_length=16, description="Supported HTTP methods (GET, POST, etc.)")
    handler_name: str = Field(min_length=1, max_length=256)
    file_path: str = Field(description="Normalized workspace-relative path")
    line_range: LineRange
    framework: FrameworkType
    guards: list[str] = Field(default_factory=list, max_length=128, description="Associated guard names/decorators")
    router_prefix: str = Field(default="", max_length=512)
    is_async: bool = Field(default=False)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)

    @field_validator("http_methods")
    @classmethod
    def uppercase_methods(cls, v: list[str]) -> list[str]:
        valid = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE"}
        upper = [m.upper().strip() for m in v]
        for m in upper:
            if m not in valid:
                raise ValueError(f"Invalid HTTP method: '{m}'")
        return sorted(list(set(upper)))


class GuardMechanismType(str, Enum):
    AUTH_CHECK = "auth_check"
    ROLE_CHECK = "role_check"
    TOKEN_VALIDATION = "token_validation"
    SESSION_VALIDATION = "session_validation"
    DECOY_NOOP = "decoy_noop"
    UNRESOLVED = "unresolved"


class GuardSignature(BaseContract):
    """Resolved security guard/decorator signature."""

    name: str = Field(min_length=1, max_length=256)
    mechanism_type: GuardMechanismType
    file_path: str = Field(description="Normalized workspace-relative path where guard is defined")
    line_range: LineRange
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    rationale: str = Field(max_length=2000)
    checked_identifiers: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)

    @field_validator("name", "rationale", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=2000)
        return v


class Evidence(BaseContract):
    """AST-derived concrete evidence supporting a finding."""

    evidence_id: str = Field(min_length=1, max_length=64)
    file_path: str = Field(description="Normalized workspace-relative path")
    line_range: LineRange
    snippet: str = Field(max_length=10000, description="Exact code slice")
    description: str = Field(max_length=2000)
    ast_node_type: str = Field(max_length=128)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)

    @field_validator("snippet", "description", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=10000)
        return v


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingCategory(str, Enum):
    A = "A"  # Repeated/inconsistent security logic
    B = "B"  # Unsafe abstraction/boilerplate
    C = "C"  # Cross-module inconsistency


class Finding(BaseContract):
    """Architectural security debt finding."""

    finding_id: str = Field(min_length=1, max_length=64)
    rule_id: str = Field(min_length=1, max_length=64)
    category: FindingCategory
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(max_length=5000)
    severity: SeverityLevel
    confidence: ConfidenceLevel
    evidence: list[Evidence] = Field(min_length=1, max_length=100)
    unproven_assumptions: str = Field(default="", max_length=2000)
    needs_review: bool = Field(default=False)

    @field_validator("title", "description", "unproven_assumptions", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=5000)
        return v


class VerdictStatus(str, Enum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    ABSTAIN = "abstain"


class Verdict(BaseContract):
    """Judge/Agent evaluation verdict for a finding."""

    verdict_id: str = Field(min_length=1, max_length=64)
    finding_id: str = Field(min_length=1, max_length=64)
    status: VerdictStatus
    rationale: str = Field(max_length=5000)
    cited_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @field_validator("rationale", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=5000)
        return v


class Score(BaseContract):
    """Deterministic architectural security-debt score."""

    overall_score: float = Field(ge=0.0, le=100.0, allow_inf_nan=False, description="0 (severe debt) to 100 (clean)")
    factor_scores: dict[str, float] = Field(max_length=32, description="Scores per category (A, B, C)")
    weights: dict[str, float] = Field(max_length=32, description="Heuristic weights used")
    rationale: str = Field(max_length=2000)
    coverage_penalty: float = Field(ge=0.0, le=100.0, default=0.0, allow_inf_nan=False)

    @field_validator("rationale", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=2000)
        return v


class Coverage(BaseContract):
    """Analysis coverage and degradation manifest."""

    scanned_files: int = Field(ge=0)
    total_files: int = Field(ge=0)
    skipped_files: dict[str, str] = Field(default_factory=dict, max_length=5000, description="path -> skip reason")
    routes_found: int = Field(ge=0)
    guards_found: int = Field(ge=0)
    parse_errors: list[str] = Field(default_factory=list, max_length=1000)
    model_fallback_active: bool = Field(default=False)

    @property
    def coverage_ratio(self) -> float:
        if self.total_files == 0:
            return 1.0
        return self.scanned_files / self.total_files


class IngestedFileRecord(BaseContract):
    """Record of an ingested file in the workspace."""

    file_path: str = Field(description="Normalized workspace-relative path")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    skipped: bool = Field(default=False)
    skip_reason: str | None = Field(default=None, max_length=256)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)


class RunManifest(BaseContract):
    """Immutable manifest of an ingested workspace run."""

    run_id: str = Field(min_length=1, max_length=64)
    target_name: str = Field(min_length=1, max_length=256)
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$", description="ISO-8601 UTC timestamp")
    files: list[IngestedFileRecord] = Field(default_factory=list, max_length=100_000)
    total_files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class TraceEvent(BaseContract):
    """Telemetry and trace event record."""

    event_id: str = Field(min_length=1, max_length=64)
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$", description="ISO-8601 UTC timestamp")
    stage: str = Field(max_length=64)
    span_name: str = Field(max_length=128)
    duration_ms: float = Field(ge=0.0, allow_inf_nan=False)
    attributes: dict[str, Any] = Field(default_factory=dict)
