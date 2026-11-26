"""The CLI text renderer renders the SAME unified supporting-documentation
contract (spec §7/§15) the API and frontend use — including rich reference
metadata (authors, DOI, pages) when present."""

from __future__ import annotations

from datetime import UTC, datetime

from strix.agent.documentation import build_supporting_documentation
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentEvidence,
    AgentVerificationStatus,
    BibliographicMetadata,
    ClaimVerification,
    EpistemicClass,
    ResearchAnswer,
    ResearchResponse,
    SourceKind,
    SupportingFact,
)
from strix.agent.response_builder import render_response

_NOW = datetime(2026, 11, 23, tzinfo=UTC)


def _response_with_rich_source() -> ResearchResponse:
    ev = AgentEvidence(
        evidence_id="EV-1",
        source_type=SourceKind.WEB_PAGE,
        provider="Journal of Examples",
        source_title="On Verifiable Evidence",
        source_url="https://example.org/paper",
        retrieved_at=_NOW,
        published_at=_NOW,
        content_hash="a" * 64,
        bibliographic=BibliographicMetadata(
            authors=("Ada Lovelace",),
            doi="10.1000/xyz123",
            pages="12-18",
        ),
    )
    claim = AgentClaim(
        claim_id="CL-1",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement="a verified statement",
        evidence_ids=("EV-1",),
        verification=ClaimVerification(status=AgentVerificationStatus.VERIFIED),
    )
    answer = ResearchAnswer(
        run_id="RUN-R",
        question="q",
        data_as_of=_NOW,
        summary="s",
        verified_claims=(claim,),
        unresolved_claims=(),
        evidence=(ev,),
        limitations=(),
        disclaimer="not advice",
    )
    return ResearchResponse(
        run_id="RUN-R",
        question="q",
        question_intent="intent",
        direct_answer="the answer",
        analysis="",
        supporting_facts=(
            SupportingFact(
                claim_id="CL-1",
                statement="a verified statement",
                epistemic_class=EpistemicClass.VERIFIED_FACT,
                evidence_ids=("EV-1",),
            ),
        ),
        sources=(ev,),
        verified_answer=answer,
    )


def test_rendered_sources_include_rich_reference_metadata() -> None:
    out = render_response(_response_with_rich_source())
    assert "10.1000/xyz123" in out  # DOI
    assert "Ada Lovelace" in out  # author
    assert "12-18" in out  # pages
    assert "On Verifiable Evidence" in out  # title


def test_rendered_citation_numbers_match_the_contract() -> None:
    resp = _response_with_rich_source()
    doc = build_supporting_documentation(resp)
    out = render_response(resp)
    # The reference number the contract assigns EV-1 appears as an inline [n] mark.
    number = doc.references[0].number
    assert f"[{number}]" in out
