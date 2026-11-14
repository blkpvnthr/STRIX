"""Tests for Phase 4: search/acquisition contracts.

Purely in-memory — no filesystem, no network, no real docs/ directory
involved anywhere in this module. The suite-wide no_network autouse
fixture (tests/conftest.py) also guards against any accidental network
use, though nothing here is network-capable in the first place.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from strix.corpus.acquisition.connectors.fake import (
    DEFAULT_FIXTURE,
    FakeSearchConnector,
    FixtureCandidate,
)
from strix.corpus.acquisition.dedup import (
    canonicalize_url,
    compute_deduplication_key,
    deduplicate_results,
)
from strix.corpus.acquisition.models import (
    AccessStatus,
    DateRange,
    SearchPlan,
    SearchResult,
    build_search_plan,
    compute_result_id,
)
from strix.errors import AcquisitionError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_plan(**overrides: object) -> SearchPlan:
    defaults: dict[str, object] = {
        "research_question": "Is neuro-symbolic reasoning viable for research platforms?",
        "queries": ('"neuro-symbolic reasoning" filetype:pdf',),
        "provider": "fake",
        "provider_version": FakeSearchConnector.PROVIDER_VERSION,
        "created_at": NOW,
    }
    defaults.update(overrides)
    return build_search_plan(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# SearchPlan
# --------------------------------------------------------------------------


def test_build_search_plan_sets_a_content_derived_plan_id() -> None:
    plan = _make_plan()
    assert plan.plan_id.startswith("PLAN-")


def test_plan_id_excludes_created_at() -> None:
    plan1 = _make_plan(created_at=datetime(2020, 1, 1, tzinfo=UTC))
    plan2 = _make_plan(created_at=datetime(2030, 6, 15, tzinfo=UTC))
    assert plan1.plan_id == plan2.plan_id
    assert plan1.created_at != plan2.created_at


def test_plan_id_changes_with_queries() -> None:
    plan1 = _make_plan(queries=('"a" filetype:pdf',))
    plan2 = _make_plan(queries=('"b" filetype:pdf',))
    assert plan1.plan_id != plan2.plan_id


def test_constructing_a_plan_with_a_wrong_plan_id_is_rejected() -> None:
    plan = _make_plan()
    with pytest.raises(ValidationError):
        SearchPlan(**{**plan.model_dump(), "plan_id": "PLAN-" + "0" * 12})


def test_queries_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        _make_plan(queries=())


def test_date_range_rejects_start_after_end() -> None:
    with pytest.raises(ValidationError):
        DateRange(start_date=date(2020, 1, 1), end_date=date(2019, 1, 1))


def test_plan_is_frozen() -> None:
    plan = _make_plan()
    with pytest.raises(ValidationError):
        plan.research_question = "changed"  # type: ignore[misc]


# --------------------------------------------------------------------------
# SearchResult
# --------------------------------------------------------------------------


def test_result_id_is_content_derived_and_self_consistent() -> None:
    plan = _make_plan()
    results = FakeSearchConnector().search(plan)
    assert results
    for result in results:
        assert result.result_id.startswith("RESULT-")


def test_constructing_a_result_with_a_wrong_result_id_is_rejected() -> None:
    plan = _make_plan()
    result = FakeSearchConnector().search(plan)[0]
    with pytest.raises(ValidationError):
        SearchResult(**{**result.model_dump(), "result_id": "RESULT-" + "0" * 12})


def test_result_id_excludes_discovered_at() -> None:
    first = compute_result_id(
        plan_id="PLAN-abc",
        discovery_query="q",
        provider="fake",
        title="T",
        authors=(),
        persistent_identifier=None,
        landing_page_url=None,
        document_url=None,
        publication_date=None,
        rank=1,
    )
    second = compute_result_id(
        plan_id="PLAN-abc",
        discovery_query="q",
        provider="fake",
        title="T",
        authors=(),
        persistent_identifier=None,
        landing_page_url=None,
        document_url=None,
        publication_date=None,
        rank=1,
    )
    assert first == second  # no timestamp parameter exists to vary


# --------------------------------------------------------------------------
# FakeSearchConnector
# --------------------------------------------------------------------------


def test_fake_connector_is_deterministic() -> None:
    plan = _make_plan()
    first = FakeSearchConnector().search(plan)
    second = FakeSearchConnector().search(plan)
    assert first == second


def test_fake_connector_rejects_a_plan_for_a_different_provider() -> None:
    plan = _make_plan(provider="crossref", provider_version="1.0.0")
    with pytest.raises(AcquisitionError):
        FakeSearchConnector().search(plan)


def test_fake_connector_returns_empty_for_an_unknown_query() -> None:
    plan = _make_plan(queries=("no such query exists",))
    assert FakeSearchConnector().search(plan) == ()


def test_fake_connector_ranks_candidates_starting_at_one() -> None:
    plan = _make_plan()
    results = FakeSearchConnector().search(plan)
    ranks = [result.rank for result in results]
    assert ranks == list(range(1, len(ranks) + 1))


def test_fake_connector_aggregates_multiple_queries_in_one_plan() -> None:
    plan = _make_plan(
        queries=(
            '"neuro-symbolic reasoning" filetype:pdf',
            '"neuro-symbolic reasoning" site:.edu filetype:pdf',
        )
    )
    results = FakeSearchConnector().search(plan)
    queries_seen = {result.discovery_query for result in results}
    assert queries_seen == set(plan.queries)
    assert len(results) == len(DEFAULT_FIXTURE[plan.queries[0]]) + len(
        DEFAULT_FIXTURE[plan.queries[1]]
    )


def test_fake_connector_accepts_an_injected_fixture() -> None:
    custom_fixture = {
        "custom query": (FixtureCandidate(title="Custom Candidate"),),
    }
    plan = _make_plan(queries=("custom query",))
    connector = FakeSearchConnector(fixture=custom_fixture)
    results = connector.search(plan)
    assert len(results) == 1
    assert results[0].title == "Custom Candidate"
    assert results[0].access_status is AccessStatus.UNKNOWN


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------


def test_canonicalize_url_normalizes_case_slash_and_tracking_params() -> None:
    assert canonicalize_url("HTTPS://Example.com/Path/") == "https://example.com/Path"
    assert canonicalize_url("https://example.com/path?utm_source=x&b=2&a=1") == (
        "https://example.com/path?a=1&b=2"
    )
    assert canonicalize_url(None) is None
    assert canonicalize_url("") is None


def test_dedup_key_prefers_persistent_identifier_over_url() -> None:
    key = compute_deduplication_key(
        persistent_identifier="10.1/ABC",
        landing_page_url="https://example.com/x",
        title="T",
    )
    assert key == "pid:10.1/abc"


def test_dedup_key_falls_back_to_canonical_url() -> None:
    key = compute_deduplication_key(
        persistent_identifier=None,
        landing_page_url="https://example.com/x/",
        title="T",
    )
    assert key == "url:https://example.com/x"


def test_dedup_key_falls_back_to_hashed_metadata_when_nothing_else_available() -> None:
    key1 = compute_deduplication_key(persistent_identifier=None, title="Same Title")
    key2 = compute_deduplication_key(persistent_identifier=None, title="Same Title")
    key3 = compute_deduplication_key(persistent_identifier=None, title="Different Title")
    assert key1 == key2
    assert key1 != key3
    assert key1.startswith("fallback:")


def test_deduplicate_results_keeps_first_occurrence_per_key() -> None:
    plan = _make_plan(
        queries=(
            '"neuro-symbolic reasoning" filetype:pdf',
            '"neuro-symbolic reasoning" filetype:pdf',  # deliberately repeated
        )
    )
    results = FakeSearchConnector().search(plan)
    assert len(results) == 2 * len(DEFAULT_FIXTURE[plan.queries[0]])

    deduplicated = deduplicate_results(results)
    assert len(deduplicated) == len(DEFAULT_FIXTURE[plan.queries[0]])
    assert len({r.deduplication_key for r in deduplicated}) == len(deduplicated)
