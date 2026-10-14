"""C8 — deterministic, non-LLM evidence verifier for RepoSentry.

Verifies that verdict claims are backed by evidence whose cited paths are
workspace-confined, ranges are valid, and quoted snippets match the source
after the normalization documented in
:mod:`reposentry.verifier.normalize`. It reports failures as downgrades with
machine-readable reason codes; it never raises on bad evidence.
"""

from .normalize import normalize_newlines, normalize_snippet, normalize_source_lines
from .types import (
    Citation,
    CitationCheck,
    Claim,
    ClaimResult,
    EvidenceItem,
    EvidenceQuality,
    EvidenceStatus,
    Reason,
    VerdictBundle,
    VerificationReport,
)
from .verifier import MAX_RANGE_LINES, check_citation, verify_bundle

__all__ = [
    "MAX_RANGE_LINES",
    "Citation",
    "CitationCheck",
    "Claim",
    "ClaimResult",
    "EvidenceItem",
    "EvidenceQuality",
    "EvidenceStatus",
    "Reason",
    "VerdictBundle",
    "VerificationReport",
    "check_citation",
    "normalize_newlines",
    "normalize_snippet",
    "normalize_source_lines",
    "verify_bundle",
]
