"""Bounded, read-only static Python workspace tools for the C7 agent."""

from __future__ import annotations

import ast
import json
import os
import re
import stat as statmod
from pathlib import Path
from typing import Any

TOOL_NAMES = (
    "code_search",
    "symbol_lookup",
    "callers",
    "callees",
    "route_context",
    "test_lookup",
)

_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "vendor", "__pycache__", "dist", "build"})


class ToolRejected(ValueError):
    """A requested tool or argument is outside the read-only allowlist."""


class WorkspaceTools:
    """Small static source index. It never imports or executes workspace code."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        max_files: int = 5000,
        max_file_bytes: int = 1_000_000,
        max_result_chars: int = 8000,
    ) -> None:
        self.root = Path(workspace_root).resolve()
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_result_chars = max_result_chars
        if min(max_files, max_file_bytes, max_result_chars) < 1:
            raise ValueError("workspace tool limits must be positive")

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            raise ToolRejected("tool is not allowlisted")
        if not isinstance(arguments, dict) or set(arguments) - {"query", "symbol", "path", "route", "test_query"}:
            raise ToolRejected("tool arguments contain unsupported fields")
        sources = self._sources()
        if name == "code_search":
            return self._search(sources, self._query(arguments.get("query")))
        if name == "symbol_lookup":
            return self._symbol(sources, self._query(arguments.get("symbol")))
        if name == "callers":
            return self._callers(sources, self._query(arguments.get("symbol")))
        if name == "callees":
            return self._callees(sources, self._query(arguments.get("symbol")))
        if name == "route_context":
            return self._route(sources, self._query(arguments.get("route") or arguments.get("path")))
        return self._tests(sources, self._query(arguments.get("test_query") or arguments.get("query")))

    @staticmethod
    def _query(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ToolRejected("query must be a nonempty string of at most 256 characters")
        return value.strip()

    def _sources(self) -> list[tuple[str, str, list[str]]]:
        collected: list[tuple[str, str, list[str]]] = []
        for current, dirs, filenames in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(
                name for name in dirs
                if name not in _SKIP_DIRS and not (Path(current) / name).is_symlink()
            )
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                if _is_dos_device(filename):
                    continue
                path = Path(current) / filename
                try:
                    resolved_before = Path(os.path.realpath(path))
                    if not _confined(self.root, resolved_before) or path.is_symlink():
                        continue
                    stat_before = path.stat(follow_symlinks=False)
                    if not statmod.S_ISREG(stat_before.st_mode) or stat_before.st_size > self.max_file_bytes:
                        continue
                    fd = os.open(
                        str(path),
                        os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    )
                    try:
                        opened = os.fstat(fd)
                        if (opened.st_dev, opened.st_ino) != (stat_before.st_dev, stat_before.st_ino):
                            continue
                        if opened.st_size > self.max_file_bytes:
                            continue
                        with os.fdopen(fd, "rb", closefd=False) as fh:
                            raw = fh.read(self.max_file_bytes + 1)
                    finally:
                        os.close(fd)
                    if len(raw) > self.max_file_bytes:
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    rel = path.relative_to(self.root).as_posix()
                    collected.append((rel, text, text.splitlines()))
                    if len(collected) >= self.max_files:
                        return collected
                except (OSError, ValueError):
                    continue
        return collected

    def _trim(self, value: dict[str, Any]) -> dict[str, Any]:
        if len(_json(value)) <= self.max_result_chars:
            return value
        results = []
        was_truncated = bool(value.get("truncated", False))
        base = {"truncated": True, "results": []}
        if len(_json(base)) > self.max_result_chars:
            return {"truncated": True, "results": []}
        for original in value.get("results", []):
            item = original
            while len(_json({"truncated": True, "results": [*results, item]})) > self.max_result_chars:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"]:
                    item = None
                    break
                excess = len(_json({"truncated": True, "results": [*results, item]})) - self.max_result_chars
                item = {
                    **item,
                    "text": item["text"][: max(0, len(item["text"]) - excess - 1)],
                    "source_exact": False,
                }
            if item is None:
                was_truncated = True
                break
            results.append(item)
            if len(_json({"truncated": True, "results": results})) >= self.max_result_chars:
                was_truncated = True
                break
        result = {"truncated": was_truncated, "results": results}
        if len(_json(result)) > self.max_result_chars:
            return base
        return result

    def _search(self, sources, query: str) -> dict[str, Any]:
        needle = query.casefold()
        hits = []
        for path, _, lines in sources:
            for number, line in enumerate(lines, start=1):
                if needle in line.casefold():
                    hits.append({"path": path, "line": number, "text": line[:1000], "source_exact": len(line) <= 1000})
                    if len(hits) >= 50:
                        return self._trim({"results": hits, "truncated": True})
        return self._trim({"results": hits, "truncated": False})

    def _symbol(self, sources, symbol: str) -> dict[str, Any]:
        results = []
        for path, text, lines in sources:
            try:
                tree = ast.parse(text, filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                    start = min([node.lineno, *(decorator.lineno for decorator in getattr(node, "decorator_list", ()))])
                    actual_end = getattr(node, "end_lineno", node.lineno)
                    end = min(actual_end, start + 119)
                    results.append({
                        "path": path,
                        "start_line": start,
                        "end_line": end,
                        "name": node.name,
                        "text": "\n".join(lines[start - 1 : end]),
                        "source_exact": True,
                    })
        return self._trim({"results": results[:50], "truncated": len(results) > 50})

    def _callers(self, sources, symbol: str) -> dict[str, Any]:
        results = []
        for path, text, lines in sources:
            try:
                tree = ast.parse(text, filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _call_name(node.func).split(".")[-1] == symbol:
                    line = lines[node.lineno - 1]
                    results.append({"path": path, "line": node.lineno, "text": line[:1000], "source_exact": len(line) <= 1000})
                    if len(results) >= 100:
                        return self._trim({"results": results, "truncated": True})
        return self._trim({"results": results, "truncated": False})

    def _callees(self, sources, symbol: str) -> dict[str, Any]:
        results = []
        for path, text, lines in sources:
            try:
                tree = ast.parse(text, filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            line = lines[child.lineno - 1]
                            results.append({"path": path, "line": child.lineno, "name": _call_name(child.func), "text": line[:1000], "source_exact": len(line) <= 1000})
                            if len(results) >= 100:
                                return self._trim({"results": results, "truncated": True})
        # Stable unique call names while retaining their first source location.
        unique: dict[str, dict[str, Any]] = {}
        for item in results:
            unique.setdefault(item["name"], item)
        return self._trim({"results": list(unique.values()), "truncated": False})

    def _route(self, sources, route: str) -> dict[str, Any]:
        results = []
        needle = route.casefold()
        for path, text, lines in sources:
            try:
                tree = ast.parse(text, filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorators = [ast.get_source_segment(text, decorator) or "" for decorator in node.decorator_list]
                if any("route" in dec.casefold() and needle in dec.casefold() for dec in decorators):
                    route_decorators = [
                        decorator for decorator in node.decorator_list
                        if "route" in (ast.get_source_segment(text, decorator) or "").casefold()
                        and needle in (ast.get_source_segment(text, decorator) or "").casefold()
                    ]
                    start = min(decorator.lineno for decorator in route_decorators)
                    end = max(getattr(decorator, "end_lineno", decorator.lineno) for decorator in route_decorators)
                    results.append({"path": path, "name": node.name, "line": start, "start_line": start,
                                    "end_line": end, "decorators": decorators[:8],
                                    "text": "\n".join(lines[start - 1:end]), "source_exact": True})
        return self._trim({"results": results[:50], "truncated": len(results) > 50})

    def _tests(self, sources, query: str) -> dict[str, Any]:
        needle = query.casefold()
        results = []
        for path, text, lines in sources:
            if not (path.rsplit("/", 1)[-1].startswith("test_") or "/tests/" in f"/{path}/"):
                continue
            try:
                tree = ast.parse(text, filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_") and needle in node.name.casefold():
                    line = lines[node.lineno - 1]
                    results.append({"path": path, "line": node.lineno, "name": node.name,
                                    "text": line[:1000], "source_exact": len(line) <= 1000})
        return self._trim({"results": results[:100], "truncated": len(results) > 100})


def _confined(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_dos_device(filename: str) -> bool:
    base = filename.split(":", 1)[0].rstrip(" .").split(".", 1)[0].rstrip(" ")
    return bool(re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", base))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

