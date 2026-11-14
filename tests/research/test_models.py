"""Tests for ResearchRequest/RetrievalTrace model construction: stable
content-derived IDs, contradictory-filter rejection, and
impossible-budget rejection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from strix.research.models import (
    CorroborationRequirement,
    DocumentFilter,
    ResearchRequest,
    RetrievalBudget,
    build_research_request,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CORPUS_ID = "CORPUS-abc123"


def test_request_id_is_content_derived_and_stable() -> None:
    request = build_research_request(
        corpus_id=CORPUS_ID, question="Q?", query_terms=("fox",), created_at=NOW
    )
    assert request.request_id.startswith("REQUEST-")


def test_request_id_excludes_created_at() -> None:
    request1 = build_research_request(
        corpus_id=CORPUS_ID,
        question="Q?",
        query_terms=("fox",),
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    request2 = build_research_request(
        corpus_id=CORPUS_ID,
        question="Q?",
        query_terms=("fox",),
        created_at=datetime(2030, 6, 15, tzinfo=UTC),
    )
    assert request1.request_id == request2.request_id
    assert request1.created_at != request2.created_at


def test_request_id_changes_with_query_terms() -> None:
    r1 = build_research_request(
        corpus_id=CORPUS_ID, question="Q?", query_terms=("fox",), created_at=NOW
    )
    r2 = build_research_request(
        corpus_id=CORPUS_ID, question="Q?", query_terms=("dog",), created_at=NOW
    )
    assert r1.request_id != r2.request_id


def test_constructing_a_request_with_a_wrong_request_id_is_rejected() -> None:
    request = build_research_request(
        corpus_id=CORPUS_ID, question="Q?", query_terms=("fox",), created_at=NOW
    )
    with pytest.raises(ValidationError):
        ResearchRequest(**{**request.model_dump(), "request_id": "REQUEST-" + "0" * 12})


def test_empty_query_terms_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_research_request(corpus_id=CORPUS_ID, question="Q?", query_terms=(), created_at=NOW)


def test_blank_only_query_terms_are_rejected() -> None:
    with pytest.raises(ValidationError):
        build_research_request(
            corpus_id=CORPUS_ID, question="Q?", query_terms=("   ", "!!!"), created_at=NOW
        )


def test_contradictory_document_id_filter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DocumentFilter(allowed_document_ids=("DOC-1",), excluded_document_ids=("DOC-1",))


def test_contradictory_path_filter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DocumentFilter(allowed_relative_paths=("a.txt",), excluded_relative_paths=("a.txt",))


def test_contradictory_extension_filter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DocumentFilter(allowed_extensions=(".txt",), excluded_extensions=(".txt",))


def test_impossible_budget_max_selected_exceeds_max_candidate_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RetrievalBudget(max_candidate_chunks=5, max_selected_chunks=10)


def test_impossible_corroboration_versus_selected_chunk_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_research_request(
            corpus_id=CORPUS_ID,
            question="Q?",
            query_terms=("fox",),
            created_at=NOW,
            corroboration=CorroborationRequirement(minimum_independent_documents=10),
            budget=RetrievalBudget(max_selected_chunks=3),
        )


def test_request_is_frozen() -> None:
    request = build_research_request(
        corpus_id=CORPUS_ID, question="Q?", query_terms=("fox",), created_at=NOW
    )
    with pytest.raises(ValidationError):
        request.question = "changed"  # type: ignore[misc]
