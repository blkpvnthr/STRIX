"""Typed models for scholarly search plans and candidate results.

A :class:`SearchPlan` is a fully preserved, replayable description of one
search request — exact queries, provider, constraints, and limits. A
:class:`SearchResult` is one candidate document a provider reported for
that plan: metadata only, never evidence. Both carry content-derived IDs
excluding any wall-clock field, following the same convention as every
other identity in STRIX (``strix.canonical.make_id``).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, Field, model_validator

from strix.canonical import make_id
from strix.corpus.models import CorpusModel


class PublicationType(StrEnum):
    JOURNAL_ARTICLE = "journal_article"
    CONFERENCE_PAPER = "conference_paper"
    PREPRINT = "preprint"
    THESIS = "thesis"
    REPORT = "report"
    BOOK_CHAPTER = "book_chapter"
    DATASET = "dataset"
    OTHER = "other"


class PeerReviewStatus(StrEnum):
    PEER_REVIEWED = "peer_reviewed"
    NOT_PEER_REVIEWED = "not_peer_reviewed"
    UNKNOWN = "unknown"


class RetractionStatus(StrEnum):
    NONE_KNOWN = "none_known"
    CORRECTED = "corrected"
    RETRACTED = "retracted"
    UNKNOWN = "unknown"


class AccessStatus(StrEnum):
    OPEN_ACCESS = "open_access"
    CLOSED_ACCESS = "closed_access"
    UNKNOWN = "unknown"


class DateRange(CorpusModel):
    """An inclusive, optionally open-ended date constraint."""

    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must not be after end_date")
        return self


def _plan_id_payload(
    research_question: str,
    queries: tuple[str, ...],
    provider: str,
    provider_version: str,
    date_range: DateRange,
    allowed_domains: tuple[str, ...],
    excluded_domains: tuple[str, ...],
    publication_types: tuple[PublicationType, ...],
    language: str | None,
    result_limit: int,
    download_limit: int,
    licensing_requirement: str,
) -> dict[str, object]:
    return {
        "research_question": research_question,
        "queries": list(queries),
        "provider": provider,
        "provider_version": provider_version,
        "date_range": date_range.model_dump(mode="json"),
        "allowed_domains": list(allowed_domains),
        "excluded_domains": list(excluded_domains),
        "publication_types": [item.value for item in publication_types],
        "language": language,
        "result_limit": result_limit,
        "download_limit": download_limit,
        "licensing_requirement": licensing_requirement,
    }


def compute_plan_id(
    *,
    research_question: str,
    queries: tuple[str, ...],
    provider: str,
    provider_version: str,
    date_range: DateRange,
    allowed_domains: tuple[str, ...] = (),
    excluded_domains: tuple[str, ...] = (),
    publication_types: tuple[PublicationType, ...] = (),
    language: str | None = None,
    result_limit: int = 50,
    download_limit: int = 0,
    licensing_requirement: str = "open_access_only",
) -> str:
    """Content-derived plan identity — every field except ``created_at``."""
    return make_id(
        "PLAN",
        _plan_id_payload(
            research_question,
            queries,
            provider,
            provider_version,
            date_range,
            allowed_domains,
            excluded_domains,
            publication_types,
            language,
            result_limit,
            download_limit,
            licensing_requirement,
        ),
    )


class SearchPlan(CorpusModel):
    """A fully preserved, replayable description of one search request.

    Domain suffixes in ``allowed_domains``/``excluded_domains`` are
    discovery filters, not trust guarantees — they narrow where a
    connector looks, not what may later be trusted as evidence.
    """

    plan_id: str
    research_question: str = Field(min_length=1)
    #: Exact queries, in execution order (e.g. the filetype:pdf / site:
    #: variants for one research question).
    queries: tuple[str, ...] = Field(min_length=1)
    provider: str = Field(min_length=1)
    #: Version of STRIX's own connector implementation, not the remote
    #: provider's API version — recorded for replay/drift detection, same
    #: convention as scanner_version, calculation_versions, etc.
    provider_version: str
    date_range: DateRange = DateRange()
    allowed_domains: tuple[str, ...] = ()
    excluded_domains: tuple[str, ...] = ()
    publication_types: tuple[PublicationType, ...] = ()
    language: str | None = None
    result_limit: int = Field(default=50, ge=1, le=1000)
    download_limit: int = Field(default=0, ge=0)
    #: Enforced later, by the download phase — not a schema-level restriction.
    licensing_requirement: str = "open_access_only"
    #: Wall clock — excluded from plan_id; audit metadata only.
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _plan_id_matches_content(self) -> SearchPlan:
        expected = compute_plan_id(
            research_question=self.research_question,
            queries=self.queries,
            provider=self.provider,
            provider_version=self.provider_version,
            date_range=self.date_range,
            allowed_domains=self.allowed_domains,
            excluded_domains=self.excluded_domains,
            publication_types=self.publication_types,
            language=self.language,
            result_limit=self.result_limit,
            download_limit=self.download_limit,
            licensing_requirement=self.licensing_requirement,
        )
        if self.plan_id != expected:
            raise ValueError(
                f"plan_id {self.plan_id!r} does not match its content "
                f"(expected {expected!r}); construct via build_search_plan()"
            )
        return self


def build_search_plan(
    *,
    research_question: str,
    queries: tuple[str, ...],
    provider: str,
    provider_version: str,
    created_at: AwareDatetime,
    date_range: DateRange | None = None,
    allowed_domains: tuple[str, ...] = (),
    excluded_domains: tuple[str, ...] = (),
    publication_types: tuple[PublicationType, ...] = (),
    language: str | None = None,
    result_limit: int = 50,
    download_limit: int = 0,
    licensing_requirement: str = "open_access_only",
) -> SearchPlan:
    """Construct a SearchPlan with its content-derived plan_id already set."""
    resolved_date_range = date_range if date_range is not None else DateRange()
    plan_id = compute_plan_id(
        research_question=research_question,
        queries=queries,
        provider=provider,
        provider_version=provider_version,
        date_range=resolved_date_range,
        allowed_domains=allowed_domains,
        excluded_domains=excluded_domains,
        publication_types=publication_types,
        language=language,
        result_limit=result_limit,
        download_limit=download_limit,
        licensing_requirement=licensing_requirement,
    )
    return SearchPlan(
        plan_id=plan_id,
        research_question=research_question,
        queries=queries,
        provider=provider,
        provider_version=provider_version,
        date_range=resolved_date_range,
        allowed_domains=allowed_domains,
        excluded_domains=excluded_domains,
        publication_types=publication_types,
        language=language,
        result_limit=result_limit,
        download_limit=download_limit,
        licensing_requirement=licensing_requirement,
        created_at=created_at,
    )


def compute_result_id(
    *,
    plan_id: str,
    discovery_query: str,
    provider: str,
    title: str,
    authors: tuple[str, ...],
    persistent_identifier: str | None,
    landing_page_url: str | None,
    document_url: str | None,
    publication_date: date | None,
    rank: int,
) -> str:
    """Content-derived result identity — every field except ``discovered_at``."""
    return make_id(
        "RESULT",
        {
            "plan_id": plan_id,
            "discovery_query": discovery_query,
            "provider": provider,
            "title": title,
            "authors": list(authors),
            "persistent_identifier": persistent_identifier,
            "landing_page_url": landing_page_url,
            "document_url": document_url,
            "publication_date": publication_date.isoformat() if publication_date else None,
            "rank": rank,
        },
    )


class SearchResult(CorpusModel):
    """One candidate document a provider reported for a search plan.

    Metadata only — a lead, never evidence. Nothing here supports a
    finding; only content later preserved, parsed, and anchored through
    the corpus pipeline may.
    """

    result_id: str
    plan_id: str
    #: Which of the plan's exact queries surfaced this candidate.
    discovery_query: str
    provider: str
    #: 1-based rank within (plan_id, discovery_query, provider).
    rank: int = Field(ge=1)

    title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    abstract: str | None = None
    #: Normalized identifier value (e.g. a DOI string) and its scheme.
    persistent_identifier: str | None = None
    persistent_identifier_scheme: str | None = None
    venue: str | None = None
    publication_date: date | None = None
    publication_type: PublicationType = PublicationType.OTHER
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN
    retraction_status: RetractionStatus = RetractionStatus.NONE_KNOWN
    landing_page_url: str | None = None
    document_url: str | None = None
    access_status: AccessStatus = AccessStatus.UNKNOWN
    license: str | None = None

    #: Deterministic dedup key — see strix.corpus.acquisition.dedup.
    deduplication_key: str

    #: Wall clock — excluded from result_id; audit metadata only.
    discovered_at: AwareDatetime

    @model_validator(mode="after")
    def _result_id_matches_content(self) -> SearchResult:
        expected = compute_result_id(
            plan_id=self.plan_id,
            discovery_query=self.discovery_query,
            provider=self.provider,
            title=self.title,
            authors=self.authors,
            persistent_identifier=self.persistent_identifier,
            landing_page_url=self.landing_page_url,
            document_url=self.document_url,
            publication_date=self.publication_date,
            rank=self.rank,
        )
        if self.result_id != expected:
            raise ValueError(
                f"result_id {self.result_id!r} does not match its content (expected {expected!r})"
            )
        return self


def compute_acquisition_id(
    *,
    result_id: str,
    plan_id: str,
    original_url: str,
    redirect_chain: tuple[str, ...],
    final_url: str,
    provider: str,
    persistent_identifier: str | None,
    persistent_identifier_scheme: str | None,
    license: str | None,
    access_status: AccessStatus,
    media_type: str,
    byte_size: int,
    content_hash: str,
    stored_relative_path: str,
    policy_version: str,
    downloader_version: str,
) -> str:
    """Content-derived acquisition identity — every field except
    ``retrieved_at``. URLs are expected to already be redacted by the
    caller (see ``strix.corpus.acquisition.redaction.redact_url``); this
    function does not redact them itself, so a raw secret in a URL would
    flow straight into a persisted ID — callers must not pass one."""
    return make_id(
        "ACQUISITION",
        {
            "result_id": result_id,
            "plan_id": plan_id,
            "original_url": original_url,
            "redirect_chain": list(redirect_chain),
            "final_url": final_url,
            "provider": provider,
            "persistent_identifier": persistent_identifier,
            "persistent_identifier_scheme": persistent_identifier_scheme,
            "license": license,
            "access_status": access_status.value,
            "media_type": media_type,
            "byte_size": byte_size,
            "content_hash": content_hash,
            "stored_relative_path": stored_relative_path,
            "policy_version": policy_version,
            "downloader_version": downloader_version,
        },
    )


class AcquisitionRecord(CorpusModel):
    """Immutable record of one successfully committed document acquisition.

    Constructed and persisted only *after* the document's bytes have been
    committed to storage (see
    :func:`strix.corpus.acquisition.storage.acquire_pdf`) — a record is
    never written for a fetch that failed policy, network-safety, or PDF
    validation, and never written before the storage commit succeeds.
    """

    acquisition_id: str
    result_id: str
    plan_id: str
    #: Redacted (see strix.corpus.acquisition.redaction.redact_url).
    original_url: str
    #: Redacted, in order followed.
    redirect_chain: tuple[str, ...]
    #: Redacted.
    final_url: str
    provider: str
    persistent_identifier: str | None
    persistent_identifier_scheme: str | None
    license: str | None
    access_status: AccessStatus
    media_type: str
    byte_size: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: Relative to <evidence_root>/acquired/ — content-addressed, derived
    #: from content_hash; DOI/persistent-identifier metadata is recorded
    #: above as separate fields, never encoded into this path.
    stored_relative_path: str
    policy_version: str
    downloader_version: str
    #: Wall clock — excluded from acquisition_id; audit metadata only.
    retrieved_at: AwareDatetime

    @model_validator(mode="after")
    def _acquisition_id_matches_content(self) -> AcquisitionRecord:
        expected = compute_acquisition_id(
            result_id=self.result_id,
            plan_id=self.plan_id,
            original_url=self.original_url,
            redirect_chain=self.redirect_chain,
            final_url=self.final_url,
            provider=self.provider,
            persistent_identifier=self.persistent_identifier,
            persistent_identifier_scheme=self.persistent_identifier_scheme,
            license=self.license,
            access_status=self.access_status,
            media_type=self.media_type,
            byte_size=self.byte_size,
            content_hash=self.content_hash,
            stored_relative_path=self.stored_relative_path,
            policy_version=self.policy_version,
            downloader_version=self.downloader_version,
        )
        if self.acquisition_id != expected:
            raise ValueError(
                f"acquisition_id {self.acquisition_id!r} does not match its "
                f"content (expected {expected!r})"
            )
        return self
