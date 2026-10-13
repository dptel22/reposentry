from __future__ import annotations

from types import SimpleNamespace

import pytest

from reposentry.benchmark.arms import ArmAdapter, ArmCallbacks, ArmConfig, get_arm
from reposentry.judge import ProposedHypothesis


def test_arm_configs_are_cumulative_and_retrieval_is_only_enabled_for_c():
    a, b, c, d, e = (get_arm(name) for name in "ABCDE")
    assert not a.use_judge
    assert b.use_judge and not b.use_retrieval
    assert c.use_judge and c.use_retrieval and not c.use_verifier
    assert d.use_judge and d.use_retrieval and d.use_verifier and not d.use_agent
    assert e.use_agent and e.allow_hypotheses and e.use_verifier


def test_c_arm_retrieval_is_passed_into_the_judge_and_candidates_are_sorted():
    calls = []
    callbacks = ArmCallbacks(
        retrieve=lambda candidate: (f"retrieval:{candidate['id']}",),
        judge=lambda candidate, retrieved: calls.append((candidate["id"], retrieved)) or "judgment",
    )
    result = ArmAdapter(get_arm("C")).run([{"id": "b"}, {"id": "a"}], callbacks)
    assert [item.candidate_id for item in result.executions] == ["a", "b"]
    assert calls == [("a", ("retrieval:a",)), ("b", ("retrieval:b",))]


def test_e_arm_runs_verifier_and_keeps_hypotheses_outside_findings():
    proposed = ProposedHypothesis("Check neighboring route")
    verified = []
    result = ArmAdapter(get_arm("E")).run(
        [{"id": "candidate"}],
        ArmCallbacks(
            retrieve=lambda candidate: ("context",),
            agent=lambda candidate, evidence: SimpleNamespace(hypotheses=(proposed,)),
            verify=lambda judgment: verified.append(judgment) or "verified",
        ),
    )
    assert result.proposed_hypotheses == (proposed,)
    assert result.executions[0].judgment.hypotheses == (proposed,)
    assert result.executions[0].verification == "verified"
    assert verified == [result.executions[0].judgment]


def test_arm_rejects_missing_callbacks_and_duplicate_candidate_ids():
    with pytest.raises(ValueError, match="retrieval callback"):
        ArmAdapter(get_arm("C")).run([{"id": "a"}], ArmCallbacks(judge=lambda *_: None))
    with pytest.raises(ValueError, match="unique"):
        ArmAdapter(get_arm("A")).run([{"id": "a"}, {"id": "a"}], ArmCallbacks())
    with pytest.raises(ValueError, match="retrieval arm"):
        ArmConfig("invalid", use_retrieval=True)
