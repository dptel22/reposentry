"""Local dataclasses and reason codes for the C8 evidence verifier.

Contracts v0 is not yet published (see docs/OPERATING_CONTRACT.md section A:
C0 owns ``src/reposentry/contracts/``), so the verifier package defines its
own local dataclasses, mirroring the style of
``src/reposentry/gateway/types.py`` and ``src/reposentry/observability/types.py``.
When contracts v0 lands, these should be replaced via a Contract Change Request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class EvidenceStatus(str, Enum):
    """Per-claim outcome. The verifier never raises on bad evidence; it reports."""

    OK = "ok"
    DOWNGRADED = "downgraded"


class Reason(str, Enum):
    """Machine-readable reason codes. Deterministic check order; first failure wins."""

    OK = "ok"
    PATH_NOT_RELATIVE = "path_not_relative"
    PATH_ESCAPES_WORKSPACE = "path_escapes_workspace"
    PATH_SYMLINK_ESCAPE = "path_symlink_escape"
    FILE_NOT_FOUND = "file_not_found"
    RANGE_INVALID = "range_invalid"
    RANGE_TOO_LARGE = "range_too_large"
    QUOTE_MISMATCH = "quote_mismatch"
    EMPTY_SNIPPET = "empty_snippet"
    NO_CITATIONS = "no_citations"
    EVIDENCE_ID_MISSING = "evidence_id_missing"


@dataclass(frozen=True)
class EvidenceItem:
    """One cited piece of evidence: a repo-relative path, a 1-based inclusive
    line range, and the quoted snippet.

    ``line_count_hint`` (optional) lets callers pre-size; the verifier never
    trusts it for validation — it always re-reads the real file line count.
    """

    id: str
    path: str
    start_line: int
    end_line: int
    snippet: str


@dataclass(frozen=True)
class Citation:
    """A claim's reference to an evidence item by id."""

    evidence_id: str


@dataclass(frozen=True)
class Claim:
    """A verdict claim that must be backed by at least one citation."""

    id: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class VerdictBundle:
    """The verdict/evidence structure handed to the verifier."""

    claims: tuple[Claim, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()


@dataclass(frozen=True)
class CitationCheck:
    """Outcome of verifying one citation of one claim."""

    claim_id: str
    evidence_id: str
    ok: bool
    reason: Reason
    detail: str = ""


@dataclass(frozen=True)
class ClaimResult:
    """Outcome of verifying one claim."""

    claim_id: str
    status: EvidenceStatus
    reason: Reason
    checks: tuple[CitationCheck, ...] = ()


@dataclass(frozen=True)
class EvidenceQuality:
    """Aggregate evidence quality: check counts by reason, deterministically
    ordered by reason enum value."""

    passed: int = 0
    failed: int = 0
    by_reason: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationReport:
    """Full verifier report. Never raised; always returned."""

    claims: tuple[ClaimResult, ...] = ()
    duplicate_evidence_ids: tuple[str, ...] = ()
    quality: EvidenceQuality = EvidenceQuality()
