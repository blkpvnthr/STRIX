"""Index reconciliation: prove an index faithfully represents its corpus (§6.C).

The retrieval analogue of GAP-003. :func:`reconcile_index` independently rebuilds
the postings, lengths, AND derived corpus statistics from the corpus, diffs them
against the index under test, and verifies the index's STORED ``index_digest``
matches its ACTUAL current content. Tampering of ANY scorer-relevant field —
postings, lengths, or the derived scalars (``total_documents`` / ``total_tokens`` /
``avg_doc_length``) — is detected rather than silently trusted. It never asserts
intent (tampering vs honest drift); it reports discrepancies for review.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum

from strix.canonical import canonical_hash
from strix.errors import CalculationError
from strix.models import StrixModel
from strix.research.normalize import tokenize
from strix.retrieval.index import (
    Document,
    InvertedIndex,
    _canonical_payload,
    average_document_length,
)


class DiscrepancyKind(StrEnum):
    """Categories of index/corpus inconsistency."""

    #: In the corpus but absent from the index.
    DOC_MISSING_FROM_INDEX = "doc_missing_from_index"
    #: In the index but absent from the corpus.
    DOC_UNEXPECTED_IN_INDEX = "doc_unexpected_in_index"
    #: Document present in both but with a different token count.
    LENGTH_MISMATCH = "length_mismatch"
    #: A term's postings differ between index and corpus.
    POSTINGS_MISMATCH = "postings_mismatch"
    #: A derived corpus statistic (total_documents/total_tokens/avg_doc_length)
    #: disagrees with the corpus.
    STAT_MISMATCH = "stat_mismatch"
    #: The index's stored digest does not match its actual content.
    STALE_DIGEST = "stale_digest"
    #: Catch-all: the index content digest differs from the corpus's despite no
    #: field-level diff being enumerated (defense in depth).
    CONTENT_DIGEST_MISMATCH = "content_digest_mismatch"


class IndexDiscrepancy(StrixModel):
    """One detected inconsistency between an index and its corpus."""

    kind: DiscrepancyKind
    detail: str
    doc_id: str | None = None
    term: str | None = None


class IndexReconciliationReport(StrixModel):
    """The outcome of reconciling an index against a corpus."""

    index_digest: str
    rebuilt_digest: str
    actual_content_digest: str
    is_consistent: bool
    discrepancies: tuple[IndexDiscrepancy, ...]


def _rebuild(
    documents: Sequence[Document],
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Recompute postings/lengths from a corpus; reject duplicate doc_ids.

    Rejecting duplicates mirrors :func:`build_index` so the reconciliation
    ground-truth is always a coherent corpus (a duplicate would otherwise leak
    postings and produce a self-contradictory baseline).
    """
    postings: dict[str, dict[str, int]] = {}
    doc_lengths: dict[str, int] = {}
    for document in documents:
        if document.doc_id in doc_lengths:
            raise CalculationError(f"duplicate doc_id {document.doc_id!r} in corpus")
        tokens = tokenize(document.text)
        doc_lengths[document.doc_id] = len(tokens)
        for term, freq in Counter(tokens).items():
            postings.setdefault(term, {})[document.doc_id] = freq
    return postings, doc_lengths


def reconcile_index(
    index: InvertedIndex, documents: Sequence[Document]
) -> IndexReconciliationReport:
    """Reconcile ``index`` against ``documents`` and report every discrepancy."""
    rebuilt_postings, rebuilt_lengths = _rebuild(documents)
    rebuilt_total_documents = len(rebuilt_lengths)
    rebuilt_total_tokens = sum(rebuilt_lengths.values())
    rebuilt_avg = average_document_length(rebuilt_total_tokens, rebuilt_total_documents)
    rebuilt_digest = canonical_hash(
        _canonical_payload(
            rebuilt_postings,
            rebuilt_lengths,
            rebuilt_total_documents,
            rebuilt_total_tokens,
            rebuilt_avg,
        )
    )
    actual_digest = index.recomputed_digest()

    discrepancies: list[IndexDiscrepancy] = []

    # 1. The stored digest must match the index's actual content.
    if index.index_digest != actual_digest:
        discrepancies.append(
            IndexDiscrepancy(
                kind=DiscrepancyKind.STALE_DIGEST,
                detail=(
                    f"stored digest {index.index_digest!r} does not match the "
                    f"digest of the index's actual content {actual_digest!r}"
                ),
            )
        )

    # 2. Document-set and length diffs.
    index_docs = set(index.doc_lengths)
    corpus_docs = set(rebuilt_lengths)
    for doc_id in sorted(corpus_docs - index_docs):
        discrepancies.append(
            IndexDiscrepancy(
                kind=DiscrepancyKind.DOC_MISSING_FROM_INDEX,
                detail=f"document {doc_id!r} is in the corpus but not the index",
                doc_id=doc_id,
            )
        )
    for doc_id in sorted(index_docs - corpus_docs):
        discrepancies.append(
            IndexDiscrepancy(
                kind=DiscrepancyKind.DOC_UNEXPECTED_IN_INDEX,
                detail=f"document {doc_id!r} is in the index but not the corpus",
                doc_id=doc_id,
            )
        )
    for doc_id in sorted(index_docs & corpus_docs):
        if index.doc_lengths[doc_id] != rebuilt_lengths[doc_id]:
            discrepancies.append(
                IndexDiscrepancy(
                    kind=DiscrepancyKind.LENGTH_MISMATCH,
                    detail=(
                        f"length {index.doc_lengths[doc_id]} != corpus "
                        f"{rebuilt_lengths[doc_id]}"
                    ),
                    doc_id=doc_id,
                )
            )

    # 3. Per-term postings diffs. Use ``.get(term)`` WITHOUT a default so a term
    #    present with empty postings ({}) is distinguished from an absent term
    #    (None) — a phantom empty-postings term is a real inconsistency.
    for term in sorted(set(index.postings) | set(rebuilt_postings)):
        if index.postings.get(term) != rebuilt_postings.get(term):
            discrepancies.append(
                IndexDiscrepancy(
                    kind=DiscrepancyKind.POSTINGS_MISMATCH,
                    detail=(
                        f"postings for {term!r}: index {index.postings.get(term)} "
                        f"!= corpus {rebuilt_postings.get(term)}"
                    ),
                    term=term,
                )
            )

    # 4. Derived-statistic diffs (scorer-critical; tampering these corrupts every
    #    score, so they must be verified against the corpus).
    for name, index_value, corpus_value in (
        ("total_documents", index.total_documents, rebuilt_total_documents),
        ("total_tokens", index.total_tokens, rebuilt_total_tokens),
        ("avg_doc_length", index.avg_doc_length, rebuilt_avg),
    ):
        if index_value != corpus_value:
            discrepancies.append(
                IndexDiscrepancy(
                    kind=DiscrepancyKind.STAT_MISMATCH,
                    detail=f"{name}: index {index_value} != corpus {corpus_value}",
                )
            )

    # 5. Defense in depth: the index content digest must equal the corpus's. If it
    #    does not yet nothing above captured it, record a catch-all so a clean
    #    verdict can never hide a content divergence.
    if actual_digest != rebuilt_digest and not discrepancies:
        discrepancies.append(
            IndexDiscrepancy(
                kind=DiscrepancyKind.CONTENT_DIGEST_MISMATCH,
                detail=(
                    f"index content digest {actual_digest!r} != corpus digest "
                    f"{rebuilt_digest!r}"
                ),
            )
        )

    return IndexReconciliationReport(
        index_digest=index.index_digest,
        rebuilt_digest=rebuilt_digest,
        actual_content_digest=actual_digest,
        is_consistent=not discrepancies,
        discrepancies=tuple(discrepancies),
    )
