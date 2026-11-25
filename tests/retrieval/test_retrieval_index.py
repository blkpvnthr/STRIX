"""Tests for the deterministic inverted index (§6.C retrieval infra)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import CalculationError
from strix.retrieval.index import Document, average_document_length, build_index

_CORPUS = (
    Document(doc_id="a", text="the quick brown fox"),
    Document(doc_id="b", text="the lazy dog"),
    Document(doc_id="c", text="quick quick fox"),
)


def test_index_counts_documents_and_tokens() -> None:
    index = build_index(_CORPUS)
    assert index.total_documents == 3
    assert index.total_tokens == 10  # 4 + 3 + 3
    assert index.doc_lengths == {"a": 4, "b": 3, "c": 3}


def test_average_document_length_is_pinned_precision_decimal() -> None:
    index = build_index(_CORPUS)
    # Recorded as a Decimal (never a float), computed at the pinned retrieval
    # precision so it is reproducible regardless of the caller's ambient context.
    assert isinstance(index.avg_doc_length, Decimal)
    assert index.avg_doc_length == average_document_length(10, 3)


def test_postings_record_term_frequencies() -> None:
    index = build_index(_CORPUS)
    assert index.postings["quick"] == {"a": 1, "c": 2}
    assert index.postings["the"] == {"a": 1, "b": 1}
    assert index.document_frequency("quick") == 2
    assert index.document_frequency("fox") == 2
    assert index.document_frequency("absent") == 0


def test_index_digest_is_deterministic_and_order_independent() -> None:
    index1 = build_index(_CORPUS)
    index2 = build_index(tuple(reversed(_CORPUS)))
    # Content-addressed over canonical sorted structure → order-independent.
    assert index1.index_digest == index2.index_digest


def test_index_digest_changes_with_content() -> None:
    index1 = build_index(_CORPUS)
    index2 = build_index((*_CORPUS, Document(doc_id="d", text="new content")))
    assert index1.index_digest != index2.index_digest


def test_duplicate_doc_ids_rejected() -> None:
    with pytest.raises(CalculationError):
        build_index((Document(doc_id="x", text="one"), Document(doc_id="x", text="two")))


def test_empty_corpus_rejected() -> None:
    with pytest.raises(CalculationError):
        build_index(())


def test_document_with_no_tokens_is_retained_with_zero_length() -> None:
    index = build_index((Document(doc_id="a", text="hello"), Document(doc_id="b", text="!!! ???")))
    assert index.doc_lengths == {"a": 1, "b": 0}
    assert index.total_documents == 2
