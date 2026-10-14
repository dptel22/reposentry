from __future__ import annotations

import pytest
import math

from reposentry.retrieval import (
    HybridIndex,
    RetrievalChunk,
    SearchHit,
    chunks_from_python,
    evidence_records,
    evaluate_retrieval,
    identifier_tokens,
)


def _chunk(chunk_id: str, path: str, text: str, line: int = 1) -> RetrievalChunk:
    return RetrievalChunk(chunk_id, path, line, line, "function", text)


def test_identifier_tokens_split_snake_and_camel_case_but_keep_identifiers():
    tokens = identifier_tokens("getUserId user_id HTTPRequest")
    assert "getuserid" in tokens
    assert {"get", "user", "id", "user_id", "httprequest", "http", "request"} <= set(tokens)


def test_function_chunks_preserve_ast_ranges_and_module_blocks():
    source = "import os\n\n@app.route('/x')\ndef fetchUser():\n    return os.getenv('X')\n"
    chunks = chunks_from_python({"app.py": source})
    func = next(chunk for chunk in chunks if chunk.kind == "function")
    module = next(chunk for chunk in chunks if chunk.kind == "module")
    assert (func.start_line, func.end_line) == (3, 5)
    assert func.text == "@app.route('/x')\ndef fetchUser():\n    return os.getenv('X')"
    assert module.start_line == module.end_line == 1
    assert module.text == "import os"


def test_chunks_reject_unsafe_paths_and_split_oversized_lines():
    chunks = chunks_from_python(
        {"../escape.py": "secret", "C:/outside.py": "outside", "ok.py": "x" * 25},
        max_chunk_chars=8,
    )
    assert all(chunk.path == "ok.py" for chunk in chunks)
    assert [chunk.text for chunk in chunks] == ["x" * 8, "x" * 8, "x" * 8, "x"]
    assert all((chunk.start_line, chunk.end_line) == (1, 1) for chunk in chunks)
    assert not evidence_records([SearchHit(chunks[0], 1.0)])


def test_lexical_index_excludes_zero_score_chunks_and_is_deterministic():
    chunks = [_chunk("a", "a.py", "getUserId checks access"), _chunk("b", "b.py", "unrelated words")]
    index = HybridIndex()
    index.build(chunks)
    one = index.search("get_user_id", k=10)
    two = index.search("get_user_id", k=10)
    assert one == two
    assert [hit.chunk.id for hit in one.hits] == ["a"]
    assert one.coverage.degraded and one.coverage.reason == "embedder_unavailable"


def test_dense_hits_fuse_with_lexical_and_can_retrieve_without_token_overlap():
    class StubEmbedder:
        def embed_documents(self, texts):
            return [[1, 0] if text == "apple" else [0, 1] for text in texts]

        def embed_query(self, text):
            return [0, 1]

    index = HybridIndex(embedder=StubEmbedder())
    index.build([_chunk("a", "a.py", "apple"), _chunk("b", "b.py", "banana")])
    result = index.search("unrelated query")
    assert [hit.chunk.id for hit in result.hits] == ["b"]
    assert result.hits[0].ranks == ("dense",)
    assert result.coverage.dense_available and not result.coverage.degraded


def test_embedder_failure_degrades_to_lexical_results():
    class BrokenEmbedder:
        def embed_documents(self, texts):
            raise RuntimeError("offline")

        def embed_query(self, text):
            raise RuntimeError("offline")

    index = HybridIndex(embedder=BrokenEmbedder())
    index.build([_chunk("a", "a.py", "check authorization")])
    result = index.search("authorization")
    assert [hit.chunk.id for hit in result.hits] == ["a"]
    assert result.coverage.degraded and result.coverage.reason == "embedding_unavailable"


def test_retrieval_metrics_match_hand_computed_tiny_example():
    hit_a = SearchHit(_chunk("a", "a.py", "a"), 1.0)
    hit_b = SearchHit(_chunk("b", "b.py", "b"), 0.5)
    scores = evaluate_retrieval(
        {"q1": [hit_b, hit_a]},
        {"q1": {"a"}},
        k=2,
    )
    assert scores.recall_at_k == 1.0
    assert scores.mrr == 0.5
    assert scores.ndcg_at_k == pytest.approx(1.0 / math.log2(3))


def test_retrieval_metrics_require_matching_query_sets():
    with pytest.raises(ValueError, match="identical"):
        evaluate_retrieval({}, {"missing": {"chunk"}})

