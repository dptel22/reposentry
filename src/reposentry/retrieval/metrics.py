"""Small deterministic retrieval benchmark metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from .types import SearchHit


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    queries: int


def evaluate_retrieval(
    rankings: Mapping[str, Sequence[SearchHit]],
    relevant: Mapping[str, set[str] | frozenset[str]],
    *,
    k: int = 10,
) -> RetrievalMetrics:
    if k < 1:
        raise ValueError("k must be positive")
    if set(rankings) != set(relevant):
        raise ValueError("rankings and relevance judgments must have identical query IDs")
    if not rankings:
        return RetrievalMetrics(0.0, 0.0, 0.0, 0)
    recalls, reciprocal, ndcgs = [], [], []
    for query_id in sorted(rankings):
        expected = set(relevant[query_id])
        top = [hit.chunk.id for hit in rankings[query_id][:k]]
        recalls.append(len(set(top) & expected) / len(expected) if expected else 0.0)
        reciprocal.append(1.0 / (next((rank for rank, value in enumerate(top, 1) if value in expected), math.inf)))
        dcg = sum((1.0 / math.log2(rank + 1)) for rank, value in enumerate(top, 1) if value in expected)
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(expected), k) + 1))
        ndcgs.append(dcg / ideal if ideal else 0.0)
    n = len(rankings)
    return RetrievalMetrics(sum(recalls) / n, sum(reciprocal) / n, sum(ndcgs) / n, n)
