"""Unit tests for the C8 deterministic evidence verifier (component C8)."""

from __future__ import annotations

import pytest

from reposentry.verifier import (
    Citation,
    Claim,
    EvidenceItem,
    EvidenceStatus,
    Reason,
    VerdictBundle,
    normalize_newlines,
    normalize_snippet,
    verify_bundle,
)


def _write(tmp_path, rel: str, content: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.encode("utf-8"))


def _bundle(tmp_path, rel: str, content: str, snippet: str, start: int, end: int):
    _write(tmp_path, rel, content)
    ev = EvidenceItem(id="ev1", path=rel, start_line=start, end_line=end, snippet=snippet)
    claim = Claim(id="c1", citations=(Citation(evidence_id="ev1"),))
    return VerdictBundle(claims=(claim,), evidence=(ev,))


def _reason_for(bundle, tmp_path) -> Reason:
    report = verify_bundle(str(tmp_path), bundle)
    assert len(report.claims) == 1
    return report.claims[0].reason


# ---------------------------------------------------------------- match


def test_exact_match(tmp_path):
    content = "alpha\nbeta\ngamma\n"
    bundle = _bundle(tmp_path, "src/a.py", content, "beta", 2, 2)
    report = verify_bundle(str(tmp_path), bundle)
    assert report.claims[0].status is EvidenceStatus.OK
    assert report.claims[0].reason is Reason.OK
    assert report.quality.passed == 1
    assert report.quality.failed == 0


def test_match_with_leading_indentation_preserved(tmp_path):
    content = "def f():\n    return 1\n"
    bundle = _bundle(tmp_path, "a.py", content, "    return 1", 2, 2)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_multi_line_match(tmp_path):
    content = "one\ntwo\nthree\nfour\n"
    bundle = _bundle(tmp_path, "a.py", content, "two\nthree", 2, 3)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_deterministic_ordering_of_claims(tmp_path):
    _write(tmp_path, "a.py", "x\ny\n")
    ev = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="x")
    bad = Claim(id="c_bad", citations=(Citation("missing"),))
    good = Claim(id="c_good", citations=(Citation("ev1"),))
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(bad, good), evidence=(ev,)))
    assert [c.claim_id for c in report.claims] == ["c_bad", "c_good"]
    assert report.claims[0].reason is Reason.EVIDENCE_ID_MISSING
    assert report.claims[1].status is EvidenceStatus.OK


# ---------------------------------------------------------------- mismatch


def test_wrong_content_mismatch(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "alpha\nbeta\n", "gamma", 1, 1)
    assert _reason_for(bundle, tmp_path) is Reason.QUOTE_MISMATCH


def test_snippet_elsewhere_in_same_file_is_mismatch(tmp_path):
    # The snippet exists in the file, but not at the cited range.
    content = "alpha\nbeta\ngamma\n"
    bundle = _bundle(tmp_path, "a.py", content, "gamma", 1, 1)
    assert _reason_for(bundle, tmp_path) is Reason.QUOTE_MISMATCH


def test_partial_overlap_is_a_mismatch(tmp_path):
    # Documented policy: a snippet overlapping only part of the cited range
    # does not match — the normalized cited block must equal the snippet.
    content = "one\ntwo\nthree\n"
    bundle = _bundle(tmp_path, "a.py", content, "one\ntwo\nthree", 1, 2)  # range too short
    assert _reason_for(bundle, tmp_path) is Reason.QUOTE_MISMATCH
    other = _bundle(tmp_path, "b.py", "one\ntwo\nthree\n", "one\ntwo", 1, 3)  # snippet too short
    assert _reason_for(other, tmp_path) is Reason.QUOTE_MISMATCH


def test_same_snippet_in_different_file_is_mismatch(tmp_path):
    _write(tmp_path, "a.py", "secret\n")
    _write(tmp_path, "b.py", "other\n")
    ev = EvidenceItem(id="ev1", path="b.py", start_line=1, end_line=1, snippet="secret")
    claim = Claim(id="c1", citations=(Citation("ev1"),))
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(claim,), evidence=(ev,)))
    assert report.claims[0].reason is Reason.QUOTE_MISMATCH


# ---------------------------------------------------------------- normalization


def test_newline_normalization_helper():
    assert normalize_newlines("a\r\nb\rc\nd") == "a\nb\nc\nd"


def test_crlf_source_matches_lf_snippet(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "alpha\r\nbeta\r\n", "alpha\nbeta", 1, 2)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_cr_only_source_matches(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "alpha\rbeta\r", "alpha\nbeta", 1, 2)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_trailing_whitespace_rstripped_on_both_sides(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "alpha   \nbeta\t\n", "alpha \nbeta", 1, 2)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_leading_whitespace_is_not_stripped(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "    indented\n", "indented", 1, 1)
    assert _reason_for(bundle, tmp_path) is Reason.QUOTE_MISMATCH


def test_leading_and_trailing_empty_lines_trimmed_both_sides(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "\n\nalpha\n\n\n", "\nalpha\n\n", 1, 5)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_tabs_are_preserved_internally(tmp_path):
    # Tabs are not expanded; internal tabs must match exactly.
    bundle = _bundle(tmp_path, "a.py", "a\tb\n", "a\tb", 1, 1)
    assert _reason_for(bundle, tmp_path) is Reason.OK
    bundle2 = _bundle(tmp_path, "b.py", "a\tb\n", "a    b", 1, 1)
    assert _reason_for(bundle2, tmp_path) is Reason.QUOTE_MISMATCH


def test_unicode_content_matches(tmp_path):
    content = "héllo wörld ✓ 日本語 🎉\nnext\n"
    bundle = _bundle(tmp_path, "a.py", content, "héllo wörld ✓ 日本語 🎉", 1, 1)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_unicode_mismatch_is_detected(tmp_path):
    # Visually confusable characters must NOT match (no Unicode folding).
    # NFC 'é' vs decomposed 'e' + combining accent: no Unicode folding, so no match.
    bundle = _bundle(tmp_path, "a.py", "caf\u00e9\n", "cafe\u0301", 1, 1)
    assert _reason_for(bundle, tmp_path) is Reason.QUOTE_MISMATCH


# ---------------------------------------------------------------- ranges


def test_off_by_one_range_start_zero(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\n", "one", 0, 1)
    assert _reason_for(bundle, tmp_path) is Reason.RANGE_INVALID


def test_off_by_one_range_end_past_eof(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\n", "one", 1, 2)
    assert _reason_for(bundle, tmp_path) is Reason.RANGE_INVALID


def test_end_before_start(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\ntwo\n", "one", 2, 1)
    assert _reason_for(bundle, tmp_path) is Reason.RANGE_INVALID


def test_last_line_range_ok(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\ntwo\n", "two", 2, 2)
    assert _reason_for(bundle, tmp_path) is Reason.OK


def test_file_without_trailing_newline_counts(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\ntwo", "two", 2, 2)
    assert _reason_for(bundle, tmp_path) is Reason.OK
    over = _bundle(tmp_path, "b.py", "one\ntwo", "two", 1, 3)
    assert _reason_for(over, tmp_path) is Reason.RANGE_INVALID


# ---------------------------------------------------------------- empty evidence


def test_empty_snippet_rejected(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\n\n\n", "\n \n", 1, 3)
    assert _reason_for(bundle, tmp_path) is Reason.EMPTY_SNIPPET


def test_bundle_with_no_claims_ok(tmp_path):
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(), evidence=()))
    assert report.claims == ()
    assert report.quality.passed == 0
    assert report.duplicate_evidence_ids == ()


def test_missing_file(tmp_path):
    ev = EvidenceItem(id="ev1", path="nope.py", start_line=1, end_line=1, snippet="x")
    claim = Claim(id="c1", citations=(Citation("ev1"),))
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(claim,), evidence=(ev,)))
    assert report.claims[0].reason is Reason.FILE_NOT_FOUND


# ---------------------------------------------------------------- evidence ids


def test_missing_evidence_id(tmp_path):
    claim = Claim(id="c1", citations=(Citation("ghost"),))
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(claim,), evidence=()))
    assert report.claims[0].reason is Reason.EVIDENCE_ID_MISSING
    assert report.quality.failed == 1


def test_zero_citations(tmp_path):
    claim = Claim(id="c1", citations=())
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(claim,), evidence=()))
    assert report.claims[0].status is EvidenceStatus.DOWNGRADED
    assert report.claims[0].reason is Reason.NO_CITATIONS


def test_aggregate_quality_counts(tmp_path):
    _write(tmp_path, "a.py", "one\n")
    ev_ok = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="one")
    ev_bad = EvidenceItem(id="ev2", path="a.py", start_line=1, end_line=9, snippet="one")
    claims = (
        Claim(id="c1", citations=(Citation("ev1"),)),
        Claim(id="c2", citations=(Citation("ev2"),)),
    )
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=claims, evidence=(ev_ok, ev_bad)))
    assert report.quality.passed == 1
    assert report.quality.failed == 1
    assert report.quality.by_reason == {"ok": 1, "range_invalid": 1}
    assert report.claims[1].status is EvidenceStatus.DOWNGRADED


# ---------------------------------------------------------------- confinement


def test_dotdot_escape_rejected(tmp_path):
    bundle = _bundle(tmp_path, "a.py", "one\n", "one", 1, 1)
    ev = EvidenceItem(id="ev1", path="../outside.py", start_line=1, end_line=1, snippet="one")
    claim = Claim(id="c1", citations=(Citation("ev1"),))
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(claim,), evidence=(ev,)))
    assert report.claims[0].reason is Reason.PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "C:/Windows/win.ini", "C:\\x.py"])
def test_absolute_paths_rejected(tmp_path, bad_path):
    ev = EvidenceItem(id="ev1", path=bad_path, start_line=1, end_line=1, snippet="x")
    claim = Claim(id="c1", citations=(Citation("ev1"),))
    report = verify_bundle(str(tmp_path), VerdictBundle(claims=(claim,), evidence=(ev,)))
    assert report.claims[0].reason is Reason.PATH_NOT_RELATIVE
