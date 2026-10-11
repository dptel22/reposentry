from __future__ import annotations

import uuid
from typing import Any, Callable, Iterator

from reposentry.observability.logging import StructuredLogger
from reposentry.observability.types import EventKind, Span, TraceEvent


class Clock:
    def time(self) -> float:
        import time

        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)


class Tracer:
    def __init__(
        self,
        run_id: str,
        logger: StructuredLogger,
        clock: Clock | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.logger = logger
        self.clock = clock or Clock()
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.events: list[TraceEvent] = []
        self._open: list[Span] = []

    def new_span_id(self) -> str:
        return self._id_factory()

    def start_span(
        self,
        name: str,
        kind: EventKind,
        *,
        model: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        span = Span(
            run_id=self.run_id,
            span_id=self.new_span_id(),
            kind=kind,
            name=name,
            start_s=self.clock.time(),
            model=model,
            attributes=dict(attributes or {}),
        )
        self._open.append(span)
        return span

    def end_span(self, span: Span, *, ok: bool, **usage: Any) -> TraceEvent:
        now = self.clock.time()
        span.ended = True
        span.ok = ok
        span.latency_ms = max(0.0, (now - span.start_s) * 1000.0)
        span.tokens_in = int(usage.get("tokens_in", span.tokens_in))
        span.tokens_out = int(usage.get("tokens_out", span.tokens_out))
        span.cost_usd = float(usage.get("cost_usd", span.cost_usd))
        if "model" in usage:
            span.model = usage["model"]
        attrs = dict(span.attributes)
        if "error_kind" in usage:
            attrs["error_kind"] = usage["error_kind"]
        event = TraceEvent(
            run_id=self.run_id,
            span_id=span.span_id,
            kind=span.kind,
            name=span.name,
            ok=ok,
            latency_ms=span.latency_ms,
            model=span.model,
            tokens_in=span.tokens_in,
            tokens_out=span.tokens_out,
            cost_usd=span.cost_usd,
            attributes=attrs,
        )
        self.events.append(event)
        self.logger.emit(event)
        return event

    def emit(
        self,
        kind: EventKind,
        name: str,
        *,
        ok: bool,
        model: str | None = None,
        attributes: dict[str, Any] | None = None,
        latency_ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> TraceEvent:
        event = TraceEvent(
            run_id=self.run_id,
            span_id=self.new_span_id(),
            kind=kind,
            name=name,
            ok=ok,
            latency_ms=latency_ms,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            attributes=dict(attributes or {}),
        )
        self.events.append(event)
        self.logger.emit(event)
        return event

    def events_of(self, kind: EventKind) -> Iterator[TraceEvent]:
        return (e for e in self.events if e.kind == kind)
