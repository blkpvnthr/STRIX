"""finalize(): structural validation only — PreparedResearch + ProposalSet
-> PendingResearchResult. No semantic verification, no trusted report, no
persistence, no replay: those are Phase 11. Deterministic: repeating
this call with the same prepared and proposal records always produces
the same pending_id.
"""

from __future__ import annotations

from datetime import UTC, datetime

from strix.errors import (
    PreparedProposalMismatchError,
    UnknownCitationError,
    VerificationStatusInjectionError,
)
from strix.research.pipeline.models import (
    ClaimProposal,
    EvidenceItem,
    PendingResearchResult,
    PreparedResearch,
    ProposalSet,
    ProposalStatus,
    compute_pending_id,
)


def finalize(prepared: PreparedResearch, proposal_set: ProposalSet) -> PendingResearchResult:
    """Structurally validate *proposal_set* against *prepared* and
    return a :class:`PendingResearchResult` that always requires Phase
    11 verification — nothing this function does can mark anything
    verified.

    Checks, in order: *proposal_set.prepared_id* matches
    *prepared.prepared_id*; every proposal's status is PROPOSED (an
    independent re-check — see :class:`~strix.errors.
    VerificationStatusInjectionError`'s docstring for why this is not
    only trusted to the model's own validator); and every citation
    (both a claim's own ``evidence_references`` and every assertion's
    ``evidence_ref``) resolves to a real evidence-packet item with a
    matching ``document_id`` — no unknown evidence is ever silently
    accepted.
    """
    if proposal_set.prepared_id != prepared.prepared_id:
        raise PreparedProposalMismatchError(
            f"proposal_set.prepared_id {proposal_set.prepared_id!r} does not match "
            f"prepared.prepared_id {prepared.prepared_id!r}"
        )

    evidence_by_chunk_id = {item.chunk_id: item for item in prepared.evidence_packet}

    for claim in proposal_set.proposals:
        _check_status_not_injected(claim)
        _check_citations_resolve(claim, evidence_by_chunk_id)

    warnings: list[str] = []
    if not proposal_set.proposals and not proposal_set.missing_evidence:
        warnings.append(
            "the proposal set contains neither a claim nor a missing-evidence "
            "declaration; the provider returned nothing to account for"
        )
    if prepared.incomplete:
        warnings.append(
            "prepared research came from an incomplete corpus; structural "
            "validation does not make this exhaustive"
        )

    requires_verification = True
    pending_id = compute_pending_id(
        prepared.prepared_id, proposal_set.proposal_set_id, requires_verification, tuple(warnings)
    )

    return PendingResearchResult(
        pending_id=pending_id,
        prepared=prepared,
        proposal_set=proposal_set,
        requires_verification=requires_verification,
        warnings=tuple(warnings),
        created_at=datetime.now(UTC),
    )


def _check_status_not_injected(claim: ClaimProposal) -> None:
    if claim.status is not ProposalStatus.PROPOSED:
        raise VerificationStatusInjectionError(
            f"proposal {claim.proposal_id!r} carries status {claim.status!r}, not "
            "PROPOSED — provider output can never assign verification status"
        )


def _check_citations_resolve(
    claim: ClaimProposal, evidence_by_chunk_id: dict[str, EvidenceItem]
) -> None:
    for ref in claim.evidence_references:
        item = evidence_by_chunk_id.get(ref.chunk_id)
        if item is None:
            raise UnknownCitationError(
                f"proposal {claim.proposal_id!r} cites chunk_id {ref.chunk_id!r}, "
                "which is not in the evidence packet"
            )
        if item.document_id != ref.document_id:
            raise UnknownCitationError(
                f"proposal {claim.proposal_id!r} cites chunk_id {ref.chunk_id!r} with "
                f"document_id {ref.document_id!r}, but that chunk belongs to document "
                f"{item.document_id!r}"
            )
    for assertion in claim.assertions:
        ref = assertion.evidence_ref
        item = evidence_by_chunk_id.get(ref.chunk_id)
        if item is None:
            raise UnknownCitationError(
                f"proposal {claim.proposal_id!r} assertion {assertion.key!r} cites "
                f"chunk_id {ref.chunk_id!r}, which is not in the evidence packet"
            )
        if item.document_id != ref.document_id:
            raise UnknownCitationError(
                f"proposal {claim.proposal_id!r} assertion {assertion.key!r} cites "
                f"chunk_id {ref.chunk_id!r} with document_id {ref.document_id!r}, but "
                f"that chunk belongs to document {item.document_id!r}"
            )
