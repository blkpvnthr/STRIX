"""Tests for the unified supporting-documentation + citation-mapping contract.

Master spec §7/§15 ("Supporting documentation" as genuine numbered references that
inline numbered citations resolve to) and §30 citation-integrity targets:
required documentation completeness, citation-mapping integrity, and
material-claim traceability — all 100% for authorized outputs.

The contract is the single source of truth all surfaces (CLI/API/React/workers)
render, replacing the ad-hoc numbering previously computed only inside the text
renderer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from strix.agent.documentation import (
    BibliographicMetadata,
    ReferenceDocument,
    SupportingDocumentation,
    build_supporting_documentation,
)
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentEvidence,
    AgentVerificationStatus,
    ClaimVerification,
    ResearchAnswer,
    ResearchResponse,
    SourceKind,
)

_NOW = datetime(2026, 11, 23, tzinfo=UTC)
_HASH = "a" * 64
_HASH2 = "b" * 64


def _evidence(evidence_id: str, hash_: str, **kw: object) -> AgentEvidence:
    return AgentEvidence(
        evidence_id=evidence_id,
        source_type=SourceKind.WEB_PAGE,
        provider="Example",
        source_title=f"Title {evidence_id}",
        retrieved_at=_NOW,
        content_hash=hash_,
        **kw,  # type: ignore[arg-type]
    )


def _verified_claim(claim_id: str, evidence_ids: tuple[str, ...]) -> AgentClaim:
    return AgentClaim(
        claim_id=claim_id,
        claim_type=AgentClaimType.QUANTITATIVE,
        statement=f"statement {claim_id}",
        evidence_ids=evidence_ids,
        verification=ClaimVerification(status=AgentVerificationStatus.VERIFIED),
    )


def _response(
    *,
    sources: tuple[AgentEvidence, ...],
    verified_claims: tuple[AgentClaim, ...],
) -> ResearchResponse:
    answer = ResearchAnswer(
        run_id="RUN-DOC",
        question="q",
        data_as_of=_NOW,
        summary="s",
        verified_claims=verified_claims,
        unresolved_claims=(),
        evidence=sources,
        limitations=(),
        disclaimer="d",
    )
    return ResearchResponse(
        run_id="RUN-DOC",
        question="q",
        question_intent="intent",
        direct_answer="the answer",
        analysis="analysis",
        sources=sources,
        verified_answer=answer,
    )


def test_references_are_numbered_from_one_in_source_order() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH), _evidence("EV-2", _HASH2)),
        verified_claims=(
            _verified_claim("CL-1", ("EV-1",)),
            _verified_claim("CL-2", ("EV-2",)),
        ),
    )
    doc = build_supporting_documentation(resp)
    assert isinstance(doc, SupportingDocumentation)
    assert [r.number for r in doc.references] == [1, 2]
    assert doc.references[0].evidence_id == "EV-1"
    assert doc.references[1].evidence_id == "EV-2"


def test_each_material_claim_maps_to_its_reference_numbers() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH), _evidence("EV-2", _HASH2)),
        verified_claims=(_verified_claim("CL-1", ("EV-2", "EV-1")),),
    )
    doc = build_supporting_documentation(resp)
    # Numbers are sorted ascending regardless of citation order in the claim.
    assert doc.claim_citations["CL-1"] == (1, 2)


def test_full_mapping_is_complete_with_no_defects() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH), _evidence("EV-2", _HASH2)),
        verified_claims=(
            _verified_claim("CL-1", ("EV-1",)),
            _verified_claim("CL-2", ("EV-2",)),
        ),
    )
    doc = build_supporting_documentation(resp)
    assert doc.integrity.complete is True
    assert doc.integrity.uncited_claims == ()
    assert doc.integrity.orphan_references == ()
    assert doc.integrity.dangling_markers == ()


def test_dangling_marker_when_claim_cites_absent_evidence() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH),),
        verified_claims=(_verified_claim("CL-1", ("EV-1", "EV-MISSING")),),
    )
    doc = build_supporting_documentation(resp)
    assert "EV-MISSING" in doc.integrity.dangling_markers
    assert doc.integrity.complete is False
    # The resolvable part is still mapped.
    assert doc.claim_citations["CL-1"] == (1,)


def test_material_claim_with_no_resolvable_citation_is_uncited() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH),),
        verified_claims=(_verified_claim("CL-ORPHAN", ()),),
    )
    doc = build_supporting_documentation(resp)
    assert "CL-ORPHAN" in doc.integrity.uncited_claims
    assert doc.integrity.complete is False


def test_orphan_reference_when_source_cited_by_no_claim() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH), _evidence("EV-2", _HASH2)),
        verified_claims=(_verified_claim("CL-1", ("EV-1",)),),
    )
    doc = build_supporting_documentation(resp)
    # EV-2 is reference #2 but no verified claim cites it.
    assert doc.integrity.orphan_references == (2,)
    # Orphans are reported but do not by themselves break material-claim traceability.
    assert doc.integrity.uncited_claims == ()
    assert doc.integrity.dangling_markers == ()


def test_rich_bibliographic_metadata_flows_into_reference() -> None:
    biblio = BibliographicMetadata(
        authors=("Ada Lovelace", "Alan Turing"),
        doi="10.1000/xyz123",
        pdf_url="https://example.org/paper.pdf",
        pages="12-18",
        sections="§3.2",
        dataset_id="DS-42",
        data_timestamp="2026-01-01T00:00:00Z",
        methodology="period_return v1",
    )
    ev = _evidence(
        "EV-1",
        _HASH,
        source_url="https://example.org/paper",
        published_at=_NOW,
        bibliographic=biblio,
    )
    resp = _response(sources=(ev,), verified_claims=(_verified_claim("CL-1", ("EV-1",)),))
    ref = build_supporting_documentation(resp).references[0]
    assert isinstance(ref, ReferenceDocument)
    assert ref.authors == ("Ada Lovelace", "Alan Turing")
    assert ref.doi == "10.1000/xyz123"
    assert ref.pdf_url == "https://example.org/paper.pdf"
    assert ref.pages == "12-18"
    assert ref.sections == "§3.2"
    assert ref.dataset_id == "DS-42"
    assert ref.data_timestamp == "2026-01-01T00:00:00Z"
    assert ref.methodology == "period_return v1"
    assert ref.title == "Title EV-1"
    assert ref.url == "https://example.org/paper"
    assert ref.content_hash == _HASH


def test_build_is_deterministic() -> None:
    resp = _response(
        sources=(_evidence("EV-1", _HASH), _evidence("EV-2", _HASH2)),
        verified_claims=(_verified_claim("CL-1", ("EV-1",)),),
    )
    a = build_supporting_documentation(resp)
    b = build_supporting_documentation(resp)
    assert a == b
