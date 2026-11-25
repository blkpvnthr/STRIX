"""Regression tests for adversarial-review findings on the Wave-9 retrieval layer.

Pins the confirmed defects so they cannot regress:

1. CRITICAL — tampering the derived scalars (total_documents / total_tokens /
   avg_doc_length) must (a) NOT affect scores — the scorer derives them from the
   authoritative doc_lengths — and (b) be DETECTED by reconciliation.
2. MAJOR — avg_doc_length must be computed at the pinned precision, independent of
   the ambient Decimal context (reproducible + contract-recomputable).
3. MINOR — a phantom term with empty postings must be detected by reconciliation.
4. MINOR — duplicate doc_ids in the reconcile corpus must be rejected.
5. MINOR — search() must not silently strip hits from the wrong end on a negative
   limit.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal, localcontext

import pytest

from strix.errors import CalculationError
from strix.retrieval.bm25 import DEFAULT_BM25_PARAMETERS, search
from strix.retrieval.index import Document, build_index
from strix.retrieval.reconcile import DiscrepancyKind, reconcile_index

_CORPUS = (
    Document(doc_id="a", text="hello world"),
    Document(doc_id="b", text="hello"),
)
_UNEVEN = (
    Document(doc_id="d1", text="alpha beta gamma"),
    Document(doc_id="d2", text="alpha delta epsilon zeta"),
    Document(doc_id="d3", text="alpha gamma eta"),
)


def _self_consistent(index: object, **changes: object) -> object:
    """Apply field changes, then refresh the stored digest so the only defect under
    test is the tampered field — not a trivially-detectable stale digest."""
    tampered = dataclasses.replace(index, **changes)  # type: ignore[type-var]
    return dataclasses.replace(tampered, index_digest=tampered.recomputed_digest())  # type: ignore[attr-defined]


# --- Finding 1 (CRITICAL): tampered scalars -------------------------------


def test_scoring_ignores_tampered_total_documents() -> None:
    index = build_index(_CORPUS)
    honest = search("hello", index, params=DEFAULT_BM25_PARAMETERS)
    tampered = _self_consistent(index, total_documents=999)
    poisoned = search("hello", tampered, params=DEFAULT_BM25_PARAMETERS)  # type: ignore[arg-type]
    assert [(r.doc_id, r.score) for r in honest] == [(r.doc_id, r.score) for r in poisoned]


def test_scoring_ignores_tampered_avg_doc_length() -> None:
    index = build_index(_CORPUS)
    honest = search("hello", index, params=DEFAULT_BM25_PARAMETERS)
    tampered = _self_consistent(index, avg_doc_length=Decimal("100"))
    poisoned = search("hello", tampered, params=DEFAULT_BM25_PARAMETERS)  # type: ignore[arg-type]
    assert [(r.doc_id, r.score) for r in honest] == [(r.doc_id, r.score) for r in poisoned]


def test_reconcile_detects_tampered_total_documents() -> None:
    index = build_index(_CORPUS)
    tampered = _self_consistent(index, total_documents=999)
    report = reconcile_index(tampered, _CORPUS)  # type: ignore[arg-type]
    assert report.is_consistent is False
    assert DiscrepancyKind.STAT_MISMATCH in {d.kind for d in report.discrepancies}


def test_reconcile_detects_tampered_avg_doc_length() -> None:
    index = build_index(_CORPUS)
    tampered = _self_consistent(index, avg_doc_length=Decimal("100"))
    report = reconcile_index(tampered, _CORPUS)  # type: ignore[arg-type]
    assert report.is_consistent is False
    assert DiscrepancyKind.STAT_MISMATCH in {d.kind for d in report.discrepancies}


def test_reconcile_detects_tampered_total_tokens() -> None:
    index = build_index(_CORPUS)
    tampered = _self_consistent(index, total_tokens=12345)
    report = reconcile_index(tampered, _CORPUS)  # type: ignore[arg-type]
    assert report.is_consistent is False
    assert DiscrepancyKind.STAT_MISMATCH in {d.kind for d in report.discrepancies}


# --- Finding 2 (MAJOR): pinned-precision avg_doc_length -------------------


def test_avg_doc_length_independent_of_ambient_context() -> None:
    default_index = build_index(_UNEVEN)
    with localcontext() as ctx:
        ctx.prec = 12
        low_prec_index = build_index(_UNEVEN)
    assert default_index.avg_doc_length == low_prec_index.avg_doc_length
    s1 = search("alpha gamma", default_index, params=DEFAULT_BM25_PARAMETERS)
    s2 = search("alpha gamma", low_prec_index, params=DEFAULT_BM25_PARAMETERS)
    assert [(r.doc_id, r.score) for r in s1] == [(r.doc_id, r.score) for r in s2]


def test_avg_doc_length_has_pinned_precision() -> None:
    index = build_index(_UNEVEN)  # avgdl = 10/3
    # 50 significant digits, not the ambient-default 28.
    assert len(index.avg_doc_length.as_tuple().digits) == 50


# --- Finding 3 (MINOR): phantom empty-postings term ----------------------


def test_reconcile_detects_phantom_empty_term() -> None:
    index = build_index(_CORPUS)
    poisoned = {**index.postings, "ghost": {}}
    tampered = _self_consistent(index, postings=poisoned)
    report = reconcile_index(tampered, _CORPUS)  # type: ignore[arg-type]
    assert report.is_consistent is False


# --- Finding 4 (MINOR): duplicate doc_ids in the corpus ------------------


def test_reconcile_rejects_duplicate_doc_ids() -> None:
    index = build_index((Document(doc_id="a", text="alpha"),))
    with pytest.raises(CalculationError):
        reconcile_index(index, (Document(doc_id="a", text="x"), Document(doc_id="a", text="y")))


# --- Finding 5 (MINOR): negative search limit ----------------------------


def test_search_rejects_negative_limit() -> None:
    index = build_index(_CORPUS)
    with pytest.raises(ValueError):
        search("hello", index, params=DEFAULT_BM25_PARAMETERS, limit=-1)


def test_search_limit_zero_returns_empty() -> None:
    index = build_index(_CORPUS)
    assert search("hello", index, params=DEFAULT_BM25_PARAMETERS, limit=0) == ()
