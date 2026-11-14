"""Typed models for research requests and retrieval traces.

A :class:`ResearchRequest` is a fully preserved, replayable description of
one retrieval request, scoped to exactly one corpus. A
:class:`RetrievalTrace` is the content-derived, replayable record of one
retrieval run against it. Both carry content-derived IDs excluding every
wall-clock field, the same convention as every other identity in STRIX
(``strix.canonical.make_id``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from strix.canonical import make_id
from strix.research.normalize import tokenize


class ResearchModel(BaseModel):
    """Base for all strix.research models: frozen, closed schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class InformationRequirement(ResearchModel):
    """One discrete piece of information the request needs answered."""

    key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True


class DocumentFilter(ResearchModel):
    """Allow/exclude lists over document identity, path, and extension.

    Each dimension (document_id, relative_path, extension) is validated
    independently: a value present in both that dimension's allowed and
    excluded lists is a contradiction, rejected at construction.
    """

    allowed_document_ids: tuple[str, ...] = ()
    excluded_document_ids: tuple[str, ...] = ()
    allowed_relative_paths: tuple[str, ...] = ()
    excluded_relative_paths: tuple[str, ...] = ()
    #: Lowercase, with leading dot (e.g. ".txt") — compared case-insensitively.
    allowed_extensions: tuple[str, ...] = ()
    excluded_extensions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _no_contradictions(self) -> DocumentFilter:
        if set(self.allowed_document_ids) & set(self.excluded_document_ids):
            raise ValueError("a document_id cannot be both allowed and excluded")
        if set(self.allowed_relative_paths) & set(self.excluded_relative_paths):
            raise ValueError("a relative_path cannot be both allowed and excluded")
        if set(self.allowed_extensions) & set(self.excluded_extensions):
            raise ValueError("an extension cannot be both allowed and excluded")
        return self


class RetrievalBudget(ResearchModel):
    """Deterministic bounds applied, in order, during retrieval.

    minimum_score is the cutoff threshold (selection step 3); the five
    limits below correspond to the "candidate, selection, per-document,
    character, and compute limits" this phase requires — max_query_terms
    is the compute limit: it bounds the multiplicative blow-up of
    candidates x query terms examined during scoring, since there is no
    wall-clock timeout anywhere in this deterministic pipeline.
    """

    minimum_score: Decimal = Field(default=Decimal(0), ge=0)
    max_candidate_chunks: int = Field(default=10_000, ge=1)
    max_selected_chunks: int = Field(default=50, ge=1)
    max_chunks_per_document: int = Field(default=10, ge=1)
    max_selected_characters: int = Field(default=20_000, ge=1)
    max_query_terms: int = Field(default=64, ge=1)

    @model_validator(mode="after")
    def _budget_is_achievable(self) -> RetrievalBudget:
        if self.max_selected_chunks > self.max_candidate_chunks:
            raise ValueError("max_selected_chunks cannot exceed max_candidate_chunks")
        return self


class CorroborationRequirement(ResearchModel):
    """How many distinct documents a requirement needs support from.

    Retrieval only ever counts distinct document_ids in the selected set
    against this — it makes no claim that those documents independently
    corroborate anything, and duplicate content (e.g. a renamed copy)
    must never inflate this count. See RetrievalTrace's docstring.
    """

    minimum_independent_documents: int = Field(default=1, ge=1)


class DateConstraint(ResearchModel):
    """An applicable date or as-of constraint, where available.

    Not yet enforced during retrieval in this phase — no corpus document
    model carries a date field to compare against yet. Carried on the
    request for later phases; retrieval neither reads nor applies it.
    """

    as_of_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> DateConstraint:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must not be after end_date")
        return self


def _request_id_payload(
    corpus_id: str,
    question: str,
    query_terms: tuple[str, ...],
    requested_information: tuple[InformationRequirement, ...],
    expected_value_types: tuple[str, ...],
    relevant_entities: tuple[str, ...],
    required_evidence_types: tuple[str, ...],
    corroboration: CorroborationRequirement,
    date_constraint: DateConstraint,
    document_filter: DocumentFilter,
    budget: RetrievalBudget,
) -> dict[str, object]:
    return {
        "corpus_id": corpus_id,
        "question": question,
        "query_terms": list(query_terms),
        "requested_information": list(requested_information),
        "expected_value_types": list(expected_value_types),
        "relevant_entities": list(relevant_entities),
        "required_evidence_types": list(required_evidence_types),
        "corroboration": corroboration,
        "date_constraint": date_constraint,
        "document_filter": document_filter,
        "budget": budget,
    }


def compute_request_id(
    *,
    corpus_id: str,
    question: str,
    query_terms: tuple[str, ...],
    requested_information: tuple[InformationRequirement, ...] = (),
    expected_value_types: tuple[str, ...] = (),
    relevant_entities: tuple[str, ...] = (),
    required_evidence_types: tuple[str, ...] = (),
    corroboration: CorroborationRequirement | None = None,
    date_constraint: DateConstraint | None = None,
    document_filter: DocumentFilter | None = None,
    budget: RetrievalBudget | None = None,
) -> str:
    """Content-derived request identity — every field except ``created_at``."""
    return make_id(
        "REQUEST",
        _request_id_payload(
            corpus_id,
            question,
            query_terms,
            requested_information,
            expected_value_types,
            relevant_entities,
            required_evidence_types,
            corroboration if corroboration is not None else CorroborationRequirement(),
            date_constraint if date_constraint is not None else DateConstraint(),
            document_filter if document_filter is not None else DocumentFilter(),
            budget if budget is not None else RetrievalBudget(),
        ),
    )


class ResearchRequest(ResearchModel):
    """A fully preserved, replayable description of one retrieval request,
    scoped to exactly one corpus (``corpus_id``) — retrieval rejects any
    attempt to run a request against a different corpus."""

    request_id: str
    corpus_id: str
    question: str = Field(min_length=1)
    #: Exact retrieval query terms, in execution order. Each entry may be
    #: a single word or a multi-word phrase (see strix.research.scoring).
    query_terms: tuple[str, ...] = Field(min_length=1)
    requested_information: tuple[InformationRequirement, ...] = ()
    expected_value_types: tuple[str, ...] = ()
    relevant_entities: tuple[str, ...] = ()
    required_evidence_types: tuple[str, ...] = ()
    corroboration: CorroborationRequirement = CorroborationRequirement()
    date_constraint: DateConstraint = DateConstraint()
    document_filter: DocumentFilter = DocumentFilter()
    budget: RetrievalBudget = RetrievalBudget()
    #: Wall clock — excluded from request_id; audit metadata only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _request_id_matches_content(self) -> ResearchRequest:
        expected = compute_request_id(
            corpus_id=self.corpus_id,
            question=self.question,
            query_terms=self.query_terms,
            requested_information=self.requested_information,
            expected_value_types=self.expected_value_types,
            relevant_entities=self.relevant_entities,
            required_evidence_types=self.required_evidence_types,
            corroboration=self.corroboration,
            date_constraint=self.date_constraint,
            document_filter=self.document_filter,
            budget=self.budget,
        )
        if self.request_id != expected:
            raise ValueError(
                f"request_id {self.request_id!r} does not match its content "
                f"(expected {expected!r}); construct via build_research_request()"
            )
        return self

    @model_validator(mode="after")
    def _query_terms_are_not_blank(self) -> ResearchRequest:
        # Whitespace- or punctuation-only terms tokenize to nothing, which
        # is just as invalid as an empty string -- checked with the real
        # tokenizer, not a naive .strip() check.
        if all(not tokenize(term) for term in self.query_terms):
            raise ValueError(
                "query_terms must contain at least one term that tokenizes to "
                "a non-empty query (not all blank or punctuation-only)"
            )
        return self

    @model_validator(mode="after")
    def _budget_can_satisfy_corroboration(self) -> ResearchRequest:
        if self.corroboration.minimum_independent_documents > self.budget.max_selected_chunks:
            raise ValueError(
                "corroboration.minimum_independent_documents cannot exceed "
                "budget.max_selected_chunks (at most one chunk per document in "
                "the best case)"
            )
        return self


def build_research_request(
    *,
    corpus_id: str,
    question: str,
    query_terms: tuple[str, ...],
    created_at: AwareDatetime,
    requested_information: tuple[InformationRequirement, ...] = (),
    expected_value_types: tuple[str, ...] = (),
    relevant_entities: tuple[str, ...] = (),
    required_evidence_types: tuple[str, ...] = (),
    corroboration: CorroborationRequirement | None = None,
    date_constraint: DateConstraint | None = None,
    document_filter: DocumentFilter | None = None,
    budget: RetrievalBudget | None = None,
) -> ResearchRequest:
    """Construct a ResearchRequest with its content-derived request_id set."""
    resolved_corroboration = (
        corroboration if corroboration is not None else CorroborationRequirement()
    )
    resolved_date_constraint = date_constraint if date_constraint is not None else DateConstraint()
    resolved_document_filter = document_filter if document_filter is not None else DocumentFilter()
    resolved_budget = budget if budget is not None else RetrievalBudget()
    request_id = compute_request_id(
        corpus_id=corpus_id,
        question=question,
        query_terms=query_terms,
        requested_information=requested_information,
        expected_value_types=expected_value_types,
        relevant_entities=relevant_entities,
        required_evidence_types=required_evidence_types,
        corroboration=resolved_corroboration,
        date_constraint=resolved_date_constraint,
        document_filter=resolved_document_filter,
        budget=resolved_budget,
    )
    return ResearchRequest(
        request_id=request_id,
        corpus_id=corpus_id,
        question=question,
        query_terms=query_terms,
        requested_information=requested_information,
        expected_value_types=expected_value_types,
        relevant_entities=relevant_entities,
        required_evidence_types=required_evidence_types,
        corroboration=resolved_corroboration,
        date_constraint=resolved_date_constraint,
        document_filter=resolved_document_filter,
        budget=resolved_budget,
        created_at=created_at,
    )


class ExclusionReason(StrEnum):
    FILTERED_DOCUMENT = "filtered_document"
    FILTERED_PATH_OR_EXTENSION = "filtered_path_or_extension"
    NO_QUERY_MATCH = "no_query_match"
    BELOW_CUTOFF = "below_cutoff"
    PER_DOCUMENT_CAP = "per_document_cap"
    CHUNK_COUNT_BUDGET = "chunk_count_budget"
    CHARACTER_BUDGET = "character_budget"


class ScoreComponents(ResearchModel):
    """Auditable breakdown of one candidate's lexical score. Integer/
    Decimal arithmetic only — no floating-point value anywhere."""

    term_frequency_score: Decimal = Field(ge=0)
    phrase_bonus: Decimal = Field(ge=0)
    total_score: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _total_matches_components(self) -> ScoreComponents:
        if self.total_score != self.term_frequency_score + self.phrase_bonus:
            raise ValueError("total_score must equal term_frequency_score + phrase_bonus")
        return self


class RetrievalCandidate(ResearchModel):
    """One candidate chunk: scored (or not) and either selected or
    excluded with a specific, typed reason. Never silently dropped."""

    chunk_id: str
    document_id: str
    relative_path: str
    #: The parent document's content_hash (from its DocumentArtifact) —
    #: lets a trace reader see when two selected documents are actually
    #: duplicate content at different paths, without cross-referencing
    #: the manifest.
    document_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_start_line: int = Field(ge=1)
    anchor_end_line: int = Field(ge=1)
    char_count: int = Field(ge=0)
    #: A labeled, versioned ESTIMATE only (see
    #: strix.research.retrieval.estimate_token_count) — never a real
    #: tokenizer count; no language-model tokenizer is used in this phase.
    estimated_token_count: int = Field(ge=0)
    #: None only for a candidate excluded before scoring could even run
    #: (FILTERED_DOCUMENT / FILTERED_PATH_OR_EXTENSION).
    score: ScoreComponents | None = None
    #: 1-based rank among candidates that passed the cutoff and entered
    #: ranking; None for anything excluded before or instead of ranking.
    rank: int | None = None
    selected: bool
    exclusion_reason: ExclusionReason | None = None

    @model_validator(mode="after")
    def _selection_fields_are_consistent(self) -> RetrievalCandidate:
        if self.selected and self.exclusion_reason is not None:
            raise ValueError("a selected candidate must not carry an exclusion_reason")
        if not self.selected and self.exclusion_reason is None:
            raise ValueError("an excluded candidate must carry an exclusion_reason")
        if self.score is None and self.rank is not None:
            raise ValueError("an unscored candidate cannot carry a rank")
        if self.anchor_end_line < self.anchor_start_line:
            raise ValueError("anchor_end_line must be >= anchor_start_line")
        return self


class UnavailableDocument(ResearchModel):
    """One document retrieval could not use at all: its ParseResult did
    not succeed. Recorded here, structurally separate from
    RetrievalCandidate, so an unavailable document is never represented
    as a chunk with a zero (or any) relevance score."""

    document_id: str
    relative_path: str
    reason: str


class RetrievalTrace(ResearchModel):
    """The content-derived, replayable record of one retrieval run.

    Reports how many distinct document_ids appear in the selected set
    (``distinct_selected_document_count``) and lists them
    (``selected_document_ids``) — but makes no claim that those documents
    independently corroborate anything; source independence and
    claim-level corroboration are verification's responsibility, in a
    later phase. Because the corpus itself does not deduplicate identical
    content stored at different paths (each gets its own document_id),
    ``distinct_selected_document_count`` alone could overstate how much
    truly-distinct content was selected. ``distinct_selected_content_hashes``
    is the honest, never-larger number: it collapses byte-identical
    documents at different paths to one, so duplicate content is never
    counted as independent evidence — this is the number a reader should
    treat as the ceiling on independent support, not the document count.
    """

    trace_id: str
    request_id: str
    corpus_id: str
    retrieval_policy_version: str
    normalization_policy_version: str
    tokenization_policy_version: str
    scoring_policy_version: str
    token_estimate_heuristic_version: str
    #: SHA-256 over the canonically ordered (document_id, chunk_id) pairs
    #: of every chunk supplied to retrieval.
    chunk_inventory_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_filter: DocumentFilter
    #: Normalized (not raw) query terms/tokens, in the order applied.
    normalized_query_terms: tuple[str, ...]
    #: Stable order: (relative_path, anchor_start_line, chunk_id) for
    #: every candidate, scored or not, selected or not.
    candidates: tuple[RetrievalCandidate, ...]
    unavailable_documents: tuple[UnavailableDocument, ...] = ()
    #: Selected chunk_ids in selection (rank) order — best match first.
    selected_chunk_ids: tuple[str, ...]
    #: Sorted, de-duplicated document_ids of the selected candidates.
    selected_document_ids: tuple[str, ...]
    applied_budget: RetrievalBudget
    total_selected_characters: int = Field(ge=0)
    total_estimated_selected_tokens: int = Field(ge=0)
    #: Count of distinct document_ids in the selected set — not a claim
    #: of independent corroboration. See this model's docstring.
    distinct_selected_document_count: int = Field(ge=0)
    #: Count of distinct document_content_hash values among selected
    #: candidates — never larger than distinct_selected_document_count,
    #: strictly smaller whenever two selected documents are
    #: byte-identical copies at different paths.
    distinct_selected_content_hashes: int = Field(ge=0)
    #: True if the corpus snapshot this trace was built from came from a
    #: truncated scan — retrieval over an incomplete corpus is not an
    #: exhaustive search.
    incomplete: bool
    warnings: tuple[str, ...] = ()
    #: Wall clock — excluded from trace_id; audit metadata only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _candidates_are_stably_ordered(self) -> RetrievalTrace:
        keys = [(c.relative_path, c.anchor_start_line, c.chunk_id) for c in self.candidates]
        if keys != sorted(keys):
            raise ValueError(
                "candidates must be ordered by (relative_path, anchor_start_line, chunk_id)"
            )
        return self

    @model_validator(mode="after")
    def _selected_summaries_match_candidates(self) -> RetrievalTrace:
        selected = [c for c in self.candidates if c.selected]
        ranked = sorted(selected, key=lambda c: c.rank if c.rank is not None else 0)
        expected_chunk_ids = tuple(c.chunk_id for c in ranked)
        if self.selected_chunk_ids != expected_chunk_ids:
            raise ValueError("selected_chunk_ids must match selected candidates in rank order")

        expected_document_ids = tuple(sorted({c.document_id for c in selected}))
        if self.selected_document_ids != expected_document_ids:
            raise ValueError(
                "selected_document_ids must be the sorted distinct document_ids "
                "of selected candidates"
            )
        if self.distinct_selected_document_count != len(expected_document_ids):
            raise ValueError(
                "distinct_selected_document_count must match the number of "
                "distinct selected document_ids"
            )
        expected_content_hashes = {c.document_content_hash for c in selected}
        if self.distinct_selected_content_hashes != len(expected_content_hashes):
            raise ValueError(
                "distinct_selected_content_hashes must match the number of distinct "
                "document_content_hash values among selected candidates"
            )
        if self.total_selected_characters != sum(c.char_count for c in selected):
            raise ValueError("total_selected_characters must equal the sum of selected char_count")
        if self.total_estimated_selected_tokens != sum(c.estimated_token_count for c in selected):
            raise ValueError(
                "total_estimated_selected_tokens must equal the sum of selected "
                "estimated_token_count"
            )
        return self


def _trace_id_payload(
    request_id: str,
    corpus_id: str,
    retrieval_policy_version: str,
    normalization_policy_version: str,
    tokenization_policy_version: str,
    scoring_policy_version: str,
    token_estimate_heuristic_version: str,
    chunk_inventory_hash: str,
    document_filter: DocumentFilter,
    normalized_query_terms: tuple[str, ...],
    candidates: tuple[RetrievalCandidate, ...],
    unavailable_documents: tuple[UnavailableDocument, ...],
    selected_chunk_ids: tuple[str, ...],
    selected_document_ids: tuple[str, ...],
    applied_budget: RetrievalBudget,
    total_selected_characters: int,
    total_estimated_selected_tokens: int,
    distinct_selected_document_count: int,
    distinct_selected_content_hashes: int,
    incomplete: bool,
    warnings: tuple[str, ...],
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "corpus_id": corpus_id,
        "retrieval_policy_version": retrieval_policy_version,
        "normalization_policy_version": normalization_policy_version,
        "tokenization_policy_version": tokenization_policy_version,
        "scoring_policy_version": scoring_policy_version,
        "token_estimate_heuristic_version": token_estimate_heuristic_version,
        "chunk_inventory_hash": chunk_inventory_hash,
        "document_filter": document_filter,
        "normalized_query_terms": list(normalized_query_terms),
        "candidates": list(candidates),
        "unavailable_documents": list(unavailable_documents),
        "selected_chunk_ids": list(selected_chunk_ids),
        "selected_document_ids": list(selected_document_ids),
        "applied_budget": applied_budget,
        "total_selected_characters": total_selected_characters,
        "total_estimated_selected_tokens": total_estimated_selected_tokens,
        "distinct_selected_document_count": distinct_selected_document_count,
        "distinct_selected_content_hashes": distinct_selected_content_hashes,
        "incomplete": incomplete,
        "warnings": list(warnings),
    }


def compute_trace_id(
    *,
    request_id: str,
    corpus_id: str,
    retrieval_policy_version: str,
    normalization_policy_version: str,
    tokenization_policy_version: str,
    scoring_policy_version: str,
    token_estimate_heuristic_version: str,
    chunk_inventory_hash: str,
    document_filter: DocumentFilter,
    normalized_query_terms: tuple[str, ...],
    candidates: tuple[RetrievalCandidate, ...],
    unavailable_documents: tuple[UnavailableDocument, ...],
    selected_chunk_ids: tuple[str, ...],
    selected_document_ids: tuple[str, ...],
    applied_budget: RetrievalBudget,
    total_selected_characters: int,
    total_estimated_selected_tokens: int,
    distinct_selected_document_count: int,
    distinct_selected_content_hashes: int,
    incomplete: bool,
    warnings: tuple[str, ...],
) -> str:
    """Content-derived trace identity — every field except ``created_at``."""
    return make_id(
        "TRACE",
        _trace_id_payload(
            request_id,
            corpus_id,
            retrieval_policy_version,
            normalization_policy_version,
            tokenization_policy_version,
            scoring_policy_version,
            token_estimate_heuristic_version,
            chunk_inventory_hash,
            document_filter,
            normalized_query_terms,
            candidates,
            unavailable_documents,
            selected_chunk_ids,
            selected_document_ids,
            applied_budget,
            total_selected_characters,
            total_estimated_selected_tokens,
            distinct_selected_document_count,
            distinct_selected_content_hashes,
            incomplete,
            warnings,
        ),
    )
