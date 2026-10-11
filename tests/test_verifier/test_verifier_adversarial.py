"""Adversarial suite for the C8 deterministic evidence verifier.

These tests attempt to defeat the verifier with hostile evidence bundles:
path escapes, symlinks out of the workspace, enormous ranges, duplicate
evidence ids, snippets planted elsewhere, and claims with no citations.
The verifier must downgrade with a reason code — never raise, never pass.
"""

from __future__ import annotations

import os
import sys

import pytest

from reposentry.verifier import (
    Citation,
    Claim,
    EvidenceItem,
    EvidenceStatus,
    Reason,
    VerdictBundle,
    verify_bundle,
)


def _verify(tmp_path, evidence, claims):
    return verify_bundle(str(tmp_path), VerdictBundle(claims=tuple(claims), evidence=tuple(evidence)))


def _claim(evidence_id: str = "ev1") -> Claim:
    return Claim(id="c1", citations=(Citation(evidence_id),))


def test_citation_path_dotdot_outside_workspace(tmp_path):
    # The cited file genuinely exists outside the workspace; the verifier must
    # refuse the path before ever touching it.
    outside = tmp_path.parent / "outside_adversarial.py"
    outside.write_text("one\n", encoding="utf-8")
    try:
        ev = EvidenceItem(id="ev1", path="../outside_adversarial.py", start_line=1, end_line=1, snippet="one")
        report = _verify(tmp_path, [ev], [_claim()])
        assert report.claims[0].status is EvidenceStatus.DOWNGRADED
        assert report.claims[0].reason is Reason.PATH_ESCAPES_WORKSPACE
    finally:
        outside.unlink(missing_ok=True)


def test_citation_path_absolute(tmp_path):
    abs_path = str(tmp_path / "a.py")
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    for variant in (abs_path, abs_path.replace("\\", "/"), abs_path.replace("/", "\\")):
        ev = EvidenceItem(id="ev1", path=variant, start_line=1, end_line=1, snippet="one")
        report = _verify(tmp_path, [ev], [_claim()])
        assert report.claims[0].reason is Reason.PATH_NOT_RELATIVE, variant


def test_symlinked_file_pointing_outside_workspace(tmp_path):
    target = tmp_path.parent / "symlink_target_adversarial.py"
    target.write_text("real content outside\n", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform/account")
    ev = EvidenceItem(id="ev1", path="link.py", start_line=1, end_line=1, snippet="real content outside")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].status is EvidenceStatus.DOWNGRADED
    assert report.claims[0].reason is Reason.PATH_SYMLINK_ESCAPE


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are Windows-specific")
def test_junction_pointing_outside_workspace(tmp_path):
    # Directory junctions need no special privilege on Windows, so this
    # exercises the same realpath-escape check the symlink test would.
    target = tmp_path.parent / "junction_target_adversarial"
    target.mkdir(exist_ok=True)
    (target / "inner.py").write_text("real content outside\n", encoding="utf-8")
    link = tmp_path / "jdir"
    import subprocess

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
    )
    try:
        if result.returncode != 0:
            pytest.skip("junction creation not permitted")
        ev = EvidenceItem(
            id="ev1", path="jdir/inner.py", start_line=1, end_line=1, snippet="real content outside"
        )
        report = _verify(tmp_path, [ev], [_claim()])
        assert report.claims[0].status is EvidenceStatus.DOWNGRADED
        assert report.claims[0].reason is Reason.PATH_SYMLINK_ESCAPE
    finally:
        if link.exists():
            os.rmdir(str(link))


def test_enormous_range_rejected(tmp_path):
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=10**9, snippet="one")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].reason is Reason.RANGE_INVALID  # end > file line count


def test_range_too_large_but_within_file(tmp_path):
    # A range that is inside the file's line count but over the 5000-line cap.
    lines = "\n".join(f"line{i}" for i in range(6000)) + "\n"
    (tmp_path / "big.py").write_text(lines, encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="big.py", start_line=1, end_line=5001, snippet="line0")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].reason is Reason.RANGE_TOO_LARGE


def test_duplicate_evidence_ids_reported(tmp_path):
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    ev_a = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="one")
    ev_b = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="WRONG")
    report = _verify(tmp_path, [ev_a, ev_b], [_claim()])
    assert report.duplicate_evidence_ids == ("ev1",)
    # First occurrence is used for checking; the claim passes on the good copy.
    assert report.claims[0].status is EvidenceStatus.OK


def test_duplicate_evidence_ids_with_conflicting_content_downgrade(tmp_path):
    # If the first duplicate is the poisoned one, the claim downgrades even
    # though a later copy would have passed — deterministic first-wins.
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    ev_bad = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="WRONG")
    ev_good = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="one")
    report = _verify(tmp_path, [ev_bad, ev_good], [_claim()])
    assert report.duplicate_evidence_ids == ("ev1",)
    assert report.claims[0].reason is Reason.QUOTE_MISMATCH


def test_snippet_exists_elsewhere_but_not_at_cited_range(tmp_path):
    (tmp_path / "a.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=2, snippet="gamma")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].status is EvidenceStatus.DOWNGRADED
    assert report.claims[0].reason is Reason.QUOTE_MISMATCH


def test_same_snippet_in_different_file(tmp_path):
    (tmp_path / "a.py").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("alpha\n", encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="b.py", start_line=1, end_line=1, snippet="alpha")
    # Snippet true in a.py but cited to b.py at a range where b.py differs.
    (tmp_path / "b.py").write_text("beta\nalpha\n", encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="b.py", start_line=1, end_line=1, snippet="alpha")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].reason is Reason.QUOTE_MISMATCH


def test_claim_with_zero_citations(tmp_path):
    report = _verify(tmp_path, [], [Claim(id="c1", citations=())])
    assert report.claims[0].status is EvidenceStatus.DOWNGRADED
    assert report.claims[0].reason is Reason.NO_CITATIONS
    assert report.quality.failed == 1


def test_subdirectory_traversal_via_dotdot_segment(tmp_path):
    # 'sub/../x.py' normalizes to x.py — the verifier accepts the relative
    # shape but realpath must keep it inside; '..' segment itself is rejected.
    ev = EvidenceItem(id="ev1", path="sub/../../x.py", start_line=1, end_line=1, snippet="x")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].reason is Reason.PATH_ESCAPES_WORKSPACE


def test_cited_directory_instead_of_file(tmp_path):
    (tmp_path / "sub").mkdir()
    ev = EvidenceItem(id="ev1", path="sub", start_line=1, end_line=1, snippet="x")
    report = _verify(tmp_path, [ev], [_claim()])
    assert report.claims[0].reason is Reason.FILE_NOT_FOUND


def test_verifier_never_raises_on_hostile_bundle(tmp_path):
    hostile = VerdictBundle(
        claims=(
            Claim(id="c1", citations=()),
            Claim(id="c2", citations=(Citation("nope"),)),
            Claim(id="c3", citations=(Citation("ev1"), Citation("nope"))),
        ),
        evidence=(
            EvidenceItem(id="ev1", path="../escape.py", start_line=0, end_line=10**9, snippet=""),
            EvidenceItem(id="ev1", path="C:/abs", start_line=-5, end_line=0, snippet="x"),
        ),
    )
    report = verify_bundle(str(tmp_path), hostile)
    assert [c.status for c in report.claims] == [EvidenceStatus.DOWNGRADED] * 3
    assert report.duplicate_evidence_ids == ("ev1",)


def test_reason_codes_are_machine_readable_and_deterministic(tmp_path):
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="a.py", start_line=1, end_line=1, snippet="one")
    r1 = _verify(tmp_path, [ev], [_claim()])
    r2 = _verify(tmp_path, [ev], [_claim()])
    assert r1 == r2
    assert r1.claims[0].reason.value == "ok"
    assert r1.quality.by_reason == {"ok": 1}


def test_backslash_paths_are_normalized_not_escaped(tmp_path):
    # Windows-style separators inside a relative path must not bypass checks.
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_text("one\n", encoding="utf-8")
    ev = EvidenceItem(id="ev1", path="sub\\a.py", start_line=1, end_line=1, snippet="one")
    report = _verify(tmp_path, [ev], [_claim()])
    if sys.platform == "win32":
        # os.path.isabs is platform-dependent for backslash forms; on Windows
        # this is treated as a normal relative path and must match.
        assert report.claims[0].reason is Reason.OK
    else:
        assert report.claims[0].reason is Reason.OK
