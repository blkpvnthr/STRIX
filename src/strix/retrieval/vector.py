"""Deterministic embeddings + pure-Python vector & hybrid retrieval (§5/§8).

:class:`DeterministicEmbeddingProvider` is a hash-based bag-of-tokens embedder — a
DETERMINISTIC TEST provider, explicitly NOT the real BGE-M3 model (which is
torch/download-gated). Its ``model_id`` is prefixed ``deterministic-test`` so its
output is never mistaken for genuine model embeddings. It lets the vector index,
exact-Decimal cosine similarity, and hybrid (dense + lexical BM25) fusion be built
and validated offline; a real embedding provider can implement the same interface.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal, localcontext

from strix.models import DecimalValue, StrixModel
from strix.research.normalize import tokenize
from strix.retrieval._precision import RETRIEVAL_PRECISION, RETRIEVAL_ROUNDING
from strix.retrieval.bm25 import BM25Parameters
from strix.retrieval.bm25 import search as bm25_search
from strix.retrieval.fusion import DEFAULT_RRF_K, FusedHit, reciprocal_rank_fusion
from strix.retrieval.index import InvertedIndex

#: A sparse term-frequency vector: dimension index -> integer weight.
SparseVector = Mapping[int, int]


class DeterministicEmbeddingProvider:
    """Hash-based bag-of-tokens embeddings (deterministic; NOT a learned model)."""

    def __init__(self, *, dimensions: int = 256) -> None:
        self._dimensions = dimensions
        self.model_id = f"deterministic-test-bow@{dimensions}"

    def embed(self, text: str) -> dict[int, int]:
        """A sparse, deterministic embedding of ``text`` (hashing vectorizer)."""
        vector: dict[int, int] = {}
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
            idx = int(digest, 16) % self._dimensions
            vector[idx] = vector.get(idx, 0) + 1
        return vector


def cosine_similarity(a: SparseVector, b: SparseVector) -> Decimal:
    """Exact-Decimal cosine similarity of two sparse vectors (0 if either is empty).

    Identical vectors yield exactly ``1`` and disjoint vectors exactly ``0`` because
    the denominator is ``sqrt(normsq_a * normsq_b)`` over integer norms-squared (a
    perfect square for identical inputs).
    """
    if not a or not b:
        return Decimal(0)
    dot = sum(a[k] * b[k] for k in a.keys() & b.keys())
    if dot == 0:
        return Decimal(0)
    normsq_a = sum(v * v for v in a.values())
    normsq_b = sum(v * v for v in b.values())
    with localcontext() as ctx:
        ctx.prec = RETRIEVAL_PRECISION
        ctx.rounding = RETRIEVAL_ROUNDING
        denom = (Decimal(normsq_a) * Decimal(normsq_b)).sqrt()
        return Decimal(dot) / denom


class VectorHit(StrixModel):
    """One vector-search hit: a document, its cosine score, and 1-based rank."""

    doc_id: str
    score: DecimalValue
    rank: int


class VectorIndex:
    """An in-memory cosine-similarity vector index over embedded documents."""

    def __init__(self, provider: DeterministicEmbeddingProvider) -> None:
        self._provider = provider
        self._vectors: dict[str, dict[int, int]] = {}

    def add(self, doc_id: str, text: str) -> None:
        self._vectors[doc_id] = self._provider.embed(text)

    def search(self, query: str, *, limit: int | None = None) -> tuple[VectorHit, ...]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        query_vec = self._provider.embed(query)
        scored = [
            (doc_id, cosine_similarity(query_vec, vec))
            for doc_id, vec in self._vectors.items()
        ]
        scored = [(doc_id, s) for doc_id, s in scored if s > Decimal(0)]
        scored.sort(key=lambda item: (-item[1], item[0]))
        if limit is not None:
            scored = scored[:limit]
        return tuple(
            VectorHit(doc_id=doc_id, score=score, rank=i + 1)
            for i, (doc_id, score) in enumerate(scored)
        )


def hybrid_search(
    query: str,
    *,
    bm25_index: InvertedIndex,
    bm25_params: BM25Parameters,
    vector_index: VectorIndex,
    limit: int | None = None,
    k: int = DEFAULT_RRF_K,
) -> tuple[FusedHit, ...]:
    """Fuse lexical (BM25) and dense (vector) rankings via Reciprocal Rank Fusion."""
    lexical = [r.doc_id for r in bm25_search(query, bm25_index, params=bm25_params)]
    dense = [h.doc_id for h in vector_index.search(query)]
    fused = reciprocal_rank_fusion([lexical, dense], k=k)
    return fused[:limit] if limit is not None else fused
