from __future__ import annotations

import json

import pytest

from reposentry.gateway.gateway import LLMGateway
from reposentry.gateway.provider import FakeModel
from reposentry.gateway.replay import MemoryStore
from reposentry.gateway.types import GatewayConfig
from reposentry.judge import AgentConfig, BoundedAgent, ToolRejected, WorkspaceTools
from reposentry.judge.agent import _bounded_tool_result, _tool_items


def _turn(action, *, tool="none", query="", verdict=None, hypotheses=()):
    return json.dumps({
        "action": action,
        "tool_name": tool,
        "arguments": {"query": query, "symbol": "", "path": "", "route": "", "test_query": ""},
        "verdict": verdict or {
            "status": "abstain", "rationale": "", "claims": [], "abstention_reason": "not final"
        },
        "hypotheses": list(hypotheses),
    })


def _final():
    return {
        "status": "supported",
        "rationale": "The source supports the claim.",
        "claims": [{"statement": "A check is absent.", "evidence_ids": ["ev-1"]}],
        "abstention_reason": "",
    }


def test_workspace_tools_read_python_without_executing_it(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("raise RuntimeError('must not execute')\ndef check_user():\n    return lookup()\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    symbols = tools.execute("symbol_lookup", {"symbol": "check_user"})
    assert symbols["results"][0]["name"] == "check_user"
    assert tools.execute("callees", {"symbol": "check_user"})["results"][0]["name"] == "lookup"
    assert tools.execute("callers", {"symbol": "lookup"})["results"][0]["path"] == "app.py"


def test_workspace_tools_reject_unallowlisted_tool_and_extra_arguments(tmp_path):
    tools = WorkspaceTools(tmp_path)
    with pytest.raises(ToolRejected):
        tools.execute("python", {"query": "anything"})
    with pytest.raises(ToolRejected):
        tools.execute("code_search", {"query": "anything", "command": "run"})


def test_agent_runs_tool_then_returns_only_grounded_final_verdict(tmp_path):
    model = FakeModel([
        _turn("tool", tool="code_search", query="check_user"),
        _turn("final", verdict=_final()),
    ])
    gateway = LLMGateway(model, config=GatewayConfig(repair_retries=0), store=MemoryStore())
    agent = BoundedAgent(
        gateway,
        WorkspaceTools(tmp_path),
        config=AgentConfig(model="test-model", max_steps=3, max_tool_calls=1),
    )
    result = agent.investigate(
        {"id": "f1", "title": "Check authorization"},
        sections={"finding_evidence": [{"id": "ev-1", "path": "app.py", "start_line": 1, "end_line": 1, "text": "candidate"}]},
    )
    assert result.verdict.status == "supported"
    assert result.verdict.claims[0].evidence_ids == ("ev-1",)
    assert len(model.calls) == 2
    assert "untrusted data" in model.calls[0]["user_text"]


def test_agent_stops_after_configured_step_limit(tmp_path):
    model = FakeModel([_turn("tool", tool="code_search", query="x")] * 5)
    gateway = LLMGateway(model, config=GatewayConfig(repair_retries=0), store=MemoryStore())
    agent = BoundedAgent(
        gateway,
        WorkspaceTools(tmp_path),
        config=AgentConfig(model="test-model", max_steps=2, max_tool_calls=4),
    )
    result = agent.investigate({"title": "bounded"})
    assert result.verdict.status == "abstain"
    assert result.degraded_reason == "step_limit"
    assert len(model.calls) == 2


def test_agent_keeps_new_candidates_in_a_separate_hypothesis_channel(tmp_path):
    model = FakeModel([_turn(
        "final",
        verdict=_final(),
        hypotheses=[{"label": "hypothesis", "statement": "Check adjacent route", "evidence_ids": ["ev-1"]}],
    )])
    gateway = LLMGateway(model, config=GatewayConfig(repair_retries=0), store=MemoryStore())
    result = BoundedAgent(
        gateway,
        WorkspaceTools(tmp_path),
        config=AgentConfig(model="test-model"),
    ).investigate(
        {"title": "Authorization"},
        sections={"finding_evidence": [{"id": "ev-1", "path": "app.py", "start_line": 1, "end_line": 1, "text": "candidate"}]},
    )
    assert result.verdict.status == "supported"
    assert result.verdict.claims[0].statement == "A check is absent."
    assert result.hypotheses[0].label == "hypothesis"
    assert result.hypotheses[0].statement == "Check adjacent route"


def test_tool_results_are_bounded_before_becoming_agent_state():
    raw = {"results": [{"path": "app.py", "start_line": 1, "end_line": 1,
                        "text": "x" * 20_000, "source_exact": True}]}
    bounded = _bounded_tool_result(raw, 512)
    assert len(json.dumps(bounded, sort_keys=True, separators=(",", ":"))) <= 512
    assert bounded["truncated"] is True
    assert bounded["results"][0]["source_exact"] is False
    assert _tool_items("code_search", bounded) == []


def test_bounded_agent_context_does_not_mutate_original_finding(tmp_path):
    original = {"title": "A finding", "nested": {"keep": True}}
    model = FakeModel([_turn("final")])
    gateway = LLMGateway(model, config=GatewayConfig(repair_retries=0), store=MemoryStore())
    BoundedAgent(gateway, WorkspaceTools(tmp_path)).investigate(original)
    assert original == {"title": "A finding", "nested": {"keep": True}}

