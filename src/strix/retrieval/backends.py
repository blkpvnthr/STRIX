"""Pluggable search backends with a BM25 offline baseline (§8).

STRIX's exact-Decimal BM25 engine is the always-available local baseline. An
external lexical engine (OpenSearch / Elasticsearch) is modelled as an adapter that
delegates to an injected client and FAILS CLOSED when no cluster is reachable.
:func:`select_search_backend` prefers an available external backend but falls back
to BM25 — it never silently returns nothing. Ranking scores are relevance signals,
NOT verification certificates or factual-confidence probabilities.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from strix.errors import CalculationError
from strix.models import DecimalValue
from strix.retrieval.bm25 import BM25Parameters, SearchResult, search
from strix.retrieval.index import InvertedIndex


class SearchBackendKind(StrEnum):
    """Which engine served a query."""

    LEXICAL = "lexical_bm25"
    EXTERNAL = "external_cluster"


@runtime_checkable
class SearchBackend(Protocol):
    """A ranked lexical search backend."""

    @property
    def kind(self) -> SearchBackendKind: ...

    def available(self) -> bool: ...

    def search(self, query: str, *, limit: int | None = None) -> tuple[SearchResult, ...]: ...


class LexicalSearchBackend:
    """The local, always-available BM25 backend over an in-memory index."""

    kind = SearchBackendKind.LEXICAL

    def __init__(self, index: InvertedIndex, *, params: BM25Parameters) -> None:
        self._index = index
        self._params = params

    def available(self) -> bool:
        return True

    def search(self, query: str, *, limit: int | None = None) -> tuple[SearchResult, ...]:
        return search(query, self._index, params=self._params, limit=limit)


@runtime_checkable
class SearchClient(Protocol):
    """Minimal contract an external cluster client must satisfy.

    Returns an ordered list of ``{"doc_id": str, "score": str|int|Decimal}`` hits,
    best first. Scores are strings/ints (never floats) to preserve the no-float
    discipline across the boundary.
    """

    def query(self, index_name: str, query_text: str, size: int) -> list[dict[str, object]]: ...


class ExternalSearchAdapter:
    """Adapter for an external OpenSearch/Elasticsearch cluster.

    Holds an injected :class:`SearchClient`; without one it is unavailable and
    :meth:`search` fails closed. This lets the adapter and its contract be
    implemented and tested offline, with a real client supplied in production.
    """

    kind = SearchBackendKind.EXTERNAL

    def __init__(
        self, *, index_name: str, client: SearchClient | None = None, default_size: int = 10
    ) -> None:
        self._index_name = index_name
        self._client = client
        self._default_size = default_size

    def available(self) -> bool:
        return self._client is not None

    def search(self, query: str, *, limit: int | None = None) -> tuple[SearchResult, ...]:
        if limit is not None and limit < 0:
            raise ValueError(f"limit must be non-negative, got {limit}")
        if self._client is None:
            raise CalculationError(
                "external search backend unavailable: no cluster client configured"
            )
        size = self._default_size if limit is None else limit
        rows = self._client.query(self._index_name, query, size)
        hits: list[SearchResult] = []
        for i, row in enumerate(rows):
            doc_id = row.get("doc_id")
            raw_score = row.get("score")
            if not isinstance(doc_id, str) or isinstance(raw_score, float):
                raise CalculationError(
                    "external search hit must carry a str doc_id and a non-float score"
                )
            hits.append(
                SearchResult(
                    doc_id=doc_id,
                    score=_as_decimal_value(raw_score),
                    rank=i + 1,
                )
            )
        return tuple(hits)


def _as_decimal_value(value: object) -> DecimalValue:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(value)
    raise CalculationError(f"unsupported score type {type(value).__name__}")


def select_search_backend(
    *,
    external: SearchBackend | None,
    fallback: SearchBackend,
    candidates: Sequence[SearchBackend] = (),
) -> SearchBackend:
    """Return the first available backend, preferring ``external`` then
    ``candidates``, else the always-available ``fallback``.

    Never returns an unavailable backend, so a caller can always serve a query.
    """
    for backend in (external, *candidates):
        if backend is not None and backend.available():
            return backend
    return fallback
