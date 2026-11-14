"""propose(): the one seam that may call a non-deterministic provider.

The provider-neutral :class:`ProposalProvider` protocol is deliberately
narrow — see its docstring for exactly what it does and does not receive.
No production, OpenAI, or network provider is defined here; only the
protocol and the orchestration that wraps whatever a provider returns
into a recorded :class:`~strix.research.pipeline.models.ProposalSet`. A
deterministic test double may be defined under ``tests/`` only (Phase 10
adds the real fake and stored provider implementations).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from strix.canonical import canonical_hash
from strix.errors import (
    MalformedProposalError,
    ProviderFailureError,
    VerificationStatusInjectionError,
)
from strix.research.pipeline.models import (
    EvidenceItem,
    InferencePolicy,
    OutputSchemaIdentity,
    PreparedResearch,
    ProposalRequestContext,
    ProposalSet,
    ProposalStatus,
    ProviderResponse,
    compute_proposal_set_id,
)


class ProposalProvider(Protocol):
    """The seam an inference provider plugs into.

    Receives only: a :class:`ProposalRequestContext` (typed request
    identity/intent — no filesystem path, no CorpusStore, no
    credentials); the bounded evidence packet (nothing outside what
    prepare() selected); an :class:`OutputSchemaIdentity`; and an
    :class:`InferencePolicy`. Never receives a network handle, a tool
    handle, or any document prepare() did not select — a provider that
    needs network access gets it through its own constructor, never
    through this call.
    """

    provider_name: str
    provider_version: str

    def propose(
        self,
        context: ProposalRequestContext,
        evidence: tuple[EvidenceItem, ...],
        schema: OutputSchemaIdentity,
        policy: InferencePolicy,
    ) -> ProviderResponse: ...


def propose(
    prepared: PreparedResearch,
    provider: ProposalProvider,
    *,
    schema: OutputSchemaIdentity,
    policy: InferencePolicy | None = None,
    prompt_version: str = "1.0.0",
    created_at: datetime | None = None,
) -> ProposalSet:
    """Call *provider* with exactly the narrow inputs its protocol
    allows, and record the result as a :class:`ProposalSet`.

    Raises :class:`~strix.errors.ProviderFailureError` if *provider*
    itself raises, :class:`~strix.errors.MalformedProposalError` if the
    response violates a structural rule this orchestration enforces
    (currently: ``len(proposals) <= policy.max_proposals``), and
    :class:`~strix.errors.VerificationStatusInjectionError` if any
    returned proposal's status is not PROPOSED.

    Proposal generation itself is not assumed reproducible — unlike
    ``prepare()``/``finalize()``, repeating this call is not guaranteed
    to produce the same ``ProposalSet``; that is the provider's
    responsibility, not this orchestration's.
    """
    resolved_policy = policy if policy is not None else InferencePolicy()

    context = ProposalRequestContext(
        request_id=prepared.request.request_id,
        corpus_id=prepared.corpus_id,
        question=prepared.request.question,
        query_terms=prepared.request.query_terms,
        requested_information=prepared.request.requested_information,
        expected_value_types=prepared.request.expected_value_types,
        relevant_entities=prepared.request.relevant_entities,
        required_evidence_types=prepared.request.required_evidence_types,
    )
    request_hash = canonical_hash(
        {
            "context": context,
            "evidence": list(prepared.evidence_packet),
            "schema": schema,
            "policy": resolved_policy,
        }
    )

    try:
        response = provider.propose(context, prepared.evidence_packet, schema, resolved_policy)
    except Exception as exc:
        raise ProviderFailureError(
            f"provider {provider.provider_name!r} ({provider.provider_version}) failed: {exc}"
        ) from exc

    if len(response.proposals) > resolved_policy.max_proposals:
        raise MalformedProposalError(
            f"provider returned {len(response.proposals)} proposals, exceeding "
            f"policy.max_proposals={resolved_policy.max_proposals}"
        )
    for claim in response.proposals:
        if claim.status is not ProposalStatus.PROPOSED:
            raise VerificationStatusInjectionError(
                f"proposal {claim.proposal_id!r} carries status {claim.status!r}, not PROPOSED"
            )

    proposal_set_id = compute_proposal_set_id(
        prepared_id=prepared.prepared_id,
        provider_name=provider.provider_name,
        provider_version=provider.provider_version,
        model_identity=response.model_identity,
        prompt_version=prompt_version,
        output_schema=schema,
        inference_policy=resolved_policy,
        request_hash=request_hash,
        response_hash=response.raw_response_hash,
        proposals=response.proposals,
        missing_evidence=response.missing_evidence,
    )

    return ProposalSet(
        proposal_set_id=proposal_set_id,
        prepared_id=prepared.prepared_id,
        provider_name=provider.provider_name,
        provider_version=provider.provider_version,
        model_identity=response.model_identity,
        prompt_version=prompt_version,
        output_schema=schema,
        inference_policy=resolved_policy,
        request_hash=request_hash,
        response_hash=response.raw_response_hash,
        proposals=response.proposals,
        missing_evidence=response.missing_evidence,
        usage=response.usage,
        latency_ms=response.latency_ms,
        attempts=response.attempts,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )
