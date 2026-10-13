"""Function-level lexical and optional dense retrieval (C5)."""

from .chunks import chunks_from_python
from .index import Embedder, HybridIndex, evidence_records
from .metrics import RetrievalMetrics, evaluate_retrieval
from .tokenize import identifier_tokens
from .types import RetrievalChunk, RetrievalCoverage, SearchHit, SearchResult

__all__ = [
    "Embedder",
    "HybridIndex",
    "RetrievalChunk",
    "RetrievalCoverage",
    "RetrievalMetrics",
    "SearchHit",
    "SearchResult",
    "chunks_from_python",
    "evaluate_retrieval",
    "evidence_records",
    "identifier_tokens",
]
