"""Provider-agnostic model interface plus a scripted fake for tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from reposentry.gateway.errors import PermanentProviderError


@dataclass(frozen=True)
class ProviderResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class ModelProvider(Protocol):
    name: str

    def complete(self, *, model: str, system: str | None, user_text: str, timeout_s: float) -> ProviderResult:
        ...


class FakeModel:
    """Scripted model: yields texts or raises scripted exceptions, in order.

    A script entry is either a str (the raw output), a ProviderResult, or an
    Exception instance to raise. Exhausting the script raises ScriptExhausted,
    which is a permanent provider error (tests must script every call they
    expect). The scrubbed user_text is recorded for assertions.
    """

    def __init__(self, script: list[Any] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []
        self.name = "fake"

    def complete(self, *, model: str, system: str | None, user_text: str, timeout_s: float) -> ProviderResult:
        self.calls.append({"model": model, "system": system, "user_text": user_text, "timeout_s": timeout_s})
        if not self.script:
            raise ScriptExhausted(f"no scripted response for call {len(self.calls)}")
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, ProviderResult):
            return entry
        return ProviderResult(text=str(entry), tokens_in=10, tokens_out=10)


class ScriptExhausted(PermanentProviderError):
    kind = "script_exhausted"
