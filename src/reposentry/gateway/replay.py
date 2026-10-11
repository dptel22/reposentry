"""Cache / recording store for the gateway.

One JSON file per recording, keyed by cache key. Entries record the model
response (text + usage) and the prompt/input hash, so replay is exact.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class RecordingStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        with self._lock:
            data = json.loads(path.read_text(encoding="utf-8"))
        return data

    def put(self, key: str, record: dict[str, Any]) -> None:
        path = self._path(key)
        with self._lock:
            path.write_text(
                json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
            )


class MemoryStore(RecordingStore):
    """In-memory store for tests and for the cache layer."""

    def __init__(self) -> None:  # noqa: D107 - no directory needed
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = record
