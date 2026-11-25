"""Deterministic inverted index over a text corpus (§6.C).

``build_index`` tokenizes each document with the shared, versioned tokenizer
(:func:`strix.research.normalize.tokenize`) and produces an :class:`InvertedIndex`
carrying term postings, document lengths, corpus statistics, and a content-
addressed ``index_digest``. The digest is computed over a canonical, sorted
representation so it is independent of document insertion order — two corpora with
the same content always yield the same digest, which the reconciliation layer uses
to prove an index faithfully represents its corpus.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

from strix.canonical import canonical_hash
from strix.errors import CalculationError
from strix.models import StrixModel
from strix.research.normalize import TOKENIZATION_POLICY_VERSION, tokenize
from strix.retrieval._precision import RETRIEVAL_PRECISION, RETRIEVAL_ROUNDING


class Document(StrixModel):
    """One corpus document: a stable identifier and its raw text."""

    doc_id: str
    text: str


@dataclass(frozen=True)
class InvertedIndex:
    """An immutable inverted index with corpus statistics and a content digest.

    The ``postings``/``doc_lengths`` mappings are treated as read-only; the
    ``index_digest`` pins the exact content they represent.
    """

    doc_ids: tuple[str, ...]
    #: term -> {doc_id -> term frequency in that document}
    postings: dict[str, dict[str, int]]
    #: doc_id -> token count
    doc_lengths: dict[str, int]
    total_documents: int
    total_tokens: int
    avg_doc_length: Decimal
    index_digest: str
    tokenization_policy_version: str

    def document_frequency(self, term: str) -> int:
        """Number of documents containing ``term`` (0 if absent)."""
        return len(self.postings.get(term, {}))

    def recomputed_digest(self) -> str:
        """Re-derive the content digest from this index's ACTUAL current fields.

        Used by reconciliation to detect a stored digest that no longer matches the
        content it claims to address.
        """
        return canonical_hash(
            _canonical_payload(
                self.postings,
                self.doc_lengths,
                self.total_documents,
                self.total_tokens,
                self.avg_doc_length,
            )
        )


def average_document_length(total_tokens: int, total_documents: int) -> Decimal:
    """Average document length as a Decimal at the pinned retrieval precision.

    Computed under a pinned context so the value is independent of the caller's
    ambient Decimal context and is recomputable from the :class:`RetrievalContract`.
    """
    if total_documents == 0:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = RETRIEVAL_PRECISION
        ctx.rounding = RETRIEVAL_ROUNDING
        return Decimal(total_tokens) / Decimal(total_documents)


def _canonical_payload(
    postings: dict[str, dict[str, int]],
    doc_lengths: dict[str, int],
    total_documents: int,
    total_tokens: int,
    avg_doc_length: Decimal,
) -> dict[str, object]:
    """A deterministic, order-independent representation for the content digest.

    Every field the scorer depends on — including the derived corpus statistics —
    is bound into the digest, so tampering any of them changes the digest.
    """
    sorted_postings = [
        [term, sorted(postings[term].items())] for term in sorted(postings)
    ]
    return {
        "postings": sorted_postings,
        "doc_lengths": sorted(doc_lengths.items()),
        "total_documents": total_documents,
        "total_tokens": total_tokens,
        "avg_doc_length": str(avg_doc_length),
        "tokenization_policy_version": TOKENIZATION_POLICY_VERSION,
    }


def build_index(documents: Sequence[Document]) -> InvertedIndex:
    """Build a deterministic :class:`InvertedIndex` from ``documents``.

    Raises :class:`CalculationError` on an empty corpus or duplicate ``doc_id``.
    A document that tokenizes to nothing is retained with length 0 (it simply has
    no postings), so the corpus statistics stay faithful to the input.
    """
    if not documents:
        raise CalculationError("cannot index an empty corpus")

    postings: dict[str, dict[str, int]] = {}
    doc_lengths: dict[str, int] = {}
    doc_ids: list[str] = []
    for document in documents:
        if document.doc_id in doc_lengths:
            raise CalculationError(f"duplicate doc_id {document.doc_id!r}")
        tokens = tokenize(document.text)
        doc_lengths[document.doc_id] = len(tokens)
        doc_ids.append(document.doc_id)
        for term, freq in Counter(tokens).items():
            postings.setdefault(term, {})[document.doc_id] = freq

    total_documents = len(doc_ids)
    total_tokens = sum(doc_lengths.values())
    avg_doc_length = average_document_length(total_tokens, total_documents)
    index_digest = canonical_hash(
        _canonical_payload(postings, doc_lengths, total_documents, total_tokens, avg_doc_length)
    )
    return InvertedIndex(
        doc_ids=tuple(doc_ids),
        postings=postings,
        doc_lengths=doc_lengths,
        total_documents=total_documents,
        total_tokens=total_tokens,
        avg_doc_length=avg_doc_length,
        index_digest=index_digest,
        tokenization_policy_version=TOKENIZATION_POLICY_VERSION,
    )
