"""Deterministic, non-LLM evidence verification (component C8).

Given a workspace root and a :class:`~reposentry.verifier.types.VerdictBundle`
of claims citing evidence items, this module checks each citation:

- the cited path is confined to the workspace (rejects absolute paths, ``..``
  escapes, and symlinks resolving outside the workspace via ``os.path.realpath``);
- the cited file exists;
- the cited 1-based inclusive line range is valid
  (``1 <= start_line <= end_line <= file line count``) and not enormous
  (more than :data:`MAX_RANGE_LINES` lines is rejected);
- the quoted snippet matches the source at the cited range after the
  normalization documented in :mod:`reposentry.verifier.normalize`.

Per claim: every claim must cite at least one evidence item, and every cited
evidence id must exist in the bundle. Duplicate evidence ids in the bundle are
reported.

The verifier NEVER raises on bad evidence — it reports failures as
downgrades with machine-readable reason codes. All orderings are
deterministic: claims are checked in bundle order, evidence ids in bundle
order, and reason counts are keyed by reason-code name.
"""

from __future__ import annotations

import os
import re
from collections import Counter

from .normalize import normalize_snippet, normalize_source_lines
from .types import (
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

MAX_RANGE_LINES = 5000
"""Cited ranges spanning more than this many lines are rejected as enormous."""
MAX_SOURCE_BYTES = 5 * 1024 * 1024
"""Files larger than this are downgraded without being read into memory."""

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _read_source_lines(abs_path: str, workspace_real: str) -> list[str]:
    """Read a file as UTF-8 text, split on newlines without raising.

    Decoding errors are replaced so a malformed file yields a deterministic
    quote mismatch instead of an exception. The verifier never executes or
    writes scanned files.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(abs_path, flags)
    try:
        before = os.fstat(fd)
        if before.st_size > MAX_SOURCE_BYTES:
            raise _OversizedSourceError
        # Confirm the pathname still names the opened regular file. O_NOFOLLOW
        # closes the final-component symlink race on platforms that support it.
        current = os.stat(abs_path, follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise OSError("source file changed while opening")
        opened_path = os.path.realpath(abs_path)
        if not _realpath_confined(workspace_real, opened_path):
            raise OSError("source file escaped workspace while opening")
        with os.fdopen(fd, "rb", closefd=False) as fh:
            raw = fh.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise _OversizedSourceError
    finally:
        os.close(fd)
    text = raw.decode("utf-8", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # A trailing newline produces a final empty element; drop it so line
    # counts match what editors report.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


class _OversizedSourceError(Exception):
    pass


def _confined_relative_path(path: str) -> Reason | None:
    """Return the confinement failure reason, or None if the path is a
    well-formed relative path with no ``..`` components."""
    if not path or path.strip() == "":
        return Reason.PATH_NOT_RELATIVE
    # POSIX-absolute paths (leading "/") are rejected explicitly: on Windows
    # ``os.path.isabs("/etc/passwd")`` is False (it is drive-relative), yet
    # joining them onto the workspace still escapes it.
    if path.startswith(("/", "\\")) or os.path.isabs(path) or _WINDOWS_DRIVE.match(path):
        return Reason.PATH_NOT_RELATIVE
    parts = path.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        return Reason.PATH_ESCAPES_WORKSPACE
    def is_dos_device(part: str) -> bool:
        base = part.split(":", 1)[0].rstrip(" .").split(".", 1)[0].rstrip(" ")
        return bool(re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", base))

    if any(is_dos_device(part) for part in parts):
        return Reason.PATH_NOT_RELATIVE
    return None


def _realpath_confined(workspace_real: str, abs_path: str) -> bool:
    """True when abs_path (already realpath-resolved) stays inside the
    realpath of the workspace."""
    try:
        return os.path.commonpath([abs_path, workspace_real]) == workspace_real
    except ValueError:
        # Different drives on Windows, etc.
        return False


def check_citation(
    workspace_root: str,
    claim: Claim,
    evidence: EvidenceItem,
) -> CitationCheck:
    """Run the full per-citation check chain. Never raises."""
    workspace_real = os.path.realpath(workspace_root)

    def fail(reason: Reason, detail: str = "") -> CitationCheck:
        return CitationCheck(
            claim_id=claim.id, evidence_id=evidence.id, ok=False, reason=reason, detail=detail
        )

    bad_path = _confined_relative_path(evidence.path)
    if bad_path is not None:
        return fail(bad_path, evidence.path)

    abs_path = os.path.join(workspace_real, evidence.path.replace("\\", "/"))
    resolved = os.path.realpath(abs_path)
    if not _realpath_confined(workspace_real, resolved):
        # A symlink (or '..'-carrying link) resolving outside the workspace.
        return fail(Reason.PATH_SYMLINK_ESCAPE, resolved)
    if not os.path.isfile(resolved):
        return fail(Reason.FILE_NOT_FOUND, evidence.path)

    try:
        source_lines = _read_source_lines(resolved, workspace_real)
    except _OversizedSourceError:
        return fail(Reason.FILE_OVERSIZED, f"file exceeds {MAX_SOURCE_BYTES} bytes")
    except OSError as exc:
        return fail(Reason.FILE_NOT_FOUND, str(exc))

    file_len = len(source_lines)
    if not (1 <= evidence.start_line <= evidence.end_line <= file_len):
        return fail(
            Reason.RANGE_INVALID,
            f"start={evidence.start_line} end={evidence.end_line} file_lines={file_len}",
        )
    if evidence.end_line - evidence.start_line + 1 > MAX_RANGE_LINES:
        return fail(
            Reason.RANGE_TOO_LARGE,
            f"span={evidence.end_line - evidence.start_line + 1} max={MAX_RANGE_LINES}",
        )

    cited_block = source_lines[evidence.start_line - 1 : evidence.end_line]
    expected = normalize_source_lines(cited_block)
    actual = normalize_snippet(evidence.snippet)
    if not actual:
        return fail(Reason.EMPTY_SNIPPET)
    if expected != actual:
        return fail(
            Reason.QUOTE_MISMATCH,
            # Partial-overlap policy: the normalized snippet must equal the
            # normalized cited block exactly; a snippet present elsewhere in
            # the file, or overlapping the range only partially, is a mismatch.
            f"snippet does not match lines {evidence.start_line}-{evidence.end_line} of {evidence.path}",
        )
    return CitationCheck(claim_id=claim.id, evidence_id=evidence.id, ok=True, reason=Reason.OK)


def verify_bundle(workspace_root: str, bundle: VerdictBundle) -> VerificationReport:
    """Verify every claim in the bundle. Deterministic and non-raising."""
    # Evidence id index: first occurrence wins for lookup; duplicates reported.
    evidence_by_id: dict[str, EvidenceItem] = {}
    seen_counts: Counter[str] = Counter()
    for item in bundle.evidence:
        seen_counts[item.id] += 1
        evidence_by_id.setdefault(item.id, item)
    duplicates = tuple(
        item_id for item_id, count in sorted(seen_counts.items()) if count > 1
    )

    results: list[ClaimResult] = []
    all_checks: list[CitationCheck] = []

    for claim in bundle.claims:
        if not claim.citations:
            check = CitationCheck(
                claim_id=claim.id,
                evidence_id="",
                ok=False,
                reason=Reason.NO_CITATIONS,
            )
            all_checks.append(check)
            results.append(
                ClaimResult(
                    claim_id=claim.id,
                    status=EvidenceStatus.DOWNGRADED,
                    reason=Reason.NO_CITATIONS,
                    checks=(check,),
                )
            )
            continue

        checks: list[CitationCheck] = []
        missing_ids: list[str] = []
        for citation in claim.citations:
            item = evidence_by_id.get(citation.evidence_id)
            if item is None:
                check = CitationCheck(
                    claim_id=claim.id,
                    evidence_id=citation.evidence_id,
                    ok=False,
                    reason=Reason.EVIDENCE_ID_MISSING,
                )
                missing_ids.append(citation.evidence_id)
            else:
                check = check_citation(workspace_root, claim, item)
            checks.append(check)
            all_checks.append(check)

        if missing_ids or any(not c.ok for c in checks):
            # First failing check in deterministic citation order decides the
            # claim's reason code.
            first_fail = next(c for c in checks if not c.ok)
            results.append(
                ClaimResult(
                    claim_id=claim.id,
                    status=EvidenceStatus.DOWNGRADED,
                    reason=first_fail.reason,
                    checks=tuple(checks),
                )
            )
        else:
            results.append(
                ClaimResult(
                    claim_id=claim.id,
                    status=EvidenceStatus.OK,
                    reason=Reason.OK,
                    checks=tuple(checks),
                )
            )

    by_reason: Counter[str] = Counter()
    passed = 0
    failed = 0
    for check in all_checks:
        if check.ok:
            passed += 1
        else:
            failed += 1
        by_reason[check.reason.value] += 1
    quality = EvidenceQuality(
        passed=passed,
        failed=failed,
        by_reason=dict(sorted(by_reason.items())),
    )
    return VerificationReport(
        claims=tuple(results),
        duplicate_evidence_ids=duplicates,
        quality=quality,
    )
