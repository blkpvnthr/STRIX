"""The SearchConnector protocol — the seam where a search provider plugs in.

A connector executes a :class:`SearchPlan` and returns the
:class:`SearchResult` candidates a provider reported for it. It must not
scrape search-engine result pages, execute scripts, determine source
trust, follow arbitrary links automatically, or download anything —
results are metadata-level leads, not evidence. No real provider
connector exists yet; only :class:`~strix.corpus.acquisition.connectors.
fake.FakeSearchConnector` does, so this protocol can be exercised offline.
"""

from __future__ import annotations

from typing import Protocol

from strix.corpus.acquisition.models import SearchPlan, SearchResult


class SearchConnector(Protocol):
    """Executes a search plan against one provider; returns candidates."""

    def search(self, plan: SearchPlan) -> tuple[SearchResult, ...]:
        """Run every query in *plan* and return the candidates found."""
        ...
