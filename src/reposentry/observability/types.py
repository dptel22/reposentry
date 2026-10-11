from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class EventKind(str, Enum):
    STAGE = "stage"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    TIMEOUT = "timeout"
    VALIDATION_FAILURE = "validation_failure"
    TOOL_REJECTION = "tool_rejection"
    BUDGET = "budget"
    FALLBACK = "fallback"
    CACHE = "cache"
    REPLAY_MISS = "replay_miss"


@dataclass(frozen=True)
class TraceEvent:
    run_id: str
    span_id: str
    kind: EventKind
    name: str
    ok: bool
    latency_ms: float = 0.0
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def as_log_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "span_id": self.span_id,
            "kind": self.kind.value,
            "name": self.name,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "attributes": dict(self.attributes),
        }


@dataclass
class Span:
    run_id: str
    span_id: str
    kind: EventKind
    name: str
    start_s: float
    model: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    ok: bool = True
    ended: bool = False
    latency_ms: float = 0.0
