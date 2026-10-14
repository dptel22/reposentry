from __future__ import annotations

import io

from reposentry.gateway.errors import TimeoutProviderError
from reposentry.gateway.gateway import LLMGateway
from reposentry.gateway.provider import FakeModel
from reposentry.gateway.replay import MemoryStore
from reposentry.gateway.types import GatewayConfig
from reposentry.judge import AgentConfig, BoundedAgent
from reposentry.observability import (
    EventKind,
    StructuredLogger,
    Tracer,
    aggregate_metrics,
    health_check,
    readiness_check,
)


def _tracer():
    return Tracer("run", StructuredLogger(io.StringIO()), id_factory=lambda: "span")


def test_timeout_and_validation_events_are_distinguishable():
    tracer = _tracer()
    timeout_gateway = LLMGateway(
        FakeModel([TimeoutProviderError("deadline")]),
        config=GatewayConfig(transient_retries=0),
        store=MemoryStore(),
        tracer=tracer,
        fallback=lambda: {"verdict": "abstain"},
    )
    timeout_gateway.call(_request())
    invalid_gateway = LLMGateway(
        FakeModel(["not json"]),
        config=GatewayConfig(repair_retries=0),
        store=MemoryStore(),
        tracer=tracer,
        fallback=lambda: {"verdict": "abstain"},
    )
    invalid_gateway.call(_request())
    metrics = aggregate_metrics(tracer.events)
    assert metrics.provider_timeouts == 1
    assert metrics.validation_rejections == 1
    assert metrics.model_calls == 2


def test_tool_rejection_appears_in_metrics():
    tracer = _tracer()
    payload = (
        '{"action":"tool","tool_name":"none",'
        '"arguments":{"query":"","symbol":"","path":"","route":"","test_query":""},'
        '"verdict":{"status":"abstain","rationale":"","claims":[],"abstention_reason":"not final"}}'
    )
    gateway = LLMGateway(FakeModel([payload]), store=MemoryStore(), tracer=tracer)
    result = BoundedAgent(
        gateway,
        object(),
        config=AgentConfig(model="fake", max_steps=1),
    ).investigate({})
    assert result.degraded_reason == "step_limit"
    assert aggregate_metrics(tracer.events).tool_rejections == 1
    assert any(event.kind is EventKind.TOOL_REJECTION for event in tracer.events)


def test_health_and_readiness_are_deterministic():
    assert health_check().as_dict() == {"live": True, "ready": True, "checks": {}}
    report = readiness_check({"gateway": True, "recordings": False})
    assert report.live and not report.ready
    assert list(report.checks) == ["gateway", "recordings"]


def _request():
    from reposentry.gateway.types import ModelRequest

    return ModelRequest(
        model="fake",
        prompt_version="test",
        bundle={"finding": "x"},
        schema={"type": "object", "required": ["verdict"], "additionalProperties": False,
                "properties": {"verdict": {"type": "string"}}},
    )

