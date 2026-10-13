"""RepoSentry C1 Ingest — isolated workspace sandbox for hostile repositories."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from reposentry.config.settings import RepoSentryConfig
from reposentry.contracts.models import (
    IngestedFileRecord,
    RunManifest,
    compute_content_hash,
    normalize_and_validate_path,
)

BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".pdf",
        ".zip", ".tar", ".gz", ".7z", ".bz2", ".woff", ".woff2", ".ttf",
        ".eot", ".mp3", ".mp4", ".wav", ".db", ".sqlite", ".sqlite3",
        ".whl", ".egg",
    }
)

IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git", ".svn", ".hg", ".bzr", ".venv", "venv", "env", "ENV",
        "node_modules", "vendor", "vendors", "third_party", "__pycache__",
        ".idea", ".vscode", "dist", "build", ".eggs", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", ".hypothesis", "htmlcov",
    }
)


class IngestSecurityError(ValueError):
    """Raised when an ingest archive violates safety bounds (zip-slip, zip bomb, etc.)."""


@dataclass(frozen=True)
class IngestResult:
    """Result of an ingest operation."""

    workspace_dir: Path
    manifest: RunManifest
    is_empty: bool


def _is_binary_file(file_path: Path) -> bool:
    """Check if file is binary by extension or content null-byte heuristic."""
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(file_path, "rb") as fh:
            chunk = fh.read(1024)
            if b"\x00" in chunk:
                return True
    except (OSError, PermissionError):
        return True
    return False


def _compute_sha256(file_path: Path) -> str:
    """Compute sha256 of file bytes."""
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


class WorkspaceSandbox:
    """Materializes untrusted repositories into a sandboxed, read-only workspace directory as data."""

    def __init__(self, config: RepoSentryConfig | None = None) -> None:
        self.config = config or RepoSentryConfig()

    def ingest_directory(
        self,
        source_dir: Path | str,
        target_workspace: Path | str | None = None,
    ) -> IngestResult:
        """Ingest a local directory into a clean workspace, applying security exclusion rules."""
        src = Path(source_dir).resolve()
        if not src.exists() or not src.is_dir():
            raise ValueError(f"Source directory does not exist or is not a directory: {source_dir}")

        if target_workspace:
            dest = Path(target_workspace).resolve()
            dest.mkdir(parents=True, exist_ok=True)
            owns_dest = False
        else:
            dest = Path(tempfile.mkdtemp(prefix="reposentry_ws_"))
            owns_dest = True

        records: list[IngestedFileRecord] = []
        total_scanned_bytes = 0

        # Collect and deterministically sort relative file paths
        all_relative_files: list[Path] = []
        for root, dirs, files in os.walk(src):
            # Prune ignored/hostile VCS and vendor directories in-place
            dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIRECTORIES and not d.startswith(".git")]
            root_path = Path(root)
            for f in files:
                rel = (root_path / f).relative_to(src)
                all_relative_files.append(rel)

        # Stable deterministic alphabetical ordering by POSIX path
        all_relative_files.sort(key=lambda p: p.as_posix())

        file_count = 0
        for rel in all_relative_files:
            file_count += 1
            src_file = src / rel

            # Validate relative path against traversal & device names
            try:
                norm_rel = normalize_and_validate_path(rel.as_posix())
            except ValueError as e:
                records.append(
                    IngestedFileRecord(
                        file_path=rel.as_posix().replace("\\", "/"),
                        sha256="0" * 64,
                        size_bytes=0,
                        skipped=True,
                        skip_reason=f"invalid_path:{e}",
                    )
                )
                continue

            # Check total file count limit
            if file_count > self.config.max_file_count:
                records.append(
                    IngestedFileRecord(
                        file_path=norm_rel,
                        sha256="0" * 64,
                        size_bytes=0,
                        skipped=True,
                        skip_reason="file_count_limit_exceeded",
                    )
                )
                continue

            # Handle symlinks safely: never follow symlinks pointing outside src
            if src_file.is_symlink():
                try:
                    resolved_target = src_file.resolve()
                    if not resolved_target.is_relative_to(src):
                        records.append(
                            IngestedFileRecord(
                                file_path=norm_rel,
                                sha256="0" * 64,
                                size_bytes=0,
                                skipped=True,
                                skip_reason="symlink_escapes_workspace",
                            )
                        )
                        continue
                except (OSError, RuntimeError):
                    records.append(
                        IngestedFileRecord(
                            file_path=norm_rel,
                            sha256="0" * 64,
                            size_bytes=0,
                            skipped=True,
                            skip_reason="broken_symlink",
                        )
                    )
                    continue

            try:
                size = src_file.stat().st_size
            except OSError:
                size = 0

            # Check oversize file limit
            if size > self.config.max_file_size_bytes:
                records.append(
                    IngestedFileRecord(
                        file_path=norm_rel,
                        sha256="0" * 64,
                        size_bytes=size,
                        skipped=True,
                        skip_reason="oversized_file",
                    )
                )
                continue

            # Check total workspace size limit
            if total_scanned_bytes + size > self.config.max_total_size_bytes:
                records.append(
                    IngestedFileRecord(
                        file_path=norm_rel,
                        sha256="0" * 64,
                        size_bytes=size,
                        skipped=True,
                        skip_reason="workspace_total_size_limit_exceeded",
                    )
                )
                continue

            # Check binary files
            if _is_binary_file(src_file):
                records.append(
                    IngestedFileRecord(
                        file_path=norm_rel,
                        sha256="0" * 64,
                        size_bytes=size,
                        skipped=True,
                        skip_reason="binary_file",
                    )
                )
                continue

            # Copy file safely to sandboxed workspace as plain data
            dest_file = dest / Path(norm_rel)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Read text with fallback decoding to sanitize and ensure clean UTF-8
                with open(src_file, "rb") as sf:
                    raw_bytes = sf.read()
                file_hash = hashlib.sha256(raw_bytes).hexdigest()
                text = raw_bytes.decode("utf-8", errors="replace")
                with open(dest_file, "w", encoding="utf-8", newline="\n") as df:
                    df.write(text)

                total_scanned_bytes += size
                records.append(
                    IngestedFileRecord(
                        file_path=norm_rel,
                        sha256=file_hash,
                        size_bytes=size,
                        skipped=False,
                        skip_reason=None,
                    )
                )
            except OSError as e:
                records.append(
                    IngestedFileRecord(
                        file_path=norm_rel,
                        sha256="0" * 64,
                        size_bytes=size,
                        skipped=True,
                        skip_reason=f"io_error:{e}",
                    )
                )

        # Create RunManifest
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_id = f"run-{hashlib.sha256(f'{src.name}-{timestamp}'.encode()).hexdigest()[:12]}"

        # Deterministic manifest hash computed over canonical records
        records_for_hash = [r.model_dump(mode="json") for r in records]
        manifest_hash = hashlib.sha256(compute_content_hash(records_for_hash).encode()).hexdigest()

        active_files = [r for r in records if not r.skipped]
        manifest = RunManifest(
            run_id=run_id,
            target_name=src.name,
            timestamp=timestamp,
            files=records,
            total_files=len(active_files),
            total_bytes=sum(r.size_bytes for r in active_files),
            manifest_hash=manifest_hash,
        )

        return IngestResult(
            workspace_dir=dest,
            manifest=manifest,
            is_empty=len(active_files) == 0,
        )

    def ingest_archive(
        self,
        archive_path: Path | str,
        target_workspace: Path | str | None = None,
    ) -> IngestResult:
        """Safely unpack an untrusted zip archive guarding against Zip-Slip, Zip-Bomb, and hostile links."""
        p = Path(archive_path).resolve()
        if not p.exists() or not p.is_file():
            raise ValueError(f"Archive file does not exist: {archive_path}")

        temp_extract = Path(tempfile.mkdtemp(prefix="reposentry_unpack_"))
        try:
            with zipfile.ZipFile(p, "r") as zf:
                infolist = zf.infolist()

                # Guard 1: entry count check
                if len(infolist) > self.config.max_file_count:
                    raise IngestSecurityError(
                        f"Archive exceeds maximum file count limit ({len(infolist)} > {self.config.max_file_count})"
                    )

                total_uncompressed = 0
                compressed_size = max(p.stat().st_size, 1)

                for member in infolist:
                    # Guard 2: zip-slip check (directory traversal in zip entries)
                    member_path = member.filename
                    if member_path.startswith(("/", "\\")) or ":" in member_path:
                        raise IngestSecurityError(f"Zip-slip attack detected (absolute/colon path): '{member_path}'")

                    cleaned_parts = [part for part in member_path.replace("\\", "/").split("/") if part and part != "."]
                    if any(part == ".." for part in cleaned_parts):
                        raise IngestSecurityError(f"Zip-slip attack detected (path traversal '..'): '{member_path}'")

                    # Guard 3: zip bomb check (compression ratio and total uncompressed size)
                    total_uncompressed += member.file_size
                    ratio = total_uncompressed / compressed_size
                    if ratio > self.config.max_compression_ratio:
                        raise IngestSecurityError(
                            f"Zip bomb detected: compression ratio {ratio:.1f} exceeds limit {self.config.max_compression_ratio}"
                        )
                    if total_uncompressed > self.config.max_total_size_bytes:
                        raise IngestSecurityError(
                            f"Zip bomb detected: uncompressed size ({total_uncompressed}) exceeds limit {self.config.max_total_size_bytes}"
                        )

                # Safe extraction
                for member in infolist:
                    if member.is_dir():
                        continue
                    # Normalize target
                    dest_file = (temp_extract / member.filename).resolve()
                    if not dest_file.is_relative_to(temp_extract):
                        raise IngestSecurityError(f"Zip-slip extraction prevented: '{member.filename}'")

                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as source, open(dest_file, "wb") as target:
                        shutil.copyfileobj(source, target)

            # Once extracted into isolated temp folder, run standard directory ingest
            return self.ingest_directory(temp_extract, target_workspace=target_workspace)
        finally:
            shutil.rmtree(temp_extract, ignore_errors=True)
