"""Unit tests for C1 Ingest sandbox: exclusions, ordering, deterministic manifests."""

from __future__ import annotations

from pathlib import Path

import pytest

from reposentry.config.settings import RepoSentryConfig
from reposentry.ingest.sandbox import WorkspaceSandbox


def test_ingest_standard_directory(tmp_path: Path) -> None:
    src = tmp_path / "sample_app"
    src.mkdir()
    (src / "app.py").write_text("print('hello')", encoding="utf-8")
    (src / "routes.py").write_text("def index(): pass", encoding="utf-8")

    sandbox = WorkspaceSandbox()
    result = sandbox.ingest_directory(src)

    assert result.is_empty is False
    assert result.manifest.total_files == 2
    assert (result.workspace_dir / "app.py").exists()
    assert (result.workspace_dir / "routes.py").exists()


def test_ingest_drops_vendor_and_vcs_directories(tmp_path: Path) -> None:
    src = tmp_path / "repo"
    src.mkdir()
    (src / "main.py").write_text("app = 1", encoding="utf-8")

    # Hostile / vendor directories
    git_dir = src / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit").write_text("malicious hook", encoding="utf-8")

    node_modules = src / "node_modules" / "pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("evil", encoding="utf-8")

    venv = src / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "site.py").write_text("pass", encoding="utf-8")

    sandbox = WorkspaceSandbox()
    result = sandbox.ingest_directory(src)

    assert result.manifest.total_files == 1
    assert not (result.workspace_dir / ".git").exists()
    assert not (result.workspace_dir / "node_modules").exists()
    assert not (result.workspace_dir / ".venv").exists()
    assert (result.workspace_dir / "main.py").exists()


def test_ingest_drops_binary_files(tmp_path: Path) -> None:
    src = tmp_path / "repo"
    src.mkdir()
    (src / "main.py").write_text("x = 1", encoding="utf-8")
    (src / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (src / "compiled.pyc").write_bytes(b"\x00\x00\x00\x00")

    sandbox = WorkspaceSandbox()
    result = sandbox.ingest_directory(src)

    assert result.manifest.total_files == 1
    assert (result.workspace_dir / "main.py").exists()
    assert not (result.workspace_dir / "image.png").exists()

    skipped = {r.file_path: r.skip_reason for r in result.manifest.files if r.skipped}
    assert "image.png" in skipped
    assert skipped["image.png"] == "binary_file"


def test_ingest_drops_oversized_files(tmp_path: Path) -> None:
    src = tmp_path / "repo"
    src.mkdir()
    (src / "normal.py").write_text("a = 1", encoding="utf-8")
    (src / "huge.txt").write_text("A" * 2000, encoding="utf-8")

    # Config with 1KB limit
    cfg = RepoSentryConfig(max_file_size_bytes=1024)
    sandbox = WorkspaceSandbox(config=cfg)
    result = sandbox.ingest_directory(src)

    assert result.manifest.total_files == 1
    skipped = {r.file_path: r.skip_reason for r in result.manifest.files if r.skipped}
    assert "huge.txt" in skipped
    assert skipped["huge.txt"] == "oversized_file"


def test_ingest_deterministic_ordering_and_hash(tmp_path: Path) -> None:
    src = tmp_path / "repo"
    src.mkdir()
    (src / "z.py").write_text("z = 1\n", encoding="utf-8")
    (src / "a.py").write_text("a = 1\n", encoding="utf-8")
    (src / "m.py").write_text("m = 1\n", encoding="utf-8")

    sandbox = WorkspaceSandbox()
    res1 = sandbox.ingest_directory(src)
    res2 = sandbox.ingest_directory(src)

    assert [r.file_path for r in res1.manifest.files] == ["a.py", "m.py", "z.py"]
    assert res1.manifest.manifest_hash == res2.manifest.manifest_hash


def test_ingest_empty_directory_yields_empty_result(tmp_path: Path) -> None:
    empty_src = tmp_path / "empty_repo"
    empty_src.mkdir()

    sandbox = WorkspaceSandbox()
    result = sandbox.ingest_directory(empty_src)

    assert result.is_empty is True
    assert result.manifest.total_files == 0
