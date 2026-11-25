"""Hybrid-retrieval fusion + evidence-aware reranking (§5/§7).

Reciprocal Rank Fusion (RRF) combines several ranked lists (e.g. BM25 lexical and a
dense-vector ranking) into one deterministic ranking. The evidence-aware
:func:`rerank` then scores candidates by a weighted blend of relevance and
evidence-quality features — BUT mandatory authorization and integrity constraints
are hard filters that a high ranking score can NEVER override. Ranking scores are
relevance signals, never verification certificates or confidence probabilities.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from pydantic import model_validator

from strix.models import DecimalValue, StrixModel
from strix.retrieval._precision import RETRIEVAL_PRECISION, RETRIEVAL_ROUNDING

#: Standard RRF damping constant.
DEFAULT_RRF_K = 60


class FusedHit(StrixModel):
    """One fused result: a document, its RRF score, and its 1-based rank."""

    doc_id: str
    score: DecimalValue
    rank: int


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = DEFAULT_RRF_K
) -> tuple[FusedHit, ...]:
    """Fuse ranked doc-id lists via RRF: score(d) = sum 1/(k + rank_in_list).

    Deterministic: scores computed under the pinned retrieval precision, ties broken
    by ascending doc_id. ``rank_in_list`` is 1-based.
    """
    if k <= 0:
        raise ValueError("RRF k must be positive")
    totals: dict[str, Decimal] = {}
    with localcontext() as ctx:
        ctx.prec = RETRIEVAL_PRECISION
        ctx.rounding = RETRIEVAL_ROUNDING
        for ranking in rankings:
            for position, doc_id in enumerate(ranking):
                contribution = Decimal(1) / Decimal(k + position + 1)
                totals[doc_id] = totals.get(doc_id, Decimal(0)) + contribution
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return tuple(
        FusedHit(doc_id=doc_id, score=score, rank=i + 1)
        for i, (doc_id, score) in enumerate(ordered)
    )


def fuse_results(
    result_lists: Sequence[Sequence[object]], *, k: int = DEFAULT_RRF_K
) -> tuple[FusedHit, ...]:
    """RRF over lists of objects exposing a ``doc_id`` attribute (e.g. SearchResult)."""
    rankings = [[getattr(r, "doc_id") for r in results] for results in result_lists]  # noqa: B009
    return reciprocal_rank_fusion(rankings, k=k)


class RerankWeights(StrixModel):
    """Weights for the evidence-aware rerank (must sum to 1; §5 experimental defaults)."""

    hybrid_relevance: DecimalValue
    evidence_type: DecimalValue
    provenance: DecimalValue
    temporal: DecimalValue
    source_authority: DecimalValue
    evidence_graph: DecimalValue

    @model_validator(mode="after")
    def _sum_to_one(self) -> RerankWeights:
        total = (
            self.hybrid_relevance + self.evidence_type + self.provenance
            + self.temporal + self.source_authority + self.evidence_graph
        )
        if total != Decimal(1):
            raise ValueError(f"rerank weights must sum to 1, got {total}")
        return self


#: §5 experimental default weights.
DEFAULT_RERANK_WEIGHTS = RerankWeights(
    hybrid_relevance=Decimal("0.30"),
    evidence_type=Decimal("0.25"),
    provenance=Decimal("0.15"),
    temporal=Decimal("0.10"),
    source_authority=Decimal("0.10"),
    evidence_graph=Decimal("0.10"),
)


class RerankFeatures(StrixModel):
    """Per-document relevance/evidence-quality feature scores (each in [0, 1])."""

    hybrid_relevance: DecimalValue
    evidence_type: DecimalValue
    provenance: DecimalValue
    temporal: DecimalValue
    source_authority: DecimalValue
    evidence_graph: DecimalValue


class RerankCandidate(StrixModel):
    """A rerank input: features plus the HARD authorization/integrity gates."""

    doc_id: str
    features: RerankFeatures
    #: Mandatory gates — a candidate failing either is excluded regardless of score.
    authorized: bool = True
    integrity_ok: bool = True


class RankedCandidate(StrixModel):
    """A reranked, admissible candidate with its combined score and rank."""

    doc_id: str
    score: DecimalValue
    rank: int


def rerank(
    candidates: Sequence[RerankCandidate], weights: RerankWeights = DEFAULT_RERANK_WEIGHTS
) -> tuple[RankedCandidate, ...]:
    """Rerank candidates by the weighted feature blend, after hard gating.

    Candidates that are not ``authorized`` or fail ``integrity_ok`` are excluded
    FIRST — no ranking score can surface them. The rest are scored by the weighted
    sum of their features and ordered by score desc, ties by ascending doc_id.
    """
    admissible = [c for c in candidates if c.authorized and c.integrity_ok]
    scored: list[tuple[str, Decimal]] = []
    with localcontext() as ctx:
        ctx.prec = RETRIEVAL_PRECISION
        ctx.rounding = RETRIEVAL_ROUNDING
        for c in admissible:
            f = c.features
            score = (
                weights.hybrid_relevance * f.hybrid_relevance
                + weights.evidence_type * f.evidence_type
                + weights.provenance * f.provenance
                + weights.temporal * f.temporal
                + weights.source_authority * f.source_authority
                + weights.evidence_graph * f.evidence_graph
            )
            scored.append((c.doc_id, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return tuple(
        RankedCandidate(doc_id=doc_id, score=score, rank=i + 1)
        for i, (doc_id, score) in enumerate(scored)
    )
