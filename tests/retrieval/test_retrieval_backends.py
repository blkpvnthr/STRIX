"""Tests for the search-backend abstraction (§8).

A pluggable search layer with the exact-Decimal BM25 engine as the always-available
offline baseline and an external (OpenSearch/Elasticsearch) adapter that fails
closed without a reachable cluster. ``select_search_backend`` prefers an available
external backend but falls back to BM25 — never silently returning nothing.
"""

from __future__ import annotations

from strix.errors import CalculationError
from strix.retrieval.backends import (
    ExternalSearchAdapter,
    LexicalSearchBackend,
    SearchBackendKind,
    select_search_backend,
)
from strix.retrieval.bm25 import DEFAULT_BM25_PARAMETERS
from strix.retrieval.index import Document, build_index

_CORPUS = (
    Document(doc_id="a", text="the quick brown fox"),
    Document(doc_id="b", text="the lazy dog"),
    Document(doc_id="c", text="quick quick fox"),
)


def _lexical() -> LexicalSearchBackend:
    return LexicalSearchBackend(build_index(_CORPUS), params=DEFAULT_BM25_PARAMETERS)


# --- lexical (BM25) backend -----------------------------------------------


def test_lexical_backend_is_always_available() -> None:
    backend = _lexical()
    assert backend.available() is True
    assert backend.kind is SearchBackendKind.LEXICAL


def test_lexical_backend_ranks_like_bm25() -> None:
    hits = _lexical().search("quick", limit=10)
    assert [h.doc_id for h in hits] == ["c", "a"]
    assert hits[0].score > hits[1].score


# --- external adapter (fails closed without a cluster) --------------------


def test_external_adapter_unavailable_without_client() -> None:
    adapter = ExternalSearchAdapter(index_name="strix", client=None)
    assert adapter.available() is False
    with __import__("pytest").raises(CalculationError):
        adapter.search("quick", limit=5)


def test_external_adapter_delegates_to_an_injected_client() -> None:
    class FakeClient:
        def query(self, index_name: str, query_text: str, size: int) -> list[dict[str, object]]:
            assert index_name == "strix"
            return [
                {"doc_id": "c", "score": "2.5"},
                {"doc_id": "a", "score": "1.1"},
            ][:size]

    adapter = ExternalSearchAdapter(index_name="strix", client=FakeClient())
    assert adapter.available() is True
    hits = adapter.search("quick", limit=5)
    assert [h.doc_id for h in hits] == ["c", "a"]
    assert hits[0].rank == 1 and hits[1].rank == 2
    assert hits[0].score > hits[1].score


# --- fallback selection ----------------------------------------------------


def test_select_prefers_available_external_backend() -> None:
    class FakeClient:
        def query(self, index_name: str, query_text: str, size: int) -> list[dict[str, object]]:
            return [{"doc_id": "x", "score": "9"}]

    external = ExternalSearchAdapter(index_name="strix", client=FakeClient())
    chosen = select_search_backend(external=external, fallback=_lexical())
    assert chosen.kind is SearchBackendKind.EXTERNAL


def test_select_falls_back_to_bm25_when_external_unavailable() -> None:
    external = ExternalSearchAdapter(index_name="strix", client=None)
    chosen = select_search_backend(external=external, fallback=_lexical())
    assert chosen.kind is SearchBackendKind.LEXICAL
    # The fallback actually works (never silently returns nothing).
    assert [h.doc_id for h in chosen.search("quick", limit=10)] == ["c", "a"]


def test_select_uses_fallback_when_no_external_given() -> None:
    chosen = select_search_backend(external=None, fallback=_lexical())
    assert chosen.kind is SearchBackendKind.LEXICAL
