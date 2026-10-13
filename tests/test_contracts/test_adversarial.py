"""Adversarial tests for C0 contracts: path traversal, device names, control chars, Unicode bidi, limits."""

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
    Symbol,
    SymbolKind,
    Score,
    normalize_and_validate_path,
    sanitize_text,
)


def test_path_traversal_dot_dot_rejected() -> None:
    with pytest.raises(ValueError, match="Path traversal"):
        normalize_and_validate_path("../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal"):
        normalize_and_validate_path("app/../../secrets.env")


def test_absolute_paths_rejected() -> None:
    # Unix absolute
    with pytest.raises(ValueError, match="Path must be relative"):
        normalize_and_validate_path("/etc/passwd")

    # Windows drive letter absolute
    with pytest.raises(ValueError, match="illegal colon"):
        normalize_and_validate_path("C:/Windows/System32")


def test_windows_dos_device_names_rejected() -> None:
    # Issue #1
    for dev in ("CON", "con", "PRN", "aux", "NUL", "COM1", "lpt9", "nul.py", "con.txt"):
        with pytest.raises(ValueError, match="reserved DOS device"):
            normalize_and_validate_path(dev)
        with pytest.raises(ValueError, match="reserved DOS device"):
            normalize_and_validate_path(f"sub/{dev}")


def test_alternate_data_streams_rejected() -> None:
    # Issue #1
    with pytest.raises(ValueError, match="illegal colon"):
        normalize_and_validate_path("app/main.py:hidden_stream")

    with pytest.raises(ValueError, match="illegal colon"):
        normalize_and_validate_path("file.py::$DATA")


def test_unc_paths_rejected() -> None:
    # Issue #1
    with pytest.raises(ValueError, match="Path must be relative"):
        normalize_and_validate_path("//attacker.com/share")

    with pytest.raises(ValueError, match="Path must be relative"):
        normalize_and_validate_path(r"\\attacker.com\share")


def test_trailing_dots_and_spaces_rejected() -> None:
    # Issue #1
    with pytest.raises(ValueError, match="trailing dot or space"):
        normalize_and_validate_path("file.py. ")

    with pytest.raises(ValueError, match="trailing dot or space"):
        normalize_and_validate_path("dir./subfile.py")


def test_unicode_bidi_override_rejected() -> None:
    # Issue #4: Right-to-Left Override (\u202E)
    malicious_bidi = "get_\u202Eadmin_profile"
    with pytest.raises(ValueError, match="Unicode format/control character"):
        sanitize_text(malicious_bidi)


def test_unicode_zero_width_and_bom_rejected() -> None:
    # Issue #4: Zero-width space (\u200B) and BOM (\uFEFF)
    zero_width = "func\u200Bname"
    with pytest.raises(ValueError, match="Unicode format/control character"):
        sanitize_text(zero_width)

    bom_str = "\uFEFFstart"
    with pytest.raises(ValueError, match="Unicode format/control character"):
        sanitize_text(bom_str)


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


def test_unbounded_collection_rejected() -> None:
    # Issue #3: parameter list exceeding max_length=256
    too_many_params = [f"p{i}" for i in range(300)]
    with pytest.raises(ValidationError):
        Symbol(
            name="func",
            kind=SymbolKind.FUNCTION,
            file_path="src/app.py",
            line_range=LineRange(start_line=1, end_line=5),
            parameters=too_many_params,
        )


def test_nan_and_inf_floats_rejected() -> None:
    # Issue #3: NaN and Inf floats rejected
    with pytest.raises(ValidationError):
        Score(
            overall_score=float("nan"),
            factor_scores={"A": 10.0},
            weights={"A": 1.0},
            rationale="test",
        )

    with pytest.raises(ValidationError):
        Score(
            overall_score=float("inf"),
            factor_scores={"A": 10.0},
            weights={"A": 1.0},
            rationale="test",
        )


def test_inverted_line_range_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be greater than end_line"):
        LineRange(start_line=50, end_line=10)


def test_inverted_column_range_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be greater than end_col"):
        LineRange(start_line=10, end_line=10, start_col=20, end_col=5)
