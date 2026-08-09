"""Data source connectors and the normalized source-document contract.

Two connectors exist in this version:

- :mod:`strix.sources.demo` — the bundled synthetic fixture (fully offline).
- :mod:`strix.sources.edgar` — SEC EDGAR company facts (real filings; the
  network is used only at fetch time, and the fetched bytes are preserved in
  the run directory so replay is always offline).

:func:`parse_source` is the deterministic dispatcher used by both the live
pipeline and replay: given preserved raw bytes, a source type, and the
research parameters, it always reproduces the same normalized document.
"""

from __future__ import annotations

from datetime import date

from strix.errors import SourceError
from strix.models import SourceType
from strix.sources.base import FetchedSource, SourceConnector, SourceDocument

__all__ = [
    "FetchedSource",
    "SourceConnector",
    "SourceDocument",
    "connector_for",
    "parse_source",
]


def parse_source(
    source_type: SourceType, raw: bytes, *, ticker: str, as_of_date: date
) -> SourceDocument:
    """Deterministically parse preserved raw source bytes.

    Identical ``(source_type, raw, ticker, as_of_date)`` inputs always yield
    an identical document; replay relies on this.
    """
    if source_type is SourceType.SYNTHETIC_FIXTURE:
        from strix.sources.demo import parse_demo_fixture

        return parse_demo_fixture(raw)
    if source_type is SourceType.SEC_EDGAR_COMPANYFACTS:
        from strix.sources.edgar import parse_companyfacts

        return parse_companyfacts(raw, ticker=ticker, as_of_date=as_of_date)
    raise SourceError(f"unsupported source type: {source_type}")


def connector_for(ticker: str) -> SourceConnector:
    """Select the connector for a ticker: DEMO is offline, the rest is EDGAR."""
    from strix.sources.demo import DEMO_TICKER, DemoConnector
    from strix.sources.edgar import EdgarConnector

    if ticker.upper() == DEMO_TICKER:
        return DemoConnector()
    return EdgarConnector()
