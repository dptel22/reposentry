"""BM25 lexical search with optional exact dense cosine and RRF fusion."""

from __future__ import annotations

import math
from collections import Counter
from typing import Protocol, Sequence

from .tokenize import identifier_tokens
from .types import RetrievalChunk, RetrievalCoverage, SearchHit, SearchResult


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
    def embed_query(self, text: str) -> Sequence[float]: ...


class HybridIndex:
    def __init__(self, *, embedder: Embedder | None = None, rrf_constant: int = 60) -> None:
        if rrf_constant < 1:
            raise ValueError("RRF constant must be positive")
        self.embedder = embedder
        self.rrf_constant = rrf_constant
        self.chunks: tuple[RetrievalChunk, ...] = ()
        self._tokens: dict[str, tuple[str, ...]] = {}
        self._term_freq: dict[str, Counter[str]] = {}
        self._doc_freq: Counter[str] = Counter()
        self._postings: dict[str, list[tuple[str, int]]] = {}
        self._lengths: dict[str, int] = {}
        self._chunk_by_id: dict[str, RetrievalChunk] = {}
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._dense_reason: str | None = "embedder_unavailable" if embedder is None else None

    @property
    def coverage(self) -> RetrievalCoverage:
        available = self.embedder is not None and self._dense_reason is None and bool(self.chunks)
        reason = self._dense_reason
        if self.embedder is not None and not self.chunks:
            reason = "empty_index"
        return RetrievalCoverage(dense_available=available, degraded=not available, reason=reason)

    def build(self, chunks: Sequence[RetrievalChunk]) -> None:
        ordered = tuple(sorted(chunks, key=lambda c: (c.path, c.start_line, c.end_line, c.id)))
        if len({chunk.id for chunk in ordered}) != len(ordered):
            raise ValueError("chunk IDs must be unique")
        self.chunks = ordered
        self._tokens = {chunk.id: identifier_tokens(chunk.text) for chunk in ordered}
        self._term_freq = {chunk.id: Counter(self._tokens[chunk.id]) for chunk in ordered}
        self._doc_freq = Counter()
        self._postings = {}
        for terms in self._term_freq.values():
            self._doc_freq.update(terms.keys())
        for chunk_id, terms in self._term_freq.items():
            for token, frequency in terms.items():
                self._postings.setdefault(token, []).append((chunk_id, frequency))
        self._lengths = {chunk.id: len(self._tokens[chunk.id]) for chunk in ordered}
        self._chunk_by_id = {chunk.id: chunk for chunk in ordered}
        self._vectors = {}
        self._dense_reason = "embedder_unavailable" if self.embedder is None else None
        if self.embedder is None or not ordered:
            return
        try:
            vectors = self.embedder.embed_documents([chunk.text for chunk in ordered])
            normalized = [_valid_vector(vector) for vector in vectors]
            if len(normalized) != len(ordered) or any(vector is None for vector in normalized):
                raise ValueError("invalid embedding output")
            dims = {len(vector) for vector in normalized if vector is not None}
            if len(dims) != 1:
                raise ValueError("embedding dimensions differ")
            self._vectors = {chunk.id: vector for chunk, vector in zip(ordered, normalized) if vector is not None}
        except Exception:
            self._vectors = {}
            self._dense_reason = "embedding_unavailable"

    def search(self, query: str, *, k: int = 10) -> SearchResult:
        if k < 1:
            raise ValueError("k must be positive")
        if not query.strip() or not self.chunks:
            return SearchResult((), self.coverage)
        lexical = self._lexical_scores(identifier_tokens(query))
        lexical_order = sorted(
            ((score, chunk_id) for chunk_id, score in lexical.items() if score > 0.0),
            key=lambda pair: (-pair[0], *_chunk_sort(self._chunk(pair[1]))),
        )
        dense: list[tuple[float, str]] = []
        if self.embedder is not None and self._vectors and self._dense_reason is None:
            try:
                query_vector = _valid_vector(self.embedder.embed_query(query))
                if query_vector is None or len(query_vector) != len(next(iter(self._vectors.values()))):
                    raise ValueError("invalid query embedding")
                dense = sorted(
                    (( _cosine(query_vector, vector), chunk_id) for chunk_id, vector in self._vectors.items()),
                    key=lambda pair: (-pair[0], *_chunk_sort(self._chunk(pair[1]))),
                )
                dense = [pair for pair in dense if pair[0] > 0.0]
            except Exception:
                self._dense_reason = "embedding_unavailable"
                dense = []
        ranks: dict[str, list[str]] = {}
        if lexical_order:
            ranks["lexical"] = [chunk_id for _, chunk_id in lexical_order]
        if dense:
            ranks["dense"] = [chunk_id for _, chunk_id in dense]
        fused: dict[str, float] = {}
        for channel, ordered_ids in ranks.items():
            for rank, chunk_id in enumerate(ordered_ids, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.rrf_constant + rank)
        dense_scores = dict(dense)
        selected = sorted(fused, key=lambda chunk_id: (-fused[chunk_id], *_chunk_sort(self._chunk(chunk_id))) )[:k]
        hits = tuple(
            SearchHit(
                self._chunk(chunk_id),
                fused[chunk_id],
                lexical.get(chunk_id, 0.0),
                dense_scores.get(chunk_id, 0.0),
                tuple(channel for channel in ("lexical", "dense") if chunk_id in ranks.get(channel, ())),
            )
            for chunk_id in selected
        )
        return SearchResult(hits, self.coverage)

    def _lexical_scores(self, query_tokens: Sequence[str]) -> dict[str, float]:
        if not query_tokens:
            return {}
        n_docs = len(self.chunks)
        avgdl = sum(self._lengths.values()) / n_docs if n_docs else 0.0
        result: dict[str, float] = {}
        for token in query_tokens:
            df = self._doc_freq.get(token, 0)
            if not df:
                continue
            idf = math.log1p((n_docs - df + 0.5) / (df + 0.5))
            for chunk_id, tf in self._postings[token]:
                length = self._lengths[chunk_id]
                denom = tf + 1.5 * (1.0 - 0.75 + 0.75 * length / max(avgdl, 1.0))
                result[chunk_id] = result.get(chunk_id, 0.0) + idf * tf * 2.5 / denom
        return result

    def _chunk(self, chunk_id: str) -> RetrievalChunk:
        return self._chunk_by_id[chunk_id]


def _valid_vector(vector: Sequence[float]) -> tuple[float, ...] | None:
    try:
        result = tuple(float(value) for value in vector)
    except (TypeError, ValueError):
        return None
    if not result or any(not math.isfinite(value) for value in result):
        return None
    norm = math.sqrt(sum(value * value for value in result))
    if norm == 0:
        return None
    return tuple(value / norm for value in result)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _chunk_sort(chunk: RetrievalChunk) -> tuple[str, int, int, str]:
    return chunk.path, chunk.start_line, chunk.end_line, chunk.id


def evidence_records(hits: Sequence[SearchHit]) -> tuple[dict[str, object], ...]:
    """Map exact-provenance retrieval hits to C7 evidence section records."""
    return tuple(
        {
            "id": hit.chunk.id,
            "path": hit.chunk.path,
            "start_line": hit.chunk.start_line,
            "end_line": hit.chunk.end_line,
            "text": hit.chunk.text,
            "retrieval_score": hit.score,
        }
        for hit in hits
        if hit.chunk.citable
    )
