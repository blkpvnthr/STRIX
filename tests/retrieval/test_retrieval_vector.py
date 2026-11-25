"""Tests for the deterministic embedding provider + vector/hybrid retrieval (§5/§8).

The embedding provider is explicitly a DETERMINISTIC TEST provider (hash-based bag
of tokens), NOT the real BGE-M3 model (which is torch/download-gated). It exists so
the vector index, cosine similarity, and hybrid (dense + lexical) fusion can be
implemented and validated offline.
"""

from __future__ import annotations

from decimal import Decimal

from strix.retrieval.bm25 import DEFAULT_BM25_PARAMETERS
from strix.retrieval.index import Document, build_index
from strix.retrieval.vector import (
    DeterministicEmbeddingProvider,
    VectorIndex,
    cosine_similarity,
    hybrid_search,
)


def test_embedding_is_deterministic() -> None:
    p = DeterministicEmbeddingProvider()
    assert p.embed("the quick brown fox") == p.embed("the quick brown fox")


def test_embedding_is_NOT_claimed_to_be_a_real_model() -> None:
    # Guards against mislabeling test embeddings as genuine model output.
    assert DeterministicEmbeddingProvider().model_id.startswith("deterministic-test")


def test_cosine_identical_is_one_disjoint_is_zero() -> None:
    p = DeterministicEmbeddingProvider()
    a = p.embed("apple banana cherry")
    assert cosine_similarity(a, a) == Decimal(1)
    disjoint = p.embed("xylophone zeppelin")
    assert cosine_similarity(a, disjoint) == Decimal(0)


def test_vector_index_ranks_by_similarity() -> None:
    p = DeterministicEmbeddingProvider()
    idx = VectorIndex(p)
    idx.add("a", "quick brown fox")
    idx.add("b", "lazy dog sleeping")
    idx.add("c", "quick fox running")
    hits = idx.search("quick fox", limit=3)
    ids = [h.doc_id for h in hits]
    # Docs about "quick fox" match; the unrelated "lazy dog" has 0 similarity → excluded.
    assert set(ids) == {"a", "c"}
    assert hits[0].doc_id in {"a", "c"}
    assert hits[0].rank == 1


def test_vector_search_ties_broken_by_doc_id() -> None:
    p = DeterministicEmbeddingProvider()
    idx = VectorIndex(p)
    idx.add("zeta", "apple")
    idx.add("alpha", "apple")
    hits = idx.search("apple", limit=2)
    assert [h.doc_id for h in hits] == ["alpha", "zeta"]  # equal similarity → doc_id order


def test_hybrid_search_fuses_lexical_and_dense() -> None:
    corpus = (
        Document(doc_id="a", text="the quick brown fox"),
        Document(doc_id="b", text="the lazy dog"),
        Document(doc_id="c", text="quick quick fox"),
    )
    bm25 = build_index(corpus)
    provider = DeterministicEmbeddingProvider()
    vindex = VectorIndex(provider)
    for d in corpus:
        vindex.add(d.doc_id, d.text)
    fused = hybrid_search(
        "quick fox", bm25_index=bm25, bm25_params=DEFAULT_BM25_PARAMETERS,
        vector_index=vindex, limit=3,
    )
    ids = [h.doc_id for h in fused]
    # The "lazy dog" doc is least relevant to both signals.
    assert "b" not in ids[:2]
    assert set(ids) <= {"a", "b", "c"}
    assert fused[0].rank == 1
