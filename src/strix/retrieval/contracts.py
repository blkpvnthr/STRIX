"""Retrieval reproducibility contract (§6.C).

A :class:`RetrievalContract` records everything needed to reproduce a ranking
exactly: the tokenization/normalization policy versions, the BM25 parameters, the
pinned Decimal precision and rounding, and the content-addressed index digest.
Anyone holding the corpus and this contract can recompute identical scores — the
retrieval layer carries no hidden state.
"""

from __future__ import annotations

from strix.models import DecimalValue, StrixModel
from strix.research.normalize import NORMALIZATION_POLICY_VERSION, TOKENIZATION_POLICY_VERSION
from strix.retrieval.bm25 import BM25_PRECISION, BM25Parameters
from strix.retrieval.index import InvertedIndex

RETRIEVAL_CONTRACT_VERSION = "1.0.0"


class RetrievalContract(StrixModel):
    """The reproducibility descriptor for a BM25 ranking over an index."""

    contract_version: str
    tokenization_policy_version: str
    normalization_policy_version: str
    bm25_k1: DecimalValue
    bm25_b: DecimalValue
    decimal_precision: int
    rounding: str
    index_digest: str
    total_documents: int


def make_retrieval_contract(
    index: InvertedIndex, params: BM25Parameters
) -> RetrievalContract:
    """Assemble the :class:`RetrievalContract` for ``index`` ranked with ``params``."""
    return RetrievalContract(
        contract_version=RETRIEVAL_CONTRACT_VERSION,
        tokenization_policy_version=TOKENIZATION_POLICY_VERSION,
        normalization_policy_version=NORMALIZATION_POLICY_VERSION,
        bm25_k1=params.k1,
        bm25_b=params.b,
        decimal_precision=BM25_PRECISION,
        rounding="round_half_even",
        index_digest=index.index_digest,
        total_documents=index.total_documents,
    )
