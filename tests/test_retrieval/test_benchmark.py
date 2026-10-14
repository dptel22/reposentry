from __future__ import annotations

import pytest

from reposentry.benchmark.retrieval import run_retrieval_benchmark
from reposentry.retrieval import HybridIndex, RetrievalChunk


def test_benchmark_emits_deterministic_recall_mrr_ndcg_and_degradation():
    index = HybridIndex()
    index.build([
        RetrievalChunk("a", "a.py", 1, 2, "function", "check authorization"),
        RetrievalChunk("b", "b.py", 1, 2, "function", "unrelated helper"),
    ])
    report = run_retrieval_benchmark(
        index,
        {"q1": "authorization", "q2": "helper"},
        {"q1": {"a"}, "q2": {"b"}},
        k=2,
    )
    assert report.aggregate.recall_at_k == 1.0
    assert report.aggregate.mrr == 1.0
    assert report.aggregate.ndcg_at_k == 1.0
    assert report.dense_available is False
    assert report.degraded_reason == "embedder_unavailable"
    assert report.as_dict()["rows"][0]["query_id"] == "q1"


def test_benchmark_rejects_mismatched_query_labels():
    with pytest.raises(ValueError, match="identical"):
        run_retrieval_benchmark(HybridIndex(), {"q1": "x"}, {"q2": {"x"}})
