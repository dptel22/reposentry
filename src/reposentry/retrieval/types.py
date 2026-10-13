"""Local retrieval records pending C0 contract integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalChunk:
    id: str
    path: str
    start_line: int
    end_line: int
    kind: str
    text: str
    citable: bool = True


@dataclass(frozen=True)
class SearchHit:
    chunk: RetrievalChunk
    score: float
    lexical_score: float = 0.0
    dense_score: float = 0.0
    ranks: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalCoverage:
    dense_available: bool
    degraded: bool
    reason: str | None = None


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    coverage: RetrievalCoverage
