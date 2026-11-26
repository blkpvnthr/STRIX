"""Unified supporting-documentation + citation-mapping contract (spec §7/§15).

Every substantive research response must present genuine numbered references
*below* the answer, and every consequential factual claim must be traceable to
the evidence that supports it (master spec §15). This module is the single
source of truth for that mapping — it replaces the ad-hoc numbering previously
computed only inside the text renderer, so the CLI, FastAPI, React frontend, and
workers all render the *same* numbered references from the *same* contract.

The contract also surfaces the integrity signals the §30 success criteria track:
required documentation completeness, citation-mapping integrity, and
material-claim traceability (targets 100% for authorized outputs). It does not
re-synthesize or re-verify anything; it is a deterministic, side-effect-free view
over an already-verified :class:`~strix.agent.models.ResearchResponse`.
"""

from __future__ import annotations

from strix.agent.models import AgentEvidence, BibliographicMetadata, ResearchResponse
from strix.models import StrixModel

__all__ = [
    "BibliographicMetadata",
    "CitationMappingIntegrity",
    "ReferenceDocument",
    "SupportingDocumentation",
    "build_supporting_documentation",
]


class ReferenceDocument(StrixModel):
    """One genuine numbered reference in the supporting-documentation section.

    ``number`` is the 1-based index an inline ``[n]`` citation resolves to. The
    rich fields (authors, DOI, pages, dataset id, methodology) are populated from
    the source's optional :class:`~strix.agent.models.BibliographicMetadata`;
    whatever is absent is simply omitted — never fabricated.
    """

    number: int
    evidence_id: str
    title: str
    provider: str
    url: str | None = None
    published_date: str | None = None
    content_hash: str
    authors: tuple[str, ...] = ()
    doi: str | None = None
    pdf_url: str | None = None
    pages: str | None = None
    sections: str | None = None
    dataset_id: str | None = None
    data_timestamp: str | None = None
    methodology: str | None = None
    #: Claim ids (material, verified) that cite this reference.
    cited_by_claim_ids: tuple[str, ...] = ()


class CitationMappingIntegrity(StrixModel):
    """Integrity of the inline-citation → reference → claim mapping (§30).

    ``complete`` is the headline material-claim-traceability signal: it is True
    iff every material (verified) claim resolves to at least one reference and no
    claim cites an evidence id that is absent from the documentation. Orphan
    references (sources cited by no claim) are reported for quality but do not, by
    themselves, break material-claim traceability.
    """

    complete: bool
    #: Material claims that resolve to zero references (traceability failure).
    uncited_claims: tuple[str, ...]
    #: Reference numbers cited by no material claim (quality signal only).
    orphan_references: tuple[int, ...]
    #: Evidence ids cited by a claim but absent from the documentation.
    dangling_markers: tuple[str, ...]


class SupportingDocumentation(StrixModel):
    """The numbered references plus the claim→reference citation mapping."""

    references: tuple[ReferenceDocument, ...]
    #: claim_id -> the reference numbers it cites, sorted ascending.
    claim_citations: dict[str, tuple[int, ...]]
    integrity: CitationMappingIntegrity


def _reference(number: int, ev: AgentEvidence) -> ReferenceDocument:
    biblio = ev.bibliographic
    published = ev.published_at.date().isoformat() if ev.published_at is not None else None
    return ReferenceDocument(
        number=number,
        evidence_id=ev.evidence_id,
        title=ev.source_title,
        provider=ev.provider,
        url=ev.source_url,
        published_date=published,
        content_hash=ev.content_hash,
        authors=biblio.authors if biblio is not None else (),
        doi=biblio.doi if biblio is not None else None,
        pdf_url=biblio.pdf_url if biblio is not None else None,
        pages=biblio.pages if biblio is not None else None,
        sections=biblio.sections if biblio is not None else None,
        dataset_id=biblio.dataset_id if biblio is not None else None,
        data_timestamp=biblio.data_timestamp if biblio is not None else None,
        methodology=biblio.methodology if biblio is not None else None,
    )


def build_supporting_documentation(response: ResearchResponse) -> SupportingDocumentation:
    """Build the unified supporting-documentation contract for ``response``.

    References are numbered 1..N in the order sources appear on the response.
    Each material (independently verified) claim is mapped to the reference
    numbers of the evidence it cites; unresolvable citations, uncited material
    claims, and orphan references are recorded in the integrity block. The result
    is deterministic and side-effect-free.
    """
    number_by_evidence: dict[str, int] = {}
    references: list[ReferenceDocument] = []
    for ev in response.sources:
        if ev.evidence_id in number_by_evidence:
            continue  # stable de-dup: first occurrence wins
        number = len(references) + 1
        number_by_evidence[ev.evidence_id] = number
        references.append(_reference(number, ev))

    material_claims = response.verified_answer.verified_claims
    claim_citations: dict[str, tuple[int, ...]] = {}
    cited_by: dict[int, list[str]] = {}
    uncited_claims: list[str] = []
    dangling: list[str] = []
    seen_dangling: set[str] = set()

    for claim in material_claims:
        numbers: set[int] = set()
        for eid in claim.evidence_ids:
            num = number_by_evidence.get(eid)
            if num is None:
                if eid not in seen_dangling:
                    seen_dangling.add(eid)
                    dangling.append(eid)
                continue
            numbers.add(num)
            cited_by.setdefault(num, []).append(claim.claim_id)
        claim_citations[claim.claim_id] = tuple(sorted(numbers))
        if not numbers:
            uncited_claims.append(claim.claim_id)

    references = [
        ref.model_copy(update={"cited_by_claim_ids": tuple(cited_by.get(ref.number, ()))})
        for ref in references
    ]
    orphan_references = tuple(
        ref.number for ref in references if not ref.cited_by_claim_ids
    )

    integrity = CitationMappingIntegrity(
        complete=not uncited_claims and not dangling,
        uncited_claims=tuple(uncited_claims),
        orphan_references=orphan_references,
        dangling_markers=tuple(dangling),
    )
    return SupportingDocumentation(
        references=tuple(references),
        claim_citations=claim_citations,
        integrity=integrity,
    )
