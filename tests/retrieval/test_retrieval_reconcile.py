"""Tests for index reconciliation — proving an index represents its corpus (§6.C).

Reconciliation is the retrieval analogue of GAP-003: it independently rebuilds the
index from the corpus and diffs it against the index under test, and also verifies
the index's stored digest matches its ACTUAL content (catching a forged/stale
digest). Tampering of any kind must be detected, never silently trusted.
"""

from __future__ import annotations

import dataclasses

from strix.retrieval.index import Document, build_index
from strix.retrieval.reconcile import DiscrepancyKind, reconcile_index

_CORPUS = (
    Document(doc_id="a", text="the quick brown fox"),
    Document(doc_id="b", text="the lazy dog"),
)


def test_honest_index_reconciles_clean() -> None:
    index = build_index(_CORPUS)
    report = reconcile_index(index, _CORPUS)
    assert report.is_consistent is True
    assert report.discrepancies == ()
    assert report.index_digest == report.rebuilt_digest


def test_tampered_doc_length_detected() -> None:
    index = build_index(_CORPUS)
    tampered = dataclasses.replace(index, doc_lengths={**index.doc_lengths, "a": 99})
    report = reconcile_index(tampered, _CORPUS)
    assert report.is_consistent is False
    kinds = {d.kind for d in report.discrepancies}
    assert DiscrepancyKind.LENGTH_MISMATCH in kinds


def test_tampered_postings_detected() -> None:
    index = build_index(_CORPUS)
    poisoned = {**index.postings, "fox": {"a": 1, "b": 7}}  # b does not contain "fox"
    tampered = dataclasses.replace(index, postings=poisoned)
    report = reconcile_index(tampered, _CORPUS)
    assert report.is_consistent is False
    assert DiscrepancyKind.POSTINGS_MISMATCH in {d.kind for d in report.discrepancies}


def test_document_added_to_corpus_detected() -> None:
    index = build_index(_CORPUS)
    grown = (*_CORPUS, Document(doc_id="c", text="new document"))
    report = reconcile_index(index, grown)
    assert report.is_consistent is False
    assert DiscrepancyKind.DOC_MISSING_FROM_INDEX in {d.kind for d in report.discrepancies}


def test_document_removed_from_corpus_detected() -> None:
    index = build_index(_CORPUS)
    shrunk = (_CORPUS[0],)
    report = reconcile_index(index, shrunk)
    assert report.is_consistent is False
    assert DiscrepancyKind.DOC_UNEXPECTED_IN_INDEX in {d.kind for d in report.discrepancies}


def test_forged_stored_digest_detected_even_if_content_matches_corpus() -> None:
    index = build_index(_CORPUS)
    forged = dataclasses.replace(index, index_digest="DEADBEEF-not-the-real-digest")
    report = reconcile_index(forged, _CORPUS)
    assert report.is_consistent is False
    assert DiscrepancyKind.STALE_DIGEST in {d.kind for d in report.discrepancies}


def test_empty_corpus_is_a_discrepancy_not_a_crash() -> None:
    index = build_index(_CORPUS)
    report = reconcile_index(index, ())
    assert report.is_consistent is False
    assert report.discrepancies  # both docs are unexpected in the index
