"""Shared fixtures for the C6 LLM gateway test suites.

Everything runs fully offline: the only provider is the scripted FakeModel,
which never touches the network (verified by construction in the suites and
explicitly by the socket-blocking fixture below).
"""

from __future__ import annotations

import io
import json
import socket
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reposentry.gateway.provider import FakeModel  # noqa: E402
from reposentry.observability.logging import StructuredLogger  # noqa: E402
from reposentry.observability.tracer import Clock, Tracer  # noqa: E402

SECRET = "sk-abcdef1234567890"

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["verdict"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["safe", "vulnerable"]},
        "score": {"type": "integer"},
        "notes": {"type": "string", "maxLength": 10},
        "items": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["id"],
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}},
            },
        },
    },
}


def verdict_payload(**overrides) -> str:
    data = {"verdict": "safe"}
    data.update(overrides)
    return json.dumps(data)


class FakeClock(Clock):
    """Clock that records sleeps instead of actually sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class BlockingSocket(socket.socket):  # pragma: no cover - never instantiated
    def __init__(self, *args, **kwargs):
        raise AssertionError("network socket created during offline gateway test")


@pytest.fixture
def no_network(monkeypatch):
    """Assert-by-construction offline guarantee: any socket creation fails."""
    monkeypatch.setattr(socket, "socket", BlockingSocket)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network use")))
    return True


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def tracer():
    logger = StructuredLogger(io.StringIO())
    return Tracer(run_id="test-run", logger=logger, clock=FakeClock(), id_factory=lambda: "span-%d" % len(logger.records))


__all__ = ["FakeModel", "FakeClock", "VERDICT_SCHEMA", "verdict_payload", "SECRET"]
