"""Cache / recording store for the gateway.

One JSON file per recording, keyed by cache key. Entries record the model
response (text + usage) and the prompt/input hash, so replay is exact.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import threading
from pathlib import Path
from typing import Any


class ReplayIntegrityError(ValueError):
    """A recording is unsigned, malformed, or has failed authentication."""


class RecordingStore:
    def __init__(self, directory: str | Path, *, key: bytes | None = None) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._key = self._validate_key(key) if key is not None else self._configured_key()

    @staticmethod
    def _validate_key(key: bytes) -> bytes:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ReplayIntegrityError("replay signing key must contain at least 32 bytes")
        return key

    @staticmethod
    def _configured_key() -> bytes:
        configured_key = os.environ.get("REPOSENTRY_REPLAY_HMAC_KEY")
        if configured_key is None:
            raise ReplayIntegrityError(
                "filesystem replay requires key=... or REPOSENTRY_REPLAY_HMAC_KEY"
            )
        key = configured_key.encode("utf-8")
        try:
            return RecordingStore._validate_key(key)
        except ReplayIntegrityError as exc:
            raise ReplayIntegrityError(
                "REPOSENTRY_REPLAY_HMAC_KEY must contain at least 32 bytes"
            ) from exc

    def _signature(self, key: str, record: dict[str, Any]) -> str:
        body = json.dumps(
            {"cache_key": key, "record": record},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hmac.new(self._key, body.encode("utf-8"), hashlib.sha256).hexdigest()

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("recording key must be a lowercase SHA-256 hex digest")
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        with self._lock:
            data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("record"), dict):
            raise ReplayIntegrityError("replay recording has invalid format")
        expected = self._signature(key, data["record"])
        if not hmac.compare_digest(str(data.get("hmac", "")), expected):
            raise ReplayIntegrityError("replay recording integrity check failed")
        return data["record"]

    def put(self, key: str, record: dict[str, Any]) -> None:
        path = self._path(key)
        with self._lock:
            envelope = {"record": record, "hmac": self._signature(key, record)}
            path.write_text(
                json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
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
