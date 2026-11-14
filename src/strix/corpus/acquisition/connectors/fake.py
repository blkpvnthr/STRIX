"""Deterministic, offline, fixture-backed SearchConnector.

Exercises the :class:`~strix.corpus.acquisition.connectors.base.
SearchConnector` protocol end to end with no network access and no real
literature — a stub to validate the search/acquisition contracts until an
approved real provider connector (Crossref, OpenAlex, arXiv, PubMed, ...)
is added in a later, explicitly-approved phase. The same plan always
produces the same results: no randomness, no wall clock in any returned
content field.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from strix.corpus.acquisition.dedup import compute_deduplication_key
from strix.corpus.acquisition.models import (
    AccessStatus,
    PeerReviewStatus,
    PublicationType,
    RetractionStatus,
    SearchPlan,
    SearchResult,
    compute_result_id,
)
from strix.errors import AcquisitionError


@dataclass(frozen=True)
class FixtureCandidate:
    """One canned candidate's publication metadata (pre-ranking, pre-ID)."""

    title: str
    authors: tuple[str, ...] = ()
    abstract: str | None = None
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


#: Built-in deterministic fixture data, keyed by exact query string. Purely
#: illustrative — not real literature — and offline: no file I/O, no
#: network. Replaceable per-instance via FakeSearchConnector(fixture=...).
DEFAULT_FIXTURE: Mapping[str, tuple[FixtureCandidate, ...]] = {
    '"neuro-symbolic reasoning" filetype:pdf': (
        FixtureCandidate(
            title="Neuro-Symbolic AI: The 3rd Wave (Demonstration Fixture)",
            authors=("Garcez, A.", "Lamb, L."),
            abstract="A survey of neuro-symbolic integration approaches. Synthetic fixture data.",
            persistent_identifier="10.9999/fake-nesy-2020",
            persistent_identifier_scheme="doi",
            venue="Fake Journal of Artificial Intelligence",
            publication_date=date(2020, 5, 1),
            publication_type=PublicationType.JOURNAL_ARTICLE,
            peer_review_status=PeerReviewStatus.PEER_REVIEWED,
            landing_page_url="https://example.org/fixtures/nesy-2020",
            document_url="https://example.org/fixtures/nesy-2020.pdf",
            access_status=AccessStatus.OPEN_ACCESS,
            license="CC-BY-4.0",
        ),
        FixtureCandidate(
            title="Combining Neural and Symbolic Methods (Demonstration Fixture)",
            authors=("Doe, J.",),
            abstract="A second synthetic fixture candidate for the same query.",
            persistent_identifier="10.9999/fake-nesy-2021",
            persistent_identifier_scheme="doi",
            venue="Fake Conference on Hybrid AI",
            publication_date=date(2021, 3, 15),
            publication_type=PublicationType.CONFERENCE_PAPER,
            peer_review_status=PeerReviewStatus.PEER_REVIEWED,
            landing_page_url="https://example.org/fixtures/nesy-2021",
            document_url="https://example.org/fixtures/nesy-2021.pdf",
            access_status=AccessStatus.CLOSED_ACCESS,
            license=None,
        ),
    ),
    '"neuro-symbolic reasoning" site:.edu filetype:pdf': (
        FixtureCandidate(
            title="A University Technical Report on Hybrid Reasoning (Demonstration Fixture)",
            authors=("Researcher, R.",),
            venue="Fake University Technical Reports",
            publication_date=date(2019, 11, 1),
            publication_type=PublicationType.REPORT,
            peer_review_status=PeerReviewStatus.NOT_PEER_REVIEWED,
            landing_page_url="https://example.edu/fixtures/report-19",
            document_url="https://example.edu/fixtures/report-19.pdf",
            access_status=AccessStatus.OPEN_ACCESS,
            license="public-domain",
        ),
    ),
}


class FakeSearchConnector:
    """Deterministic fixture-backed SearchConnector. No network, ever."""

    PROVIDER = "fake"
    PROVIDER_VERSION = "1.0.0"

    def __init__(
        self,
        fixture: Mapping[str, Sequence[FixtureCandidate]] | None = None,
    ) -> None:
        self._fixture: Mapping[str, Sequence[FixtureCandidate]] = (
            fixture if fixture is not None else DEFAULT_FIXTURE
        )

    def search(self, plan: SearchPlan) -> tuple[SearchResult, ...]:
        """Run every query in *plan* against the fixture; no live calls."""
        if plan.provider != self.PROVIDER:
            raise AcquisitionError(
                f"FakeSearchConnector cannot execute a plan for provider "
                f"{plan.provider!r} (expected {self.PROVIDER!r})"
            )
        results: list[SearchResult] = []
        for query in plan.queries:
            for rank, candidate in enumerate(self._fixture.get(query, ()), start=1):
                results.append(self._build_result(plan, query, rank, candidate))
        return tuple(results)

    def _build_result(
        self, plan: SearchPlan, query: str, rank: int, candidate: FixtureCandidate
    ) -> SearchResult:
        deduplication_key = compute_deduplication_key(
            persistent_identifier=candidate.persistent_identifier,
            landing_page_url=candidate.landing_page_url,
            document_url=candidate.document_url,
            title=candidate.title,
            venue=candidate.venue,
            publication_date=candidate.publication_date,
        )
        result_id = compute_result_id(
            plan_id=plan.plan_id,
            discovery_query=query,
            provider=self.PROVIDER,
            title=candidate.title,
            authors=candidate.authors,
            persistent_identifier=candidate.persistent_identifier,
            landing_page_url=candidate.landing_page_url,
            document_url=candidate.document_url,
            publication_date=candidate.publication_date,
            rank=rank,
        )
        return SearchResult(
            result_id=result_id,
            plan_id=plan.plan_id,
            discovery_query=query,
            provider=self.PROVIDER,
            rank=rank,
            title=candidate.title,
            authors=candidate.authors,
            abstract=candidate.abstract,
            persistent_identifier=candidate.persistent_identifier,
            persistent_identifier_scheme=candidate.persistent_identifier_scheme,
            venue=candidate.venue,
            publication_date=candidate.publication_date,
            publication_type=candidate.publication_type,
            peer_review_status=candidate.peer_review_status,
            retraction_status=candidate.retraction_status,
            landing_page_url=candidate.landing_page_url,
            document_url=candidate.document_url,
            access_status=candidate.access_status,
            license=candidate.license,
            deduplication_key=deduplication_key,
            discovered_at=plan.created_at,
        )
