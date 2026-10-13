"""Deterministic operational counters derived from sanitized trace events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .types import EventKind, TraceEvent


@dataclass(frozen=True)
class OperationalMetrics:
    events: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    provider_timeouts: int = 0
    validation_rejections: int = 0
    tool_rejections: int = 0
    budget_hits: int = 0
    cache_hits: int = 0
    parse_failures: int = 0
    parse_attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    @property
    def validation_rejection_rate(self) -> float:
        return self.validation_rejections / self.model_calls if self.model_calls else 0.0

    @property
    def parse_failure_rate(self) -> float:
        return self.parse_failures / self.parse_attempts if self.parse_attempts else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "events": self.events,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "provider_timeouts": self.provider_timeouts,
            "validation_rejections": self.validation_rejections,
            "validation_rejection_rate": self.validation_rejection_rate,
            "tool_rejections": self.tool_rejections,
            "budget_hits": self.budget_hits,
            "cache_hits": self.cache_hits,
            "parse_failures": self.parse_failures,
            "parse_attempts": self.parse_attempts,
            "parse_failure_rate": self.parse_failure_rate,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
        }


def aggregate_metrics(events: Iterable[TraceEvent]) -> OperationalMetrics:
    rows = tuple(events)
    model_events = tuple(event for event in rows if event.kind is EventKind.MODEL_CALL)
    parse_events = tuple(
        event for event in rows
        if event.name.casefold() in {"parse", "parse_failure", "parse_success"}
        or event.attributes.get("stage") == "parse"
    )
    values = {
        "events": len(rows),
        "model_calls": len(model_events),
        "tool_calls": sum(event.kind is EventKind.TOOL_CALL for event in rows),
        "provider_timeouts": sum(
            event.attributes.get("error_kind") == "timeout" for event in model_events
        ),
        "validation_rejections": sum(event.kind is EventKind.VALIDATION_FAILURE for event in rows),
        "tool_rejections": sum(event.kind is EventKind.TOOL_REJECTION for event in rows),
        "budget_hits": sum(event.kind is EventKind.BUDGET for event in rows),
        "cache_hits": sum(event.kind is EventKind.CACHE and event.name == "cache_hit" for event in rows),
        "parse_failures": sum(not event.ok for event in parse_events),
        "parse_attempts": len(parse_events),
        "tokens_in": sum(event.tokens_in for event in rows),
        "tokens_out": sum(event.tokens_out for event in rows),
        "cost_usd": sum(event.cost_usd for event in rows),
    }
    return OperationalMetrics(**values)
