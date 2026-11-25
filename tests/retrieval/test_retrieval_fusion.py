"""Tests for Reciprocal Rank Fusion + evidence-aware rerank (§5/§7)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.retrieval.fusion import (
    DEFAULT_RERANK_WEIGHTS,
    RerankCandidate,
    RerankFeatures,
    RerankWeights,
    reciprocal_rank_fusion,
    rerank,
)


def test_rrf_fuses_two_rankings_deterministically() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], k=60)
    ids = [h.doc_id for h in fused]
    # a and b appear in both lists (highest), tie broken by doc_id; c,d once each.
    assert ids == ["a", "b", "c", "d"]
    by_id = {h.doc_id: h.score for h in fused}
    assert by_id["a"] == by_id["b"]  # symmetric contributions
    assert by_id["a"] > by_id["c"]
    assert fused[0].rank == 1 and fused[-1].rank == 4


def test_rrf_is_order_independent_across_input_lists() -> None:
    a = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
    b = reciprocal_rank_fusion([["b", "a"], ["a", "b"]])
    assert [(h.doc_id, h.score) for h in a] == [(h.doc_id, h.score) for h in b]


def test_rrf_empty_returns_empty() -> None:
    assert reciprocal_rank_fusion([]) == ()
    assert reciprocal_rank_fusion([[], []]) == ()


def test_default_weights_sum_to_one_and_match_spec() -> None:
    w = DEFAULT_RERANK_WEIGHTS
    assert w.hybrid_relevance == Decimal("0.30")
    assert w.evidence_type == Decimal("0.25")
    assert w.provenance == Decimal("0.15")
    assert w.temporal == Decimal("0.10")
    assert w.source_authority == Decimal("0.10")
    assert w.evidence_graph == Decimal("0.10")


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError):
        RerankWeights(
            hybrid_relevance=Decimal("0.5"), evidence_type=Decimal("0.5"),
            provenance=Decimal("0.5"), temporal=Decimal("0"),
            source_authority=Decimal("0"), evidence_graph=Decimal("0"),
        )


def _candidate(
    doc_id: str, score: str, *, authorized: bool = True, integrity: bool = True
) -> RerankCandidate:
    s = Decimal(score)
    return RerankCandidate(
        doc_id=doc_id,
        features=RerankFeatures(
            hybrid_relevance=s, evidence_type=s, provenance=s, temporal=s,
            source_authority=s, evidence_graph=s,
        ),
        authorized=authorized,
        integrity_ok=integrity,
    )


def test_rerank_orders_by_weighted_score() -> None:
    ranked = rerank([_candidate("low", "0.2"), _candidate("high", "0.9")])
    assert [r.doc_id for r in ranked] == ["high", "low"]
    # All-equal features -> weighted score == feature value (weights sum to 1).
    assert ranked[0].score == Decimal("0.9")


def test_rerank_excludes_unauthorized_regardless_of_score() -> None:
    ranked = rerank([
        _candidate("secret", "1.0", authorized=False),
        _candidate("ok", "0.1"),
    ])
    assert [r.doc_id for r in ranked] == ["ok"]  # a top-scoring unauthorized doc is dropped


def test_rerank_excludes_integrity_failures_regardless_of_score() -> None:
    ranked = rerank([
        _candidate("tampered", "1.0", integrity=False),
        _candidate("ok", "0.1"),
    ])
    assert [r.doc_id for r in ranked] == ["ok"]


def test_rerank_tie_broken_by_doc_id() -> None:
    ranked = rerank([_candidate("zeta", "0.5"), _candidate("alpha", "0.5")])
    assert [r.doc_id for r in ranked] == ["alpha", "zeta"]
