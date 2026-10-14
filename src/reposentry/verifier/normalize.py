"""Documented quote normalization for the C8 evidence verifier.

Normalization (the ONLY normalization applied, applied identically to both the
quoted snippet and the source lines):

1. Line-ending normalization: CRLF (``\\r\\n``) and bare CR (``\\r``) are
   normalized to LF (``\\n``). This makes quotes written on Windows match
   sources stored with any common line ending.
2. Per-line rstrip: trailing horizontal whitespace is stripped from each line
   (spaces and tabs, any ``str.rstrip()`` whitespace). This makes a quote that
   lost trailing whitespace survive; leading indentation is preserved.
3. Empty-line trimming: leading and trailing empty lines (after rstrip) are
   dropped from BOTH the snippet and the cited source range.

Comparison after these steps is EXACT — no case folding, no Unicode
normalization (NFC/NFKC), no collapsing of internal whitespace.

Partial-overlap policy: the cited range must contain the snippet exactly as a
contiguous block of lines after normalization. A snippet that overlaps only
part of the cited range, or extends beyond it, is a MISMATCH
(``Reason.QUOTE_MISMATCH``), not a pass.
"""

from __future__ import annotations


def normalize_newlines(text: str) -> str:
    """Normalize CRLF and bare CR to LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_and_rstrip(text: str) -> list[str]:
    return [line.rstrip() for line in normalize_newlines(text).split("\n")]


def _trim_empty(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return lines[start:end]


def normalize_snippet(snippet: str) -> list[str]:
    """Normalized lines of a quoted snippet (documented normalization above)."""
    return _trim_empty(_split_and_rstrip(snippet))


def normalize_source_lines(lines: list[str]) -> list[str]:
    """Normalized lines of a source range (documented normalization above)."""
    return _trim_empty([line.rstrip() for line in lines])
