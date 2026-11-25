"""Tests for deterministic Decimal BM25 ranking (§6.C).

Correctness is pinned by an INDEPENDENT recomputation of the BM25 formula at the
same pinned precision/rounding — proving the implementation matches the documented,
hand-recomputable specification exactly (no floating point anywhere).
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import pytest

from strix.retrieval.bm25 import (
    BM25_PRECISION,
    DEFAULT_BM25_PARAMETERS,
    BM25Parameters,
    bm25_idf,
    bm25_score,
    search,
)
from strix.retrieval.index import Document, build_index

_CORPUS = (
    Document(doc_id="a", text="the quick brown fox"),
    Document(doc_id="b", text="the lazy dog"),
    Document(doc_id="c", text="quick quick fox"),
)


def _ref_idf(n_docs: int, df: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = BM25_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        half = Decimal("0.5")
        ratio = (Decimal(n_docs) - Decimal(df) + half) / (Decimal(df) + half)
        return (Decimal(1) + ratio).ln()


def _ref_score(
    query_tokens: tuple[str, ...], doc_id: str, params: BM25Parameters
) -> Decimal:
    index = build_index(_CORPUS)
    with localcontext() as ctx:
        ctx.prec = BM25_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        total = Decimal(0)
        dl = Decimal(index.doc_lengths[doc_id])
        avgdl = index.avg_doc_length
        for term in dict.fromkeys(query_tokens):
            df = index.document_frequency(term)
            if df == 0:
                continue
            tf = Decimal(index.postings[term].get(doc_id, 0))
            if tf == 0:
                continue
            idf = _ref_idf(index.total_documents, df)
            denom = tf + params.k1 * (Decimal(1) - params.b + params.b * dl / avgdl)
            total += idf * (tf * (params.k1 + Decimal(1))) / denom
        return total


def test_idf_matches_formula_exactly() -> None:
    index = build_index(_CORPUS)
    observed = bm25_idf("quick", index, params=DEFAULT_BM25_PARAMETERS)
    assert observed == _ref_idf(index.total_documents, 2)


def test_idf_is_non_negative_even_for_common_terms() -> None:
    # A term in every document still yields a non-negative IDF (Lucene form).
    corpus = (Document(doc_id="a", text="x"), Document(doc_id="b", text="x"))
    index = build_index(corpus)
    assert bm25_idf("x", index, params=DEFAULT_BM25_PARAMETERS) >= Decimal(0)


def test_score_matches_independent_recompute() -> None:
    index = build_index(_CORPUS)
    for doc_id in ("a", "c"):
        observed = bm25_score(("quick",), doc_id, index, params=DEFAULT_BM25_PARAMETERS)
        assert observed == _ref_score(("quick",), doc_id, DEFAULT_BM25_PARAMETERS)


def test_score_zero_when_no_query_term_present() -> None:
    index = build_index(_CORPUS)
    assert bm25_score(("quick",), "b", index, params=DEFAULT_BM25_PARAMETERS) == Decimal(0)


def test_repeated_query_terms_do_not_inflate_score() -> None:
    index = build_index(_CORPUS)
    once = bm25_score(("quick",), "c", index, params=DEFAULT_BM25_PARAMETERS)
    twice = bm25_score(("quick", "quick"), "c", index, params=DEFAULT_BM25_PARAMETERS)
    assert once == twice


def test_search_ranks_by_score_descending() -> None:
    index = build_index(_CORPUS)
    results = search("quick", index, params=DEFAULT_BM25_PARAMETERS)
    # Only a and c contain "quick"; c has tf=2 and is shorter → ranks first.
    assert [r.doc_id for r in results] == ["c", "a"]
    assert results[0].rank == 1 and results[1].rank == 2
    assert results[0].score > results[1].score > Decimal(0)


def test_search_breaks_ties_by_doc_id() -> None:
    # Two identical documents → identical scores → deterministic doc_id tiebreak.
    corpus = (
        Document(doc_id="zeta", text="apple"),
        Document(doc_id="alpha", text="apple"),
    )
    index = build_index(corpus)
    results = search("apple", index, params=DEFAULT_BM25_PARAMETERS)
    assert [r.doc_id for r in results] == ["alpha", "zeta"]
    assert results[0].score == results[1].score


def test_search_respects_limit() -> None:
    index = build_index(_CORPUS)
    results = search("quick fox", index, params=DEFAULT_BM25_PARAMETERS, limit=1)
    assert len(results) == 1


def test_search_empty_query_returns_nothing() -> None:
    index = build_index(_CORPUS)
    assert search("!!! ???", index, params=DEFAULT_BM25_PARAMETERS) == ()


def test_search_is_deterministic() -> None:
    index = build_index(_CORPUS)
    r1 = search("quick fox", index, params=DEFAULT_BM25_PARAMETERS)
    r2 = search("quick fox", index, params=DEFAULT_BM25_PARAMETERS)
    assert [(r.doc_id, r.score) for r in r1] == [(r.doc_id, r.score) for r in r2]


def test_parameters_reject_float() -> None:
    # pydantic's ValidationError subclasses ValueError; DecimalValue bans floats.
    with pytest.raises(ValueError):
        BM25Parameters(k1=1.2, b=0.75)  # type: ignore[arg-type]
