"""Adversarial tests for C1 Ingest: Zip-Slip, Zip-Bomb, hostile symlinks, file limits."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from reposentry.config.settings import RepoSentryConfig
from reposentry.ingest.sandbox import IngestSecurityError, WorkspaceSandbox


def test_zip_slip_parent_traversal_blocked(tmp_path: Path) -> None:
    # P1.6: Zip-slip with .. traversal
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../../evil.py", "malicious_code = True")

    archive_path = tmp_path / "slip.zip"
    archive_path.write_bytes(zip_buf.getvalue())

    sandbox = WorkspaceSandbox()
    with pytest.raises(IngestSecurityError, match="Zip-slip attack detected"):
        sandbox.ingest_archive(archive_path)


def test_zip_slip_absolute_path_blocked(tmp_path: Path) -> None:
    # P1.6: Zip-slip with absolute Unix path
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("/etc/passwd", "root:x:0:0")

    archive_path = tmp_path / "slip_abs.zip"
    archive_path.write_bytes(zip_buf.getvalue())

    sandbox = WorkspaceSandbox()
    with pytest.raises(IngestSecurityError, match="Zip-slip attack detected"):
        sandbox.ingest_archive(archive_path)


def test_zip_bomb_compression_ratio_blocked(tmp_path: Path) -> None:
    # P1.8: Zip bomb high compression ratio
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1MB of zeros compresses to a few bytes
        zf.writestr("bomb.txt", b"\x00" * 1_000_000)

    archive_path = tmp_path / "bomb.zip"
    archive_path.write_bytes(zip_buf.getvalue())

    # Low compression ratio threshold
    cfg = RepoSentryConfig(max_compression_ratio=10.0)
    sandbox = WorkspaceSandbox(config=cfg)

    with pytest.raises(IngestSecurityError, match="Zip bomb detected"):
        sandbox.ingest_archive(archive_path)


def test_zip_bomb_uncompressed_size_blocked(tmp_path: Path) -> None:
    # P1.8: Uncompressed total size limit
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("large.txt", b"A" * 20_000)

    archive_path = tmp_path / "large.zip"
    archive_path.write_bytes(zip_buf.getvalue())

    # 10KB total limit
    cfg = RepoSentryConfig(max_total_size_bytes=10_000, max_compression_ratio=1000.0)
    sandbox = WorkspaceSandbox(config=cfg)

    with pytest.raises(IngestSecurityError, match="Zip bomb detected: uncompressed size"):
        sandbox.ingest_archive(archive_path)


def test_thousands_of_tiny_files_capped(tmp_path: Path) -> None:
    # P1.9: File count limit
    src = tmp_path / "many_files"
    src.mkdir()
    for i in range(25):
        (src / f"file_{i:03d}.py").write_text(f"x_{i} = 1", encoding="utf-8")

    cfg = RepoSentryConfig(max_file_count=10)
    sandbox = WorkspaceSandbox(config=cfg)
    result = sandbox.ingest_directory(src)

    # First 10 accepted, remainder marked skipped
    accepted = [r for r in result.manifest.files if not r.skipped]
    skipped = [r for r in result.manifest.files if r.skipped]

    assert len(accepted) == 10
    assert len(skipped) == 15
    assert all(r.skip_reason == "file_count_limit_exceeded" for r in skipped)


def test_hostile_git_hooks_and_config_stripped(tmp_path: Path) -> None:
    # P1.12: Hostile .git hooks stripped
    src = tmp_path / "hostile_repo"
    src.mkdir()
    (src / "app.py").write_text("from flask import Flask", encoding="utf-8")

    git_dir = src / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\nhooksPath = /tmp/evil", encoding="utf-8")
    hooks = git_dir / "hooks"
    hooks.mkdir()
    (hooks / "post-checkout").write_text("#!/bin/sh\nrm -rf /", encoding="utf-8")

    sandbox = WorkspaceSandbox()
    result = sandbox.ingest_directory(src)

    assert result.manifest.total_files == 1
    assert (result.workspace_dir / "app.py").exists()
    assert not (result.workspace_dir / ".git").exists()
