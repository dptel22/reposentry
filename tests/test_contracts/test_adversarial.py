"""Adversarial tests for C0 contracts: path traversal, control chars, limits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reposentry.contracts.models import (
    Evidence,
    Finding,
    FindingCategory,
    LineRange,
    Route,
    SeverityLevel,
    ConfidenceLevel,
    FrameworkType,
    normalize_and_validate_path,
)


def test_path_traversal_dot_dot_rejected() -> None:
    with pytest.raises(ValueError, match="Path traversal"):
        normalize_and_validate_path("../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal"):
        normalize_and_validate_path("app/../../secrets.env")


def test_absolute_paths_rejected() -> None:
    # Unix absolute
    with pytest.raises(ValueError, match="Absolute paths are forbidden"):
        normalize_and_validate_path("/etc/passwd")

    # Windows drive letter absolute
    with pytest.raises(ValueError, match="forbidden"):
        normalize_and_validate_path("C:/Windows/System32")


def test_control_characters_rejected() -> None:
    # String with null byte or ASCII 1
    malicious = "bad\x00input"
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev-1",
            file_path="src/file.py",
            line_range=LineRange(start_line=1, end_line=5),
            snippet=malicious,
            description="test",
            ast_node_type="Expr",
        )


def test_oversized_string_rejected() -> None:
    huge_text = "A" * 15000  # max length is 10000
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev-1",
            file_path="src/file.py",
            line_range=LineRange(start_line=1, end_line=5),
            snippet=huge_text,
            description="test",
            ast_node_type="Expr",
        )


def test_inverted_line_range_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be greater than end_line"):
        LineRange(start_line=50, end_line=10)


def test_inverted_column_range_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be greater than end_col"):
        LineRange(start_line=10, end_line=10, start_col=20, end_col=5)


def test_markup_in_fields_safely_handled() -> None:
    # XSS payload in description should be stored safely without crashing
    xss_desc = "<script>alert('xss')</script> & <b>bold</b>"
    evidence = Evidence(
        evidence_id="ev-xss",
        file_path="src/app.py",
        line_range=LineRange(start_line=1, end_line=5),
        snippet="x = 1",
        description=xss_desc,
        ast_node_type="Assign",
    )
    assert evidence.description == xss_desc
