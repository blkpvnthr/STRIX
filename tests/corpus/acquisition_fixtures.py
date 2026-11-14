"""Shared fixtures for Phase 5 acquisition tests (download/storage/SSRF).

No test in this subtree ever touches a real socket (tests/conftest.py's
no_network autouse fixture guarantees that at the harness level) or the
real evidence root — every AcquiredDocumentStore/evidence root used here
is a pytest tmp_path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from strix.corpus.acquisition.dedup import compute_deduplication_key
from strix.corpus.acquisition.models import (
    AccessStatus,
    PeerReviewStatus,
    PublicationType,
    RetractionStatus,
    SearchPlan,
    SearchResult,
    build_search_plan,
    compute_result_id,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)

#: A minimal, well-formed PDF body: real signature, trivial structure.
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

SAFE_HOST = "docs.example.org"
#: Unambiguously public per ipaddress.IPv4Address.is_global — never
#: actually connected to; every test uses httpx.MockTransport.
SAFE_IPV4 = "93.184.216.34"
#: Unambiguously public per ipaddress.IPv6Address.is_global.
SAFE_IPV6 = "2606:4700:4700::1111"


def make_plan(**overrides: object) -> SearchPlan:
    defaults: dict[str, object] = {
        "research_question": "Is X a thing?",
        "queries": ("q1",),
        "provider": "fake",
        "provider_version": "1.0.0",
        "created_at": NOW,
    }
    defaults.update(overrides)
    return build_search_plan(**defaults)  # type: ignore[arg-type]


def make_result(
    plan: SearchPlan,
    *,
    document_url: str | None,
    access_status: AccessStatus = AccessStatus.OPEN_ACCESS,
    license: str | None = "CC-BY-4.0",
    title: str = "A Test Document",
    rank: int = 1,
) -> SearchResult:
    discovery_query = plan.queries[0]
    result_id = compute_result_id(
        plan_id=plan.plan_id,
        discovery_query=discovery_query,
        provider=plan.provider,
        title=title,
        authors=(),
        persistent_identifier=None,
        landing_page_url=None,
        document_url=document_url,
        publication_date=None,
        rank=rank,
    )
    dedup_key = compute_deduplication_key(
        persistent_identifier=None, landing_page_url=None, document_url=document_url, title=title
    )
    return SearchResult(
        result_id=result_id,
        plan_id=plan.plan_id,
        discovery_query=discovery_query,
        provider=plan.provider,
        rank=rank,
        title=title,
        authors=(),
        abstract=None,
        persistent_identifier=None,
        persistent_identifier_scheme=None,
        venue=None,
        publication_date=None,
        publication_type=PublicationType.OTHER,
        peer_review_status=PeerReviewStatus.UNKNOWN,
        retraction_status=RetractionStatus.NONE_KNOWN,
        landing_page_url=None,
        document_url=document_url,
        access_status=access_status,
        license=license,
        deduplication_key=dedup_key,
        discovered_at=NOW,
    )
