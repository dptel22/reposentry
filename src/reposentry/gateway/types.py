from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class Mode(str, Enum):
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"
    STRICT_REPLAY = "strict_replay"


@dataclass(frozen=True)
class GatewayConfig:
    mode: Mode = Mode.LIVE
    timeout_s: float = 30.0
    repair_retries: int = 2
    transient_retries: int = 3
    backoff_base_s: float = 0.05
    backoff_cap_s: float = 5.0
    max_output_bytes: int = 262144
    max_prompt_chars: int = 200_000
    # per-1M-token prices per model; cost is 0 when unknown
    prices: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    kill_switch: bool = False


@dataclass(frozen=True)
class Budget:
    """Bounded resource envelope. None means unbounded for that axis."""

    max_calls: int | None = None
    max_tokens_in: int | None = None
    max_tokens_out: int | None = None
    max_cost_usd: float | None = None


@dataclass
class BudgetState:
    spent_calls = 0
    spent_tokens_in = 0
    spent_tokens_out = 0
    spent_cost_usd = 0.0

    def would_exceed(self, budget: Budget, *, est_tokens_in: int = 0) -> bool:
        return (
            (budget.max_calls is not None and self.spent_calls >= budget.max_calls)
            or (budget.max_tokens_in is not None and self.spent_tokens_in + est_tokens_in > budget.max_tokens_in)
            or (budget.max_tokens_out is not None and self.spent_tokens_out >= budget.max_tokens_out)
            or (budget.max_cost_usd is not None and self.spent_cost_usd >= budget.max_cost_usd)
        )

    def record(self, *, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        self.spent_calls += 1
        self.spent_tokens_in += tokens_in
        self.spent_tokens_out += tokens_out
        self.spent_cost_usd += cost_usd


@dataclass(frozen=True)
class ModelRequest:
    model: str
    prompt_version: str
    bundle: Any  # untrusted, JSON-serializable input data
    schema: dict[str, Any]
    system: str | None = None
    max_output_bytes: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    data: dict[str, Any] | None  # None when the fallback produced the answer
    raw_text: str | None
    source: str  # provider | cache | replay | fallback
    degraded_reason: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    attempts: int = 0

    @property
    def used_fallback(self) -> bool:
        return self.source == "fallback"


FallbackFn = Callable[[], dict[str, Any]]
