"""Typed models for the prepare()/propose()/finalize() boundary.

Convention carried over from every prior phase: a model that wraps
another content-derived model uses that model's *ID string* in its own
identity-hash payload, never the full nested object — otherwise a nested
wall-clock field (e.g. ResearchRequest.created_at, RetrievalTrace.created_at)
would leak into an outer ID that is supposed to exclude wall-clock
content entirely.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from strix.canonical import make_id, sha256_hex
from strix.corpus.parsers.models import DocumentAnchor
from strix.research.models import (
    InformationRequirement,
    ResearchRequest,
    RetrievalTrace,
    ScoreComponents,
)


class PipelineModel(BaseModel):
    """Base for all strix.research.pipeline models: frozen, closed schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------
# prepare()
# --------------------------------------------------------------------------


class PreparationPolicy(PipelineModel):
    """Explicit policy for how prepare() handles a truncated corpus
    snapshot. Defaults closed: prepare() refuses to proceed unless this
    is set to explicitly permit it."""

    allow_incomplete_corpus: bool = False


class ParserVersionInfo(PipelineModel):
    """One distinct (parser, policy-versions) combination actually used
    while preparing this research — collected from the successful parse
    results, deduplicated and sorted by parser_name."""

    parser_name: str
    parser_version: str
    normalization_policy_version: str | None = None
    chunking_policy_version: str | None = None


class ParseResultIdentity(PipelineModel):
    """A content-derived pin on one document's exact parse outcome.

    ParseResult itself carries no ID of its own (Phase 6 never gave it
    one); result_hash is computed here, over the full ParseResult (it has
    no wall-clock field, so nothing needs excluding).
    """

    document_id: str
    status: str
    source_content_hash: str
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceItem(PipelineModel):
    """One piece of evidence in the bounded packet prepare() hands to
    propose() — a complete, unselected-content-free, independently
    verifiable copy of exactly one selected retrieval candidate.
    """

    document_id: str
    relative_path: str
    chunk_id: str
    anchor: DocumentAnchor
    #: The exact normalized chunk text.
    text: str
    #: SHA-256 of `text` — must equal anchor.normalized_content_hash.
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: The parent document's own content_hash — carried so a later phase
    #: can detect duplicate-content documents without re-touching the
    #: manifest, exactly mirroring strix.research.retrieval's own
    #: distinct_selected_content_hashes reasoning.
    document_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: ScoreComponents
    rank: int = Field(ge=1)

    @model_validator(mode="after")
    def _anchor_matches_document(self) -> EvidenceItem:
        if self.anchor.document_id != self.document_id:
            raise ValueError("anchor.document_id must match the evidence item's document_id")
        return self

    @model_validator(mode="after")
    def _hash_matches_recomputed_content(self) -> EvidenceItem:
        expected = sha256_hex(self.text.encode("utf-8"))
        if self.content_hash != expected:
            raise ValueError("content_hash does not match the recomputed hash of text")
        if self.anchor.normalized_content_hash != expected:
            raise ValueError(
                "anchor.normalized_content_hash does not match the recomputed hash of text"
            )
        return self


def _prepared_id_payload(
    request_id: str,
    corpus_id: str,
    manifest_content_hash: str,
    parser_versions: tuple[ParserVersionInfo, ...],
    parse_result_identities: tuple[ParseResultIdentity, ...],
    retrieval_trace_id: str,
    evidence_packet: tuple[EvidenceItem, ...],
    warnings: tuple[str, ...],
    incomplete: bool,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "corpus_id": corpus_id,
        "manifest_content_hash": manifest_content_hash,
        "parser_versions": list(parser_versions),
        "parse_result_identities": list(parse_result_identities),
        "retrieval_trace_id": retrieval_trace_id,
        "evidence_packet": list(evidence_packet),
        "warnings": list(warnings),
        "incomplete": incomplete,
    }


def compute_prepared_id(
    *,
    request_id: str,
    corpus_id: str,
    manifest_content_hash: str,
    parser_versions: tuple[ParserVersionInfo, ...],
    parse_result_identities: tuple[ParseResultIdentity, ...],
    retrieval_trace_id: str,
    evidence_packet: tuple[EvidenceItem, ...],
    warnings: tuple[str, ...],
    incomplete: bool,
) -> str:
    """Content-derived prepared identity — every field except ``created_at``."""
    return make_id(
        "PREPARED",
        _prepared_id_payload(
            request_id,
            corpus_id,
            manifest_content_hash,
            parser_versions,
            parse_result_identities,
            retrieval_trace_id,
            evidence_packet,
            warnings,
            incomplete,
        ),
    )


class PreparedResearch(PipelineModel):
    """The deterministic output of prepare(): everything propose() needs,
    and nothing it should not have — in particular, no unselected corpus
    content anywhere in ``evidence_packet``.
    """

    prepared_id: str
    request: ResearchRequest
    corpus_id: str
    manifest_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_versions: tuple[ParserVersionInfo, ...]
    parse_result_identities: tuple[ParseResultIdentity, ...]
    retrieval_trace: RetrievalTrace
    #: Stable order: (relative_path, anchor.start_line, chunk_id).
    evidence_packet: tuple[EvidenceItem, ...]
    warnings: tuple[str, ...] = ()
    incomplete: bool
    #: Wall clock — excluded from prepared_id; audit metadata only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _prepared_id_matches_content(self) -> PreparedResearch:
        expected = compute_prepared_id(
            request_id=self.request.request_id,
            corpus_id=self.corpus_id,
            manifest_content_hash=self.manifest_content_hash,
            parser_versions=self.parser_versions,
            parse_result_identities=self.parse_result_identities,
            retrieval_trace_id=self.retrieval_trace.trace_id,
            evidence_packet=self.evidence_packet,
            warnings=self.warnings,
            incomplete=self.incomplete,
        )
        if self.prepared_id != expected:
            raise ValueError(
                f"prepared_id {self.prepared_id!r} does not match its content "
                f"(expected {expected!r})"
            )
        return self

    @model_validator(mode="after")
    def _request_and_trace_corpus_match(self) -> PreparedResearch:
        if self.request.corpus_id != self.corpus_id:
            raise ValueError("request.corpus_id must match corpus_id")
        if self.retrieval_trace.corpus_id != self.corpus_id:
            raise ValueError("retrieval_trace.corpus_id must match corpus_id")
        return self

    @model_validator(mode="after")
    def _evidence_packet_is_ordered(self) -> PreparedResearch:
        keys = [
            (item.relative_path, item.anchor.start_line, item.chunk_id)
            for item in self.evidence_packet
        ]
        if keys != sorted(keys):
            raise ValueError(
                "evidence_packet must be ordered by (relative_path, anchor.start_line, chunk_id)"
            )
        return self

    @model_validator(mode="after")
    def _evidence_packet_matches_selected_candidates(self) -> PreparedResearch:
        selected_chunk_ids = {
            candidate.chunk_id
            for candidate in self.retrieval_trace.candidates
            if candidate.selected
        }
        packet_chunk_ids = {item.chunk_id for item in self.evidence_packet}
        if packet_chunk_ids != selected_chunk_ids:
            raise ValueError(
                "evidence_packet must contain exactly the retrieval trace's selected "
                "candidates — no more, no fewer"
            )
        return self


# --------------------------------------------------------------------------
# propose(): the provider-neutral seam
# --------------------------------------------------------------------------


class OutputSchemaIdentity(PipelineModel):
    """Identifies which typed output schema a provider's response must
    conform to — a label the provider and propose() both agree on, not
    a claim that propose() parses or enforces that schema beyond what
    this phase's structural checks already do."""

    schema_name: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)


class InferencePolicy(PipelineModel):
    """Explicit, typed policy governing one propose() call. Carries no
    network, filesystem, or tool permission of any kind — a provider
    that needs any of those gets them through its own constructor,
    never through this policy."""

    max_proposals: int = Field(default=20, ge=1)
    allow_insufficient_evidence_declaration: bool = True


class ProposalRequestContext(PipelineModel):
    """Everything a provider is told about the request's identity and
    intent. Deliberately not an escape hatch: no corpus_id-to-filesystem
    path, no CorpusStore, no credentials — just typed, already-decided
    request content.
    """

    request_id: str
    corpus_id: str
    question: str
    query_terms: tuple[str, ...]
    requested_information: tuple[InformationRequirement, ...]
    expected_value_types: tuple[str, ...]
    relevant_entities: tuple[str, ...]
    required_evidence_types: tuple[str, ...]


class EvidenceReference(PipelineModel):
    """A citation to exactly one evidence-packet item."""

    chunk_id: str
    document_id: str


class ProposedAssertion(PipelineModel):
    """One structured, cited factual/numeric assertion. The evidence_ref
    is mandatory — "every factual or numeric proposal must cite evidence
    packet chunk IDs" is enforced by this field being required, not by a
    policy toggle. Value is a plain string in this phase: no claim about
    value-type correctness is made here, only that a citation exists —
    that belongs to Phase 11 verification.
    """

    key: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence_ref: EvidenceReference


class UncertaintyLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UncertaintyDeclaration(PipelineModel):
    """A bounded, qualitative uncertainty level — never a probability, and
    never a claim of calibration (that belongs to evaluation, far later)."""

    description: str = Field(min_length=1)
    level: UncertaintyLevel


class MissingEvidenceDeclaration(PipelineModel):
    """The provider's explicit declaration that it could not find
    sufficient evidence to answer one requested_information key — a
    first-class non-answer. Lives on ProposalSet, not nested inside a
    ClaimProposal, since the model may declare this without producing
    any claim at all.
    """

    requirement_key: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ProposalStatus(StrEnum):
    #: The only value this phase's vocabulary has — provider output can
    #: never assign verification status, so there is nothing else to be.
    PROPOSED = "proposed"


def compute_proposal_id(
    statement: str,
    evidence_references: tuple[EvidenceReference, ...],
    assertions: tuple[ProposedAssertion, ...],
    uncertainty: tuple[UncertaintyDeclaration, ...],
) -> str:
    return make_id(
        "PROPOSAL",
        {
            "statement": statement,
            "evidence_references": list(evidence_references),
            "assertions": list(assertions),
            "uncertainty": list(uncertainty),
        },
    )


class ClaimProposal(PipelineModel):
    """One provider-proposed claim. Always PROPOSED — provider output can
    never assign verification status; that is a later-phase concern, and
    this model's vocabulary (ProposalStatus) has no other value to assign.
    """

    proposal_id: str
    statement: str = Field(min_length=1)
    evidence_references: tuple[EvidenceReference, ...] = Field(min_length=1)
    assertions: tuple[ProposedAssertion, ...] = ()
    uncertainty: tuple[UncertaintyDeclaration, ...] = ()
    status: ProposalStatus = ProposalStatus.PROPOSED

    @model_validator(mode="after")
    def _proposal_id_matches_content(self) -> ClaimProposal:
        expected = compute_proposal_id(
            self.statement, self.evidence_references, self.assertions, self.uncertainty
        )
        if self.proposal_id != expected:
            raise ValueError(
                f"proposal_id {self.proposal_id!r} does not match its content "
                f"(expected {expected!r})"
            )
        return self

    @model_validator(mode="after")
    def _assertions_cite_a_referenced_chunk(self) -> ClaimProposal:
        cited_chunk_ids = {ref.chunk_id for ref in self.evidence_references}
        for assertion in self.assertions:
            if assertion.evidence_ref.chunk_id not in cited_chunk_ids:
                raise ValueError(
                    f"assertion {assertion.key!r} cites chunk_id "
                    f"{assertion.evidence_ref.chunk_id!r}, which is not among this "
                    "claim's own evidence_references"
                )
        return self


class UsageInfo(PipelineModel):
    """Provider usage fields, when available. Deliberately not a claim
    about cost or a real tokenizer's count — see
    strix.research.retrieval.estimate_token_count for the project's one
    other token-adjacent field, which carries the same caveat."""

    input_units: int | None = Field(default=None, ge=0)
    output_units: int | None = Field(default=None, ge=0)


class ProviderResponse(PipelineModel):
    """What a ProposalProvider.propose() call returns. Not persisted on
    its own — propose() wraps this into a ProposalSet, which is."""

    model_identity: str = Field(min_length=1)
    proposals: tuple[ClaimProposal, ...] = ()
    missing_evidence: tuple[MissingEvidenceDeclaration, ...] = ()
    #: SHA-256 of the provider's raw response bytes/text, or — when no
    #: raw text exists (e.g. a structured test double) — of the
    #: canonical JSON representation of this response instead.
    raw_response_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    usage: UsageInfo | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    attempts: int = Field(default=1, ge=1)


def _proposal_set_id_payload(
    prepared_id: str,
    provider_name: str,
    provider_version: str,
    model_identity: str,
    prompt_version: str,
    output_schema: OutputSchemaIdentity,
    inference_policy: InferencePolicy,
    request_hash: str,
    response_hash: str,
    proposals: tuple[ClaimProposal, ...],
    missing_evidence: tuple[MissingEvidenceDeclaration, ...],
) -> dict[str, object]:
    return {
        "prepared_id": prepared_id,
        "provider_name": provider_name,
        "provider_version": provider_version,
        "model_identity": model_identity,
        "prompt_version": prompt_version,
        "output_schema": output_schema,
        "inference_policy": inference_policy,
        "request_hash": request_hash,
        "response_hash": response_hash,
        "proposals": list(proposals),
        "missing_evidence": list(missing_evidence),
    }


def compute_proposal_set_id(
    *,
    prepared_id: str,
    provider_name: str,
    provider_version: str,
    model_identity: str,
    prompt_version: str,
    output_schema: OutputSchemaIdentity,
    inference_policy: InferencePolicy,
    request_hash: str,
    response_hash: str,
    proposals: tuple[ClaimProposal, ...],
    missing_evidence: tuple[MissingEvidenceDeclaration, ...],
) -> str:
    """Content-derived proposal-set identity.

    Excludes ``created_at`` (wall clock) and also ``usage``/``latency_ms``/
    ``attempts`` — execution measurements, not part of *what* was
    proposed; two calls that happen to differ only in latency are still
    "the same proposal set." Proposal generation itself is not assumed
    reproducible, so this identity describes the record that was made,
    not a guarantee that repeating the call reproduces it.
    """
    return make_id(
        "PROPOSALSET",
        _proposal_set_id_payload(
            prepared_id,
            provider_name,
            provider_version,
            model_identity,
            prompt_version,
            output_schema,
            inference_policy,
            request_hash,
            response_hash,
            proposals,
            missing_evidence,
        ),
    )


class ProposalSet(PipelineModel):
    """The recorded result of one propose() call."""

    proposal_set_id: str
    prepared_id: str
    provider_name: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    model_identity: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    output_schema: OutputSchemaIdentity
    inference_policy: InferencePolicy
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposals: tuple[ClaimProposal, ...] = ()
    missing_evidence: tuple[MissingEvidenceDeclaration, ...] = ()
    usage: UsageInfo | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    attempts: int = Field(default=1, ge=1)
    #: Wall clock — excluded from proposal_set_id; audit metadata only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _proposal_set_id_matches_content(self) -> ProposalSet:
        expected = compute_proposal_set_id(
            prepared_id=self.prepared_id,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            model_identity=self.model_identity,
            prompt_version=self.prompt_version,
            output_schema=self.output_schema,
            inference_policy=self.inference_policy,
            request_hash=self.request_hash,
            response_hash=self.response_hash,
            proposals=self.proposals,
            missing_evidence=self.missing_evidence,
        )
        if self.proposal_set_id != expected:
            raise ValueError(
                f"proposal_set_id {self.proposal_set_id!r} does not match its content "
                f"(expected {expected!r})"
            )
        return self


# --------------------------------------------------------------------------
# finalize(): structural checks only — nothing here is a trust decision
# --------------------------------------------------------------------------


def compute_pending_id(
    prepared_id: str,
    proposal_set_id: str,
    requires_verification: bool,
    warnings: tuple[str, ...],
) -> str:
    """Content-derived pending-result identity.

    Uses prepared_id/proposal_set_id (not the full nested objects) so
    that repeating finalize() with the same prepared and proposal
    records always produces the same ID, with no wall-clock leakage
    through either nested object's own created_at field.
    """
    return make_id(
        "PENDING",
        {
            "prepared_id": prepared_id,
            "proposal_set_id": proposal_set_id,
            "requires_verification": requires_verification,
            "warnings": list(warnings),
        },
    )


class PendingResearchResult(PipelineModel):
    """The output of finalize(): structurally valid, and explicitly,
    permanently NOT verified. ``requires_verification`` is always True in
    this phase — there is no code path that can set it False; that
    requires Phase 11's semantic verification.
    """

    pending_id: str
    prepared: PreparedResearch
    proposal_set: ProposalSet
    requires_verification: bool = True
    warnings: tuple[str, ...] = ()
    #: Wall clock — excluded from pending_id; audit metadata only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _requires_verification_is_always_true(self) -> PendingResearchResult:
        if not self.requires_verification:
            raise ValueError(
                "requires_verification must always be True in this phase — no "
                "Phase 9 result may be marked verified"
            )
        return self

    @model_validator(mode="after")
    def _pending_id_matches_content(self) -> PendingResearchResult:
        expected = compute_pending_id(
            self.prepared.prepared_id,
            self.proposal_set.proposal_set_id,
            self.requires_verification,
            self.warnings,
        )
        if self.pending_id != expected:
            raise ValueError(
                f"pending_id {self.pending_id!r} does not match its content (expected {expected!r})"
            )
        return self

    @model_validator(mode="after")
    def _proposal_set_references_this_prepared_result(self) -> PendingResearchResult:
        if self.proposal_set.prepared_id != self.prepared.prepared_id:
            raise ValueError("proposal_set.prepared_id must match prepared.prepared_id")
        return self
