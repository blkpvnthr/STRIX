"""Tests for the retrieval reproducibility contract + end-to-end flow (§6.C)."""

from __future__ import annotations

from decimal import Decimal

from strix.research.normalize import NORMALIZATION_POLICY_VERSION, TOKENIZATION_POLICY_VERSION
from strix.retrieval.bm25 import BM25_PRECISION, DEFAULT_BM25_PARAMETERS, search
from strix.retrieval.contracts import RetrievalContract, make_retrieval_contract
from strix.retrieval.index import Document, build_index
from strix.retrieval.reconcile import reconcile_index

_CORPUS = (
    Document(doc_id="a", text="the quick brown fox"),
    Document(doc_id="b", text="the lazy dog"),
    Document(doc_id="c", text="quick quick fox"),
)


def test_contract_records_everything_needed_to_reproduce() -> None:
    index = build_index(_CORPUS)
    contract = make_retrieval_contract(index, DEFAULT_BM25_PARAMETERS)
    assert isinstance(contract, RetrievalContract)
    assert contract.tokenization_policy_version == TOKENIZATION_POLICY_VERSION
    assert contract.normalization_policy_version == NORMALIZATION_POLICY_VERSION
    assert contract.bm25_k1 == Decimal("1.2")
    assert contract.bm25_b == Decimal("0.75")
    assert contract.decimal_precision == BM25_PRECISION
    assert contract.rounding == "round_half_even"
    assert contract.index_digest == index.index_digest
    assert contract.total_documents == 3


def test_contract_digest_tracks_the_index() -> None:
    index1 = build_index(_CORPUS)
    index2 = build_index((*_CORPUS, Document(doc_id="d", text="more")))
    c1 = make_retrieval_contract(index1, DEFAULT_BM25_PARAMETERS)
    c2 = make_retrieval_contract(index2, DEFAULT_BM25_PARAMETERS)
    assert c1.index_digest != c2.index_digest


def test_end_to_end_index_search_reconcile_is_consistent() -> None:
    index = build_index(_CORPUS)
    results = search("quick fox", index, params=DEFAULT_BM25_PARAMETERS)
    # Only a and c contain "quick"/"fox"; b (="the lazy dog") is excluded.
    assert [r.doc_id for r in results] == ["c", "a"]
    # Reconciliation proves the index the search ran against matches the corpus.
    report = reconcile_index(index, _CORPUS)
    assert report.is_consistent is True
