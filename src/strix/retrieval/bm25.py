"""Deterministic Okapi/Lucene BM25 ranking in exact Decimal (§6.C).

Every value is computed under a pinned Decimal context (precision
:data:`BM25_PRECISION`, ``ROUND_HALF_EVEN``), so a score is fully reproducible and
hand-recomputable from the index and parameters — no floating point, no network.
The IDF uses the Lucene form ``ln(1 + (N - df + 0.5) / (df + 0.5))`` which is
always non-negative. Repeated query terms are deduplicated before scoring, so
repeating a word in the query cannot inflate its own weight.

    score(q, d) = sum over distinct query terms t present in d of
        idf(t) * ( tf(t,d) * (k1 + 1) )
                 / ( tf(t,d) + k1 * (1 - b + b * |d| / avgdl) )
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from strix.models import DecimalValue, StrixModel
from strix.research.normalize import tokenize
from strix.retrieval._precision import RETRIEVAL_PRECISION, RETRIEVAL_ROUNDING
from strix.retrieval.index import InvertedIndex

#: Decimal working precision for all BM25 arithmetic (incl. ``ln``).
BM25_PRECISION = RETRIEVAL_PRECISION
BM25_ROUNDING = RETRIEVAL_ROUNDING


class BM25Parameters(StrixModel):
    """BM25 free parameters (``k1`` term-saturation, ``b`` length-normalization)."""

    k1: DecimalValue = Decimal("1.2")
    b: DecimalValue = Decimal("0.75")


DEFAULT_BM25_PARAMETERS = BM25Parameters()


class SearchResult(StrixModel):
    """One ranked hit: a document, its BM25 score, and its 1-based rank."""

    doc_id: str
    score: DecimalValue
    rank: int


def bm25_idf(term: str, index: InvertedIndex, *, params: BM25Parameters) -> Decimal:
    """Lucene BM25 inverse document frequency for ``term`` (always ≥ 0).

    ``N`` is derived from the authoritative ``doc_lengths`` rather than the stored
    ``total_documents`` scalar, so a tampered scalar cannot corrupt the IDF.
    """
    df = index.document_frequency(term)
    n_docs = len(index.doc_lengths)
    with localcontext() as ctx:
        ctx.prec = BM25_PRECISION
        ctx.rounding = BM25_ROUNDING
        half = Decimal("0.5")
        ratio = (Decimal(n_docs) - Decimal(df) + half) / (Decimal(df) + half)
        return (Decimal(1) + ratio).ln()


def bm25_score(
    query_tokens: Sequence[str],
    doc_id: str,
    index: InvertedIndex,
    *,
    params: BM25Parameters,
) -> Decimal:
    """BM25 score of ``doc_id`` against ``query_tokens`` (0 if no term matches).

    The average document length is derived from the authoritative ``doc_lengths``
    at the pinned precision — never read from the stored ``avg_doc_length`` scalar —
    so a tampered scalar cannot corrupt the score.
    """
    dl = Decimal(index.doc_lengths.get(doc_id, 0))
    n_docs = len(index.doc_lengths)
    with localcontext() as ctx:
        ctx.prec = BM25_PRECISION
        ctx.rounding = BM25_ROUNDING
        avgdl = (
            Decimal(sum(index.doc_lengths.values())) / Decimal(n_docs)
            if n_docs
            else Decimal(0)
        )
        total = Decimal(0)
        # dict.fromkeys deduplicates while preserving first-seen order.
        for term in dict.fromkeys(query_tokens):
            posting = index.postings.get(term)
            if not posting:
                continue
            tf = posting.get(doc_id, 0)
            if tf == 0:
                continue
            tf_dec = Decimal(tf)
            idf = bm25_idf(term, index, params=params)
            denom = tf_dec + params.k1 * (Decimal(1) - params.b + params.b * dl / avgdl)
            total += idf * (tf_dec * (params.k1 + Decimal(1))) / denom
        return total


def _ranking_key(result: tuple[str, Decimal]) -> tuple[Decimal, str]:
    doc_id, score = result
    # Score descending, then doc_id ascending for a deterministic tiebreak.
    return (-score, doc_id)


def search(
    query: str,
    index: InvertedIndex,
    *,
    params: BM25Parameters,
    limit: int | None = None,
) -> tuple[SearchResult, ...]:
    """Rank the corpus against ``query`` and return the top ``limit`` hits.

    Only documents containing at least one query term are returned. Ranking is
    deterministic: score descending, ties broken by ascending ``doc_id``.
    """
    if limit is not None and limit < 0:
        raise ValueError(f"limit must be non-negative, got {limit}")
    query_tokens = tokenize(query)
    if not query_tokens:
        return ()

    # Candidate docs = union of postings for the distinct query terms.
    candidates: set[str] = set()
    for term in dict.fromkeys(query_tokens):
        posting = index.postings.get(term)
        if posting:
            candidates.update(posting)

    scored = [
        (doc_id, bm25_score(query_tokens, doc_id, index, params=params))
        for doc_id in candidates
    ]
    scored = [(doc_id, score) for doc_id, score in scored if score > Decimal(0)]
    scored.sort(key=_ranking_key)
    if limit is not None:
        scored = scored[:limit]
    return tuple(
        SearchResult(doc_id=doc_id, score=score, rank=i + 1)
        for i, (doc_id, score) in enumerate(scored)
    )
