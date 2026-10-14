from __future__ import annotations

import json
from typing import Any, TextIO

from reposentry.observability.redact import strip_source_and_secrets
from reposentry.observability.types import TraceEvent


class StructuredLogger:
    """JSON logs. Source content omitted by default."""

    def __init__(self, stream: TextIO, *, include_source: bool = False) -> None:
        self._stream = stream
        self.include_source = include_source
        self.records: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any] | TraceEvent) -> None:
        if isinstance(event, TraceEvent):
            payload = event.as_log_record()
        else:
            payload = dict(event)
        safe = strip_source_and_secrets(payload, include_source=self.include_source)
        self.records.append(safe)
        self._stream.write(json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n")
        self._stream.flush()
