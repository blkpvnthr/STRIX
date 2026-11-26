"""Dependency-aware admission on the live path (R-N1 / A_ind projection).

Applies the dependency engine's content-hash origin canonicalization to a claim's cited
evidence, so duplicated or shared-origin corroboration cannot create unjustified confidence
in independent support. Faithfully computable from AgentEvidence (content_hash + provider);
does not require the full evidence-graph reconstruction.
"""

from __future__ import annotations

from datetime import UTC, datetime

from strix.agent.dependency_check import IndependenceVerdict, assess_claim_independence
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentEvidence,
    AgentVerificationStatus,
    ClaimVerification,
    SourceKind,
)

_NOW = datetime(2024, 1, 1, tzinfo=UTC)
_H1 = "1" * 64
_H2 = "2" * 64


def _evidence(eid: str, content_hash: str, provider: str) -> AgentEvidence:
    return AgentEvidence(
        evidence_id=eid,
        source_type=SourceKind.SEC_EDGAR,
        provider=provider,
        source_title=f"doc {eid}",
        retrieved_at=_NOW,
        content_hash=content_hash,
    )


def _claim(evidence_ids: tuple[str, ...]) -> AgentClaim:
    return AgentClaim(
        claim_id="c1",
        claim_type=AgentClaimType.OBSERVATION,
        statement="a corroborated statement",
        evidence_ids=evidence_ids,
        verification=ClaimVerification(status=AgentVerificationStatus.VERIFIED),
    )


def test_distinct_origins_are_independent() -> None:
    col = EvidenceCollector()
    col.put_evidence(_evidence("E1", _H1, "SEC"))
    col.put_evidence(_evidence("E2", _H2, "FRED"))
    verdict = assess_claim_independence(_claim(("E1", "E2")), col)
    assert isinstance(verdict, IndependenceVerdict)
    assert verdict.cited_count == 2
    assert verdict.distinct_origin_count == 2
    assert verdict.artificial_corroboration is False


def test_duplicate_content_hash_is_artificial_corroboration() -> None:
    # Two citations, same underlying document bytes (same content_hash) -> one real origin.
    col = EvidenceCollector()
    col.put_evidence(_evidence("E1", _H1, "SEC"))
    col.put_evidence(_evidence("E2", _H1, "mirror-site"))
    verdict = assess_claim_independence(_claim(("E1", "E2")), col)
    assert verdict.cited_count == 2
    assert verdict.distinct_origin_count == 1
    assert verdict.artificial_corroboration is True


def test_single_citation_is_not_flagged_as_artificial() -> None:
    col = EvidenceCollector()
    col.put_evidence(_evidence("E1", _H1, "SEC"))
    verdict = assess_claim_independence(_claim(("E1",)), col)
    assert verdict.cited_count == 1
    assert verdict.distinct_origin_count == 1
    # A single-source claim is not independently corroborated, but that is not *artificial*
    # corroboration (no overstated independence); it is simply single-sourced.
    assert verdict.artificial_corroboration is False
    assert verdict.single_sourced is True


def test_unresolved_citations_do_not_count_as_origins() -> None:
    col = EvidenceCollector()
    col.put_evidence(_evidence("E1", _H1, "SEC"))
    # E2 is cited but not preserved -> cannot be credited as an independent origin.
    verdict = assess_claim_independence(_claim(("E1", "E2")), col)
    assert verdict.cited_count == 1  # only resolvable evidence counts
    assert verdict.distinct_origin_count == 1
