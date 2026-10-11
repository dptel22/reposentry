"""RepoSentry C0 Contracts — typed, versioned data definitions."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: str = "0.1.0"


def canonical_json(data: Any) -> str:
    """Produce deterministic, canonical JSON representation with sorted keys and no whitespace."""
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_content_hash(data: Any) -> str:
    """Compute sha256 hash of canonical JSON representation."""
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_and_validate_path(path_str: str) -> str:
    """Validate and normalize workspace-relative paths.

    Rejects absolute paths and parent-directory navigation ('..').
    Converts Windows backslashes to standard forward slashes.
    """
    if not path_str or not path_str.strip():
        raise ValueError("Path cannot be empty.")

    # Check for forbidden traversal attempts
    cleaned = path_str.strip().replace("\\", "/")
    parts = cleaned.split("/")
    if any(p == ".." for p in parts):
        raise ValueError(f"Path traversal ('..') is strictly forbidden: '{path_str}'")

    # Reject absolute paths (Windows drive letters or Unix root)
    if PureWindowsPath(path_str).is_absolute() or PurePosixPath(path_str).is_absolute():
        raise ValueError(f"Absolute paths are forbidden; paths must be workspace-relative: '{path_str}'")
    if re.match(r"^[a-zA-Z]:", path_str):
        raise ValueError(f"Drive letter absolute paths are forbidden: '{path_str}'")

    return "/".join(p for p in parts if p and p != ".")


def sanitize_text(text: str, max_length: int = 10000) -> str:
    """Sanitize strings: check bounds and reject control characters except standard whitespace."""
    if len(text) > max_length:
        raise ValueError(f"Text length ({len(text)}) exceeds maximum allowed ({max_length})")
    # Reject control characters (0-31 except tab \t, newline \n, carriage return \r)
    if any(ord(c) < 32 and c not in ("\t", "\n", "\r") for c in text):
        raise ValueError("String contains illegal control characters")
    return text


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
    parameters: list[str] = Field(default_factory=list)
    return_type: str | None = Field(default=None, max_length=256)
    decorators: list[str] = Field(default_factory=list)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)

    @field_validator("name", "return_type", mode="before")
    @classmethod
    def sanitize_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v, max_length=256)
        return v


class FrameworkType(str, Enum):
    FLASK = "flask"
    FASTAPI = "fastapi"
    UNKNOWN = "unknown"


class Route(BaseContract):
    """Extracted web endpoint definition."""

    path: str = Field(min_length=1, max_length=1024, description="URL route pattern")
    http_methods: list[str] = Field(min_length=1, description="Supported HTTP methods (GET, POST, etc.)")
    handler_name: str = Field(min_length=1, max_length=256)
    file_path: str = Field(description="Normalized workspace-relative path")
    line_range: LineRange
    framework: FrameworkType
    guards: list[str] = Field(default_factory=list, description="Associated guard names/decorators")
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
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=2000)
    checked_identifiers: list[str] = Field(default_factory=list)

    @field_validator("file_path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_path(v)


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
            return sanitize_text(v)
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
    evidence: list[Evidence] = Field(min_length=1)
    unproven_assumptions: str = Field(default="", max_length=2000)
    needs_review: bool = Field(default=False)

    @field_validator("title", "description", "unproven_assumptions", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v)
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
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("rationale", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v)
        return v


class Score(BaseContract):
    """Deterministic architectural security-debt score."""

    overall_score: float = Field(ge=0.0, le=100.0, description="0 (severe debt) to 100 (clean)")
    factor_scores: dict[str, float] = Field(description="Scores per category (A, B, C)")
    weights: dict[str, float] = Field(description="Heuristic weights used")
    rationale: str = Field(max_length=2000)
    coverage_penalty: float = Field(ge=0.0, le=100.0, default=0.0)

    @field_validator("rationale", mode="before")
    @classmethod
    def sanitize(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_text(v)
        return v


class Coverage(BaseContract):
    """Analysis coverage and degredation manifest."""

    scanned_files: int = Field(ge=0)
    total_files: int = Field(ge=0)
    skipped_files: dict[str, str] = Field(default_factory=dict, description="path -> skip reason")
    routes_found: int = Field(ge=0)
    guards_found: int = Field(ge=0)
    parse_errors: list[str] = Field(default_factory=list)
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
    timestamp: str = Field(description="ISO-8601 UTC timestamp")
    files: list[IngestedFileRecord] = Field(default_factory=list)
    total_files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class TraceEvent(BaseContract):
    """Telemetry and trace event record."""

    event_id: str = Field(min_length=1, max_length=64)
    timestamp: str = Field(description="ISO-8601 UTC timestamp")
    stage: str = Field(max_length=64)
    span_name: str = Field(max_length=128)
    duration_ms: float = Field(ge=0.0)
    attributes: dict[str, Any] = Field(default_factory=dict)
