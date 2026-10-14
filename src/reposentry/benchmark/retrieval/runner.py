"""Run a fixed labeled query set and report per-query and aggregate metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from reposentry.retrieval.index import HybridIndex
from reposentry.retrieval.metrics import RetrievalMetrics, evaluate_retrieval


@dataclass(frozen=True)
class BenchmarkRow:
    query_id: str
    retrieved_ids: tuple[str, ...]
    relevant_ids: tuple[str, ...]
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float


@dataclass(frozen=True)
class RetrievalBenchmark:
    k: int
    rows: tuple[BenchmarkRow, ...]
    aggregate: RetrievalMetrics
    dense_available: bool
    degraded_reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "k": self.k,
            "queries": self.aggregate.queries,
            "recall_at_k": self.aggregate.recall_at_k,
            "mrr": self.aggregate.mrr,
            "ndcg_at_k": self.aggregate.ndcg_at_k,
            "dense_available": self.dense_available,
            "degraded_reason": self.degraded_reason,
            "rows": [
                {
                    "query_id": row.query_id,
                    "retrieved_ids": list(row.retrieved_ids),
                    "relevant_ids": list(row.relevant_ids),
                    "recall_at_k": row.recall_at_k,
                    "reciprocal_rank": row.reciprocal_rank,
                    "ndcg_at_k": row.ndcg_at_k,
                }
                for row in self.rows
            ],
        }


def run_retrieval_benchmark(
    index: HybridIndex,
    queries: Mapping[str, str],
    relevance: Mapping[str, set[str] | frozenset[str]],
    *,
    k: int = 10,
) -> RetrievalBenchmark:
    if set(queries) != set(relevance):
        raise ValueError("queries and relevance judgments must have identical IDs")
    rankings = {query_id: index.search(queries[query_id], k=k).hits for query_id in sorted(queries)}
    aggregate = evaluate_retrieval(rankings, relevance, k=k)
    rows = []
    for query_id in sorted(queries):
        result = rankings[query_id]
        relevant_ids = set(relevance[query_id])
        ids = [hit.chunk.id for hit in result[:k]]
        recall = len(set(ids) & relevant_ids) / len(relevant_ids) if relevant_ids else 0.0
        reciprocal = 1.0 / next((rank for rank, item_id in enumerate(ids, 1) if item_id in relevant_ids), float("inf"))
        dcg = sum(1.0 / math.log2(rank + 1) for rank, item_id in enumerate(ids, 1) if item_id in relevant_ids)
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant_ids), k) + 1))
        rows.append(BenchmarkRow(
            query_id, tuple(ids), tuple(sorted(relevant_ids)), recall, reciprocal,
            dcg / ideal if ideal else 0.0,
        ))
    coverage = index.coverage
    return RetrievalBenchmark(k, tuple(rows), aggregate, coverage.dense_available, coverage.reason)
