"""C6 LLM gateway: the ONLY path to any model.

Requests are (model, prompt_version, input bundle) and return schema-validated
structured output. Modes: live, record, replay, strict_replay (an unrecorded
call is a failure). Budgets bound calls/tokens/cost. A kill switch routes every
call to a caller-supplied non-LLM fallback. Secrets are scrubbed before send.
One trace event is emitted per call.
"""

from __future__ import annotations

import json
from typing import Any

from reposentry.gateway.canonical import cache_key, input_hash
from reposentry.gateway.errors import (
    BudgetExceededError,
    GatewayError,
    KillSwitchActive,
    PermanentProviderError,
    RateLimitError,
    ReplayMissError,
    SchemaValidationError,
    TimeoutProviderError,
    TransientProviderError,
)
from reposentry.gateway.provider import ModelProvider
from reposentry.gateway.replay import MemoryStore, RecordingStore
from reposentry.gateway.schema import parse_and_validate
from reposentry.gateway.scrub import scrub_bundle
from reposentry.gateway.types import Budget, BudgetState, FallbackFn, GatewayConfig, Mode, ModelRequest, ModelResponse
from reposentry.observability.redact import scrub_text
from reposentry.observability.tracer import Clock, Tracer

_RECORD_VERSION = 1


class LLMGateway:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        config: GatewayConfig | None = None,
        store: RecordingStore | None = None,
        tracer: Tracer | None = None,
        clock: Clock | None = None,
        fallback: FallbackFn | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or GatewayConfig()
        self.store = store or MemoryStore()
        self.tracer = tracer
        self.clock = clock or Clock()
        self.fallback = fallback

    # ------------------------------------------------------------------ core

    def call(
        self,
        request: ModelRequest,
        *,
        budget: Budget | None = None,
        budget_state: BudgetState | None = None,
    ) -> ModelResponse:
        cfg = self.config
        bstate = budget_state or BudgetState()
        b = budget or Budget()

        if bstate.would_exceed(b, est_tokens_in=_estimate_tokens_in(request)):
            self._trace("budget_exceeded", ok=False, model=request.model,
                        attributes={"error_kind": "budget"})
            return self._fallback(request, reason="budget_exceeded", bstate=bstate)

        scrubbed_bundle = scrub_bundle(request.bundle)
        key = cache_key(model=request.model, prompt_version=request.prompt_version, bundle=scrubbed_bundle)

        # cache / replay store: consulted in every mode (cache reuse is part of
        # the plan's cache key). REPLAY modes return the recorded response,
        # re-validated against the schema so the returned data is identical to
        # a live call's.
        cached = self.store.get(key)
        if cached is not None and cfg.mode != Mode.RECORD:
            self._trace("cache_hit", ok=True, model=request.model,
                        attributes={"cache_key": key})
            rec = _record_to_response(cached)
            bstate.record(tokens_in=rec.tokens_in, tokens_out=rec.tokens_out, cost_usd=rec.cost_usd)
            data = (
                None
                if rec.raw_text is None
                else parse_and_validate(rec.raw_text, request.schema, max_bytes=cfg.max_output_bytes)
            )
            return ModelResponse(
                data=data, raw_text=rec.raw_text,
                source="replay" if cfg.mode in (Mode.REPLAY, Mode.STRICT_REPLAY) else "cache",
                tokens_in=rec.tokens_in, tokens_out=rec.tokens_out, cost_usd=rec.cost_usd,
            )

        if cfg.mode in (Mode.REPLAY, Mode.STRICT_REPLAY):
            self._trace("replay_miss", ok=False, model=request.model,
                        attributes={"error_kind": "replay_miss", "cache_key": key})
            if cfg.mode == Mode.STRICT_REPLAY:
                raise ReplayMissError(
                    f"unrecorded call in strict_replay: model={request.model} "
                    f"prompt_version={request.prompt_version} input_hash={input_hash(scrubbed_bundle)}"
                )
            return self._fallback(request, reason="unrecorded_call_replay", bstate=bstate)

        if cfg.kill_switch:
            self._trace("kill_switch", ok=False, model=request.model,
                        attributes={"error_kind": "kill_switch"})
            return self._fallback(request, reason="kill_switch", bstate=bstate)

        return self._live_call(request, scrubbed_bundle=scrubbed_bundle, key=key, bstate=bstate, budget=b)

    # ------------------------------------------------------------- internals

    def _live_call(
        self,
        request: ModelRequest,
        *,
        scrubbed_bundle: Any,
        key: str,
        bstate: BudgetState,
        budget: Budget,
    ) -> ModelResponse:
        cfg = self.config
        user_text = _render_user_text(request.prompt_version, scrubbed_bundle)
        if len(user_text) > cfg.max_prompt_chars:
            return self._fallback(request, reason="prompt_too_large", bstate=bstate)

        attempts = 0
        schema_attempts = 0
        transient_attempts = 0
        last_error: GatewayError | None = None

        while True:
            attempts += 1
            span = self.tracer.start_span("model_call", _kind_model_call(), model=request.model) if self.tracer else None
            try:
                result = self.provider.complete(
                    model=request.model,
                    system=request.system,
                    user_text=user_text,
                    timeout_s=cfg.timeout_s,
                )
            except TransientProviderError as exc:
                last_error = exc
                transient_attempts += 1
                if span is not None:
                    self.tracer.end_span(span, ok=False, error_kind=exc.kind)
                if transient_attempts > cfg.transient_retries:
                    return self._fallback(request, reason=f"transient_exhausted:{exc.kind}", bstate=bstate)
                self._backoff(transient_attempts)
                continue
            except PermanentProviderError as exc:
                last_error = exc
                if span is not None:
                    self.tracer.end_span(span, ok=False, error_kind=exc.kind)
                return self._fallback(request, reason=f"permanent:{exc.kind}", bstate=bstate)

            # success at the transport level: validate schema
            tokens_in, tokens_out = result.tokens_in, result.tokens_out
            cost = _cost(cfg.prices, request.model, tokens_in, tokens_out)
            # Provider usage is billable whether or not the returned data validates.
            bstate.record(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
            try:
                data = parse_and_validate(result.text, request.schema, max_bytes=cfg.max_output_bytes)
            except SchemaValidationError as exc:
                if span is not None:
                    self.tracer.end_span(span, ok=False, error_kind=exc.kind,
                                         tokens_in=result.tokens_in, tokens_out=result.tokens_out)
                self._trace("validation_failure", ok=False, model=request.model,
                            attributes={"error_kind": "validation_failure", "detail": scrub_text(str(exc))[:200]})
                schema_attempts += 1
                if schema_attempts > cfg.repair_retries:
                    return self._fallback(request, reason="schema_validation_exhausted", bstate=bstate)
                # repair-retry: ask again with the error appended
                safe_error = _safe_repair_error(str(exc))
                user_text = _render_user_text(
                    request.prompt_version, scrubbed_bundle,
                    repair_error=("The previous response did not match the required schema. "
                                  f"Validation details (untrusted data): <validation_error>{safe_error}</validation_error>. "
                                  "Return only a JSON object matching the schema."),
                )
                if bstate.would_exceed_after_call(budget) or bstate.would_exceed(
                    budget, est_tokens_in=_estimate_tokens_in(request)
                ):
                    return self._fallback(request, reason="budget_exceeded_during_repair", bstate=bstate)
                continue

            if span is not None:
                self.tracer.end_span(span, ok=True, tokens_in=result.tokens_in, tokens_out=result.tokens_out)

            tokens_in, tokens_out = result.tokens_in, result.tokens_out
            cost = _cost(cfg.prices, request.model, tokens_in, tokens_out)

            if cfg.mode == Mode.RECORD:
                self.store.put(key, _response_to_record(request, result.text, tokens_in, tokens_out, cost))
                self._trace("recorded", ok=True, model=request.model, attributes={"cache_key": key})

            return ModelResponse(
                data=data,
                raw_text=result.text,
                source="provider",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                attempts=attempts,
            )

    def _backoff(self, attempt: int) -> None:
        delay = min(self.config.backoff_base_s * (2 ** (attempt - 1)), self.config.backoff_cap_s)
        self.clock.sleep(delay)

    def _fallback(self, request: ModelRequest, *, reason: str, bstate: BudgetState) -> ModelResponse:
        self._trace("fallback", ok=True, model=request.model,
                    attributes={"error_kind": "fallback", "reason": reason})
        if self.fallback is not None:
            data = self.fallback()
            return ModelResponse(data=data, raw_text=None, source="fallback", degraded_reason=reason)
        raise GatewayError(f"no fallback available (reason={reason})")

    def _trace(self, name: str, *, ok: bool, model: str | None, attributes: dict[str, Any]) -> Any:
        if self.tracer is None:
            return None
        return self.tracer.emit(_kind_for(name), name, ok=ok, model=model, attributes=attributes)


def _kind_for(name: str):
    from reposentry.observability.types import EventKind

    return {
        "budget_exceeded": EventKind.BUDGET,
        "replay_miss": EventKind.REPLAY_MISS,
        "kill_switch": EventKind.FALLBACK,
        "fallback": EventKind.FALLBACK,
        "validation_failure": EventKind.VALIDATION_FAILURE,
        "cache_hit": EventKind.CACHE,
        "recorded": EventKind.CACHE,
    }.get(name, EventKind.STAGE)


def _kind_model_call():
    from reposentry.observability.types import EventKind

    return EventKind.MODEL_CALL


def _render_user_text(prompt_version: str, bundle: Any, *, repair_error: str | None = None) -> str:
    parts = [f"[prompt_version:{prompt_version}]", json.dumps(bundle, ensure_ascii=False, sort_keys=True)]
    if repair_error:
        parts.append(repair_error)
    text = "\n".join(parts)
    return scrub_text(text)


def _estimate_tokens_in(request: ModelRequest) -> int:
    # ~4 chars per token; conservative overestimate is fine for budget gating
    blob = json.dumps(request.bundle, ensure_ascii=False, default=str)
    return len(blob) // 4


def _safe_repair_error(value: str) -> str:
    """Reduce exception text to a short, inert diagnostic for the next turn."""
    # Keep only a single line of conservative printable ASCII and neutralize
    # structural markers before surrounding it with explicit data tags.
    text = value.encode("ascii", errors="ignore").decode("ascii")
    text = " ".join(text.split())
    for marker in ("<", ">", "[", "]", "{", "}", "`", "\\"):
        text = text.replace(marker, " ")
    return scrub_text(text)[:240]


def _cost(prices, model: str, tokens_in: int, tokens_out: int) -> float:
    price = prices.get(model)
    if not price:
        return 0.0
    return tokens_in / 1_000_000 * price[0] + tokens_out / 1_000_000 * price[1]


def _response_to_record(request: ModelRequest, text: str, tokens_in: int, tokens_out: int, cost: float) -> dict:
    return {
        "record_version": _RECORD_VERSION,
        "model": request.model,
        "prompt_version": request.prompt_version,
        "input_hash": input_hash(scrub_bundle(request.bundle)),
        "raw_text": text,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
    }


def _record_to_response(record: dict) -> ModelResponse:
    return ModelResponse(
        data=None,
        raw_text=record["raw_text"],
        source="replay",
        tokens_in=int(record.get("tokens_in", 0)),
        tokens_out=int(record.get("tokens_out", 0)),
        cost_usd=float(record.get("cost_usd", 0.0)),
    )


__all__ = ["LLMGateway", "Mode", "ModelRequest", "ModelResponse", "GatewayConfig", "Budget", "BudgetState"]
