"""Deterministic function-level Python chunks with AST line provenance."""

from __future__ import annotations

import ast
import hashlib
import os
import re
from pathlib import PurePosixPath
from typing import Mapping

from .types import RetrievalChunk

_DRIVE = re.compile(r"^[A-Za-z]:")


def chunks_from_python(
    files: Mapping[str, str],
    *,
    max_chunk_chars: int = 3000,
    max_file_chars: int = 1_000_000,
) -> tuple[RetrievalChunk, ...]:
    """Chunk functions/classes plus uncovered module blocks.

    Oversized blocks are split at newline boundaries. A single oversized line
    is split by characters while retaining its exact 1-based line location.
    Syntax-invalid files still contribute bounded module text.
    """
    if max_chunk_chars < 1 or max_file_chars < 1:
        raise ValueError("chunk size limits must be positive")
    chunks: list[RetrievalChunk] = []
    for path in sorted(files):
        normalized = _relative_path(path)
        if normalized is None:
            continue
        source = files[path]
        if not isinstance(source, str) or len(source) > max_file_chars:
            continue
        lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if not lines:
            continue
        try:
            tree = ast.parse(source, filename=normalized)
        except SyntaxError:
            tree = None
        covered = [False] * len(lines)
        ranges: list[tuple[int, int, str]] = []
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
                    end = getattr(node, "end_lineno", node.lineno)
                    ranges.append((start, end, "function" if not isinstance(node, ast.ClassDef) else "class"))
                    for index in range(max(0, start - 1), min(len(lines), end)):
                        covered[index] = True
        for start, end, kind in sorted(ranges):
            chunks.extend(_split_range(normalized, lines, start, end, kind, max_chunk_chars))
        # Module-level text is emitted only where no function/class owns lines.
        run_start: int | None = None
        for index, is_covered in enumerate([*covered, True]):
            if not is_covered and run_start is None:
                run_start = index
            elif is_covered and run_start is not None:
                chunks.extend(_split_range(normalized, lines, run_start + 1, index, "module", max_chunk_chars))
                run_start = None
    chunks.sort(key=lambda chunk: (chunk.path, chunk.start_line, chunk.end_line, chunk.kind, chunk.id))
    return tuple(chunks)


def _split_range(path: str, lines: list[str], start: int, end: int, kind: str, limit: int) -> list[RetrievalChunk]:
    result: list[RetrievalChunk] = []
    current: list[tuple[int, str]] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            first, last = current[0][0], current[-1][0]
            text = "\n".join(line for _, line in current)
            digest = hashlib.sha256(f"{path}\0{first}\0{last}\0{kind}\0{text}".encode("utf-8")).hexdigest()[:24]
            result.append(RetrievalChunk(digest, path, first, last, kind, text))
            current, size = [], 0

    for line_no in range(start, min(end, len(lines)) + 1):
        line = lines[line_no - 1]
        if len(line) > limit:
            flush()
            for offset in range(0, len(line), limit):
                piece = line[offset : offset + limit]
                digest = hashlib.sha256(f"{path}\0{line_no}\0{kind}\0{offset}\0{piece}".encode("utf-8")).hexdigest()[:24]
                result.append(RetrievalChunk(digest, path, line_no, line_no, kind, piece, citable=False))
            continue
        if current and size + len(line) + 1 > limit:
            flush()
        current.append((line_no, line))
        size += len(line) + 1
    flush()
    return result


def _relative_path(path: str) -> str | None:
    if not path or path.startswith(("/", "\\")) or _DRIVE.match(path):
        return None
    normalized = path.replace("\\", "/")
    if any(part in ("", ".", "..") for part in normalized.split("/")):
        return None
    return PurePosixPath(normalized).as_posix()
